import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
import pytz
from arq import create_pool
from arq.connections import RedisSettings
from redis import Redis as _RedisSync
from database import (get_active_schedule_rows, log_intake, apply_intake_stock,
                      apply_intake_hearts, get_today_intake_statuses,
                      get_schedules_by_medication, get_or_create_user, get_medication_by_id,
                      get_caregiver_tids_for_dependent, get_dep_share_viewer_tids,
                      get_wish_digest_candidates, mark_wish_reactions_digested)
from utils import escape_html, get_tz_for_user, local_day_bounds_utc
# _rule_fires_today живёт в schedule_utils (чистая логика, без telegram/db);
# реэкспорт для обратной совместимости: stats/export/timezone импортируют его отсюда.
from schedule_utils import _rule_fires_today, days_of_stock_left, cycle_dose_for_day

logger = logging.getLogger(__name__)

_arq_pool = None


async def init_arq_pool():
    global _arq_pool
    # AX8: единый REDIS_URL вместо дефолтного localhost.
    _arq_pool = await create_pool(RedisSettings.from_dsn(REDIS_URL))
    logger.info("ARQ pool инициализирован")

from constants import MEAL_LABELS_TEXT as _MEAL_LABELS  # noqa: E402 (alias для обратной совместимости)

# AX4: окно догона для once-слотов (минут после времени напоминания)
CATCHUP_MIN = 5

# (telegram_id, medication_id, reminder_time) -> datetime (UTC) последней отправки
_pending: dict = {}
# (telegram_id, medication_id, reminder_time) -> datetime (UTC) ПЕРВОЙ отправки
# в текущем цикле повтора. Окно repeat считается от него; _pending же освежается
# каждой отправкой (для паузы 300с). Раньше окно считалось от _pending → каждый
# повтор сбрасывал отсчёт, и условие остановки `>= repeat_window` было недостижимо
# (повтор шёл вечно каждые ~5 мин). См. фикс «repeat не выключается».
_repeat_anchor: dict = {}
# (telegram_id, medication_id, reminder_time, date_iso) — слоты, отмеченные сегодня
# (taken/skipped через TG-кнопку или строгий режим). Подавляет и догон, и повтор:
# раньше callback просто pop'ил _pending, и догон в окне CATCHUP_MIN пере-отправлял
# напоминание (юзер жмёт «принял» → через минуту приходит снова). См. фикс «догон
# пере-взводит напоминание после отметки».
_marked_today: set = set()
# (telegram_id, date_iso) — пользователи, которым план дня уже отправлен сегодня
_daily_plan_sent: set = set()

# Ф15: (telegram_id, date_iso) — кому TG-дайджест откликов уже отправлен сегодня.
_wish_digest_sent: set = set()
# Локальное время отправки дайджеста откликов (HH:MM в TZ юзера).
WISH_DIGEST_TIME = "20:00"

# AX6: персист состояния планировщика в Redis — переживает рестарт бота
# (иначе после рестарта в окне догона CATCHUP_MIN once-слот отправился бы повторно).
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_STATE_KEY = "scheduler:state"
_state_loaded = False
_redis_conn = None


def _redis_sync():
    global _redis_conn
    if _redis_conn is None:
        _redis_conn = _RedisSync.from_url(REDIS_URL)
    return _redis_conn


def _load_state():
    """Загружает _pending / _daily_plan_sent из Redis (один раз на старте)."""
    global _state_loaded
    _state_loaded = True
    try:
        raw = _redis_sync().get(_STATE_KEY)
        if raw:
            data = json.loads(raw)
            for tid, med, t, iso in data.get("pending", []):
                _pending[(tid, med, t)] = datetime.fromisoformat(iso)
            for tid, med, t, iso in data.get("repeat_anchor", []):
                _repeat_anchor[(tid, med, t)] = datetime.fromisoformat(iso)
            for tid, med, t, d in data.get("marked_today", []):
                _marked_today.add((tid, med, t, d))
            for tid, d in data.get("daily_plan_sent", []):
                _daily_plan_sent.add((tid, d))
            for tid, d in data.get("wish_digest_sent", []):
                _wish_digest_sent.add((tid, d))
            logger.info("scheduler: состояние восстановлено из Redis (pending=%d)", len(_pending))
    except Exception as e:
        logger.warning("scheduler: не удалось загрузить состояние из Redis: %s", e)


def _save_state():
    """Сохраняет состояние планировщика в Redis (TTL 2ч, как окно _pending)."""
    try:
        data = {
            "pending": [[k[0], k[1], k[2], ts.isoformat()] for k, ts in _pending.items()],
            "repeat_anchor": [[k[0], k[1], k[2], ts.isoformat()] for k, ts in _repeat_anchor.items()],
            "marked_today": [[k[0], k[1], k[2], k[3]] for k in _marked_today],
            "daily_plan_sent": [[k[0], k[1]] for k in _daily_plan_sent],
            "wish_digest_sent": [[k[0], k[1]] for k in _wish_digest_sent],
        }
        _redis_sync().set(_STATE_KEY, json.dumps(data), ex=7200)
    except Exception as e:
        logger.warning("scheduler: не удалось сохранить состояние в Redis: %s", e)


def clear_pending_for_medication(medication_id: int):
    """Удаляет все pending-записи для указанного лекарства (вызывается при деактивации)."""
    for key in [k for k in _pending if k[1] == medication_id]:
        del _pending[key]
    for key in [k for k in _repeat_anchor if k[1] == medication_id]:
        del _repeat_anchor[key]


def _prune_pending(now_utc: datetime):
    """Удаляет из _pending записи старше 12 часов (макс. окно repeat)."""
    cutoff = now_utc - timedelta(seconds=43200)
    for key in [k for k, ts in _pending.items() if ts < cutoff]:
        del _pending[key]
    # Якорь без живого _pending не нужен (плюс защита от утечки по времени).
    for key in [k for k, ts in _repeat_anchor.items() if k not in _pending or ts < cutoff]:
        del _repeat_anchor[key]
    # _marked_today: держим только сегодня/вчера (локальные даты ±1 от UTC).
    day_cutoff = (now_utc.date() - timedelta(days=2)).isoformat()
    for key in [k for k in _marked_today if k[3] < day_cutoff]:
        _marked_today.discard(key)


async def send_reminders(app):
    """Проверяет расписание и отправляет напоминания с учётом TZ каждого пользователя."""
    try:
        await _send_reminders_impl(app)
        from alerter import on_scheduler_ok
        on_scheduler_ok()
    except Exception as exc:
        from alerter import on_scheduler_error
        on_scheduler_error(exc)


async def _send_reminders_impl(app):
    now_utc = datetime.now(pytz.utc)
    # AX6: восстановить состояние из Redis при первом проходе после старта.
    if not _state_loaded:
        await asyncio.to_thread(_load_state)
    _prune_pending(now_utc)
    # B3: синхронный psycopg-запрос не должен блокировать event loop каждую минуту.
    schedules = await asyncio.to_thread(get_active_schedule_rows)

    sent = errors = 0

    for row in schedules:
        try:
            user_tz = pytz.timezone(row["timezone"] or "UTC")
        except Exception:
            user_tz = pytz.utc

        now_local = datetime.now(user_tz)
        key = (row["telegram_id"], row["medication_id"], row["reminder_time"])

        if not _rule_fires_today(row, now_local.date()):
            continue

        # Слот уже отмечен сегодня (TG-кнопка / строгий режим) → не напоминаем
        # повторно. Гасит и догон, и повтор, не завися от _pending.
        if (key[0], key[1], key[2], now_local.date().isoformat()) in _marked_today:
            _pending.pop(key, None)
            _repeat_anchor.pop(key, None)
            continue

        # AX4: окно догона вместо точного «== ЧЧ:ММ». Если проход планировщика
        # задержался/пропустил минуту (GC, медленный запрос, рестарт), once-слот
        # всё равно сработает в пределах CATCHUP_MIN минут после своего времени.
        # `since` — сколько минут прошло сегодня с момента слота (только вперёд).
        try:
            rh, rm = row["reminder_time"].split(":")
            reminder_min = int(rh) * 60 + int(rm)
        except (ValueError, AttributeError):
            continue
        now_min = now_local.hour * 60 + now_local.minute
        since = now_min - reminder_min
        already = key in _pending  # слот уже отправлялся в этом цикле

        should_send = False
        if not already and 0 <= since <= CATCHUP_MIN:
            should_send = True  # первая отправка: точная минута ИЛИ догон после пропуска
        elif row["reminder_mode"] == "repeat" and already:
            # Окно повтора считаем от ПЕРВОЙ отправки (anchor), пауза между
            # повторами — от последней (_pending). Раньше окно мерялось от
            # _pending, который освежался каждым повтором → отсчёт сбрасывался,
            # `>= repeat_window` не достигалось, повтор шёл вечно.
            anchor = _repeat_anchor.get(key, _pending[key])
            repeat_window = ((row.get("reminder_repeat_hours") or 2) * 60 + (row.get("reminder_repeat_minutes") or 0)) * 60
            if (now_utc - anchor).total_seconds() >= repeat_window:
                _pending.pop(key, None)
                _repeat_anchor.pop(key, None)
            elif (now_utc - _pending[key]).total_seconds() >= 300:
                should_send = True

        if not should_send:
            continue

        _ct = cycle_dose_for_day(row.get("dose_cycle"), row.get("anchor_date"), now_local.date())
        dosage = f"{_ct} {row.get('unit_dose_label') or 'мг'}" if _ct else (row["rule_dosage"] or row["med_dosage"])
        dep_suffix = f" <i>({escape_html(row['dependent_name'])})</i>" if row["dependent_name"] else ""
        buttons = [[
            {"text": "✅ Принял",    "callback_data": f"taken:{row['medication_id']}:{row['reminder_time']}"},
            {"text": "❌ Пропустить", "callback_data": f"skipped:{row['medication_id']}:{row['reminder_time']}"},
        ]]
        text = (
            f"💊 Время принять препарат!\n\n"
            f"<b>{escape_html(row['name'])}</b>{dep_suffix} — {escape_html(dosage)}\n"
            f"🍽 Принимать {_MEAL_LABELS.get(row['meal_relation'], row['meal_relation'])}"
        )
        try:
            track_key = f"{row['medication_id']}:{row['reminder_time']}:{now_local.date().isoformat()}"
            await _arq_pool.enqueue_job(
                'send_reminder',
                chat_id=row["telegram_id"],
                text=text,
                buttons=buttons,
                track_key=track_key,
            )
            _pending[key] = now_utc
            _repeat_anchor.setdefault(key, now_utc)  # фикс окна повтора: anchor = первая отправка
            sent += 1
        except Exception as e:
            logger.error("Ошибка постановки в очередь: %s", e)
            errors += 1

    if sent or errors:
        logger.info("scheduler: sent=%d errors=%d active_rules=%d", sent, errors, len(schedules))

    await _send_daily_plans(app, schedules)
    # G2: строгий режим — авто-пропуск просроченных приёмов со штрафом сердечком.
    await _apply_strict_autoskip(schedules)
    # Ф15: TG-дайджест откликов на пожелания (1/день, тогл wishes_tg_notify).
    await _send_wish_digests()
    # AX6: сохранить обновлённое состояние (отправленные слоты/планы) в Redis.
    await asyncio.to_thread(_save_state)


def _prune_daily_plan_sent():
    """Удаляет из _daily_plan_sent записи старше 2 дней (локальная дата ±1 от UTC)."""
    cutoff = (datetime.now(pytz.utc).date() - timedelta(days=2)).isoformat()
    stale = {k for k in _daily_plan_sent if k[1] < cutoff}
    _daily_plan_sent.difference_update(stale)


async def _send_daily_plans(app, schedules):
    """Отправляет утренний план дня пользователям, у которых наступило время plan_time.

    Использует строки из общего прохода планировщика (schedules), фильтруя по
    daily_plan_enabled — без отдельного запроса к БД.
    """
    _prune_daily_plan_sent()
    rows = [r for r in schedules if r["daily_plan_enabled"]]
    if not rows:
        return

    users: dict = {}
    for row in rows:
        tid = row["telegram_id"]
        if tid not in users:
            try:
                tz = pytz.timezone(row["timezone"] or "UTC")
            except Exception:
                tz = pytz.utc
            now_local = datetime.now(tz)
            users[tid] = {
                "tz": tz,
                "now_local": now_local,
                "plan_time": row["daily_plan_time"] or "08:00",
                "meds": {},
            }
        mid = row["medication_id"]
        if not _rule_fires_today(row, users[tid]["now_local"].date()):
            continue
        if mid not in users[tid]["meds"]:
            users[tid]["meds"][mid] = {
                "name": row["name"], "meal_relation": row["meal_relation"],
                "dep_name": row["dependent_name"], "times": [],
            }
        _ct = cycle_dose_for_day(row.get("dose_cycle"), row.get("anchor_date"),
                                 users[tid]["now_local"].date())
        dosage = f"{_ct} {row.get('unit_dose_label') or 'мг'}" if _ct else (row["rule_dosage"] or row["med_dosage"])
        users[tid]["meds"][mid]["times"].append((row["reminder_time"], dosage))

    for tid, data in users.items():
        now_local = data["now_local"]
        if now_local.strftime("%H:%M") != data["plan_time"]:
            continue
        plan_key = (tid, now_local.date().isoformat())
        if plan_key in _daily_plan_sent:
            continue
        if not data["meds"]:
            continue

        lines = ["🌅 <b>Доброе утро!</b>\n", "📋 <b>Сегодня нужно принять:</b>\n"]
        for med in data["meds"].values():
            meal = _MEAL_LABELS.get(med["meal_relation"], "")
            meal_str = f" — {meal}" if meal and med["meal_relation"] != "any" else ""
            dep_label = f" <i>({escape_html(med['dep_name'])})</i>" if med["dep_name"] else ""
            lines.append(f"💊 <b>{escape_html(med['name'])}</b>{dep_label}")
            for reminder_time, dosage in sorted(med["times"]):
                lines.append(f"   ⏰ {reminder_time} — {escape_html(dosage)}{meal_str}")
        lines.append("\nНе забудь взять препараты с собой! 🎒")
        lines.append("Продуктивного дня! 🚀")

        try:
            await _arq_pool.enqueue_job(
                'send_reminder',
                chat_id=tid,
                text="\n".join(lines),
            )
            _daily_plan_sent.add(plan_key)
            logger.info("План дня поставлен в очередь: %s", tid)
        except Exception as e:
            logger.error("Ошибка постановки плана дня в очередь: %s", e)


def _prune_wish_digest_sent():
    """Удаляет из _wish_digest_sent записи старше 2 дней."""
    cutoff = (datetime.now(pytz.utc).date() - timedelta(days=2)).isoformat()
    stale = {k for k in _wish_digest_sent if k[1] < cutoff}
    _wish_digest_sent.difference_update(stale)


async def _send_wish_digests():
    """Ф15: раз в день (в WISH_DIGEST_TIME local) шлёт сводку откликов на пожелания.

    Только юзерам с тоглом wishes_tg_notify=1, у кого есть нерассланные реакции.
    Дедуп: in-memory _wish_digest_sent (на день) + БД-метка sender_digest_at.
    """
    if _arq_pool is None:
        return
    _prune_wish_digest_sent()
    try:
        candidates = await asyncio.to_thread(get_wish_digest_candidates)
    except Exception as e:
        logger.error("Ошибка выборки дайджеста пожеланий: %s", e)
        return
    for c in candidates:
        try:
            tz = pytz.timezone(c["timezone"] or "UTC")
        except Exception:
            tz = pytz.utc
        now_local = datetime.now(tz)
        if now_local.strftime("%H:%M") != WISH_DIGEST_TIME:
            continue
        key = (c["telegram_id"], now_local.date().isoformat())
        if key in _wish_digest_sent:
            continue
        helped, supported = c["helped"] or 0, c["supported"] or 0
        total = helped + supported
        if total <= 0:
            continue
        parts = []
        if helped:
            parts.append(f"👍 {helped}")
        if supported:
            parts.append(f"❤️ {supported}")
        text = (
            "💛 <b>Спасибо за вашу поддержку!</b>\n\n"
            f"Сегодня ваши тёплые слова отметили {total} раз ({' · '.join(parts)}).\n"
            "Кому-то стало чуточку легче благодаря вам."
        )
        try:
            await _arq_pool.enqueue_job('send_reminder', chat_id=c["telegram_id"], text=text)
            await asyncio.to_thread(mark_wish_reactions_digested, c["user_id"])
            _wish_digest_sent.add(key)
            logger.info("Дайджест пожеланий поставлен в очередь: %s", c["telegram_id"])
        except Exception as e:
            logger.error("Ошибка постановки дайджеста пожеланий: %s", e)


async def _apply_strict_autoskip(schedules):
    """G2: в строгом режиме помечает просроченные приёмы как пропущенные (−1 ❤️).

    Просрочка = прошло strict_mode_hours часов после reminder_time, а отметки за
    сегодня (taken/skipped) нет. Идемпотентно: запись skipped → следующий проход
    видит её и не повторяет.
    """
    strict_rows = [r for r in schedules if r.get("strict_mode")]
    if not strict_rows:
        return

    by_user: dict = {}
    for r in strict_rows:
        by_user.setdefault(r["telegram_id"], []).append(r)

    for tid, rows in by_user.items():
        first = rows[0]
        try:
            tz = pytz.timezone(first["timezone"] or "UTC")
        except Exception:
            tz = pytz.utc
        now_local = datetime.now(tz)
        today = now_local.date()
        now_min = now_local.hour * 60 + now_local.minute
        hours = (first["strict_mode_hours"] or 2) + (first.get("strict_mode_minutes") or 0) / 60
        threshold = int(hours * 60)
        start_utc, end_utc = local_day_bounds_utc(tz, now_local)
        statuses = await asyncio.to_thread(get_today_intake_statuses, tid, start_utc, end_utc)
        # F10-C: опекуны владельца (F7) считаются один раз на юзера; viewer'ы (F8) — по dep_id.
        caregiver_tids = await asyncio.to_thread(get_caregiver_tids_for_dependent, first["user_id"])
        owner_label = f"@{first['owner_username']}" if first.get("owner_username") else "вашего близкого"
        viewer_cache: dict = {}

        for r in rows:
            if not _rule_fires_today(r, today):
                continue
            try:
                rh, rm = r["reminder_time"].split(":")
                reminder_min = int(rh) * 60 + int(rm)
            except (ValueError, AttributeError):
                continue
            if now_min < reminder_min + threshold:
                continue  # ещё не просрочено
            key = (r["medication_id"], r["reminder_time"])
            if key in statuses:
                continue  # уже отмечено

            await asyncio.to_thread(
                log_intake, r["medication_id"], r["reminder_time"], "skipped", start_utc, end_utc
            )
            await asyncio.to_thread(apply_intake_hearts, r["user_id"], "skipped", None)
            statuses[key] = "skipped"
            # Гасим напоминания по этому слоту на сегодня (как и ручная отметка).
            _marked_today.add((tid, r["medication_id"], r["reminder_time"], today.isoformat()))
            _pending.pop((tid, r["medication_id"], r["reminder_time"]), None)
            _repeat_anchor.pop((tid, r["medication_id"], r["reminder_time"]), None)
            dep = f" ({escape_html(r['dependent_name'])})" if r["dependent_name"] else ""
            try:
                await _arq_pool.enqueue_job(
                    'send_reminder',
                    chat_id=tid,
                    text=(f"⏰ <b>{escape_html(r['name'])}</b>{dep} автоматически отмечен "
                          f"пропущенным (режим «Без пропусков», прошло {hours} ч). −1 ❤️"),
                )
            except Exception as e:
                logger.error("strict autoskip enqueue error: %s", e)
            # F10-C: пуш помощникам о пропуске приёма подопечного.
            await _notify_caregivers_on_miss(r, caregiver_tids, owner_label, viewer_cache, hours)


async def _notify_caregivers_on_miss(r, caregiver_tids, owner_label, viewer_cache, hours):
    """Пуш помощникам, что приём подопечного пропущен (F7 опекуну / F8 наблюдателям)."""
    med = escape_html(r["name"])
    if r.get("dependent_id"):
        # F8: локальный близкий → активные наблюдатели
        dep_id = r["dependent_id"]
        if dep_id not in viewer_cache:
            viewer_cache[dep_id] = await asyncio.to_thread(get_dep_share_viewer_tids, dep_id)
        targets = viewer_cache[dep_id]
        who = escape_html(r["dependent_name"]) if r.get("dependent_name") else "близкого"
        text = (f"⚠️ Пропущен приём <b>{med}</b> у «{who}» "
                f"(прошло {hours} ч без отметки).")
    else:
        # F7: собственное лекарство подопечного-аккаунта → его опекуны
        targets = caregiver_tids
        text = (f"⚠️ Пропущен приём <b>{med}</b> у {owner_label} "
                f"(прошло {hours} ч без отметки).")
    for target_tid in targets:
        try:
            await _arq_pool.enqueue_job('send_reminder', chat_id=target_tid, text=text)
        except Exception as e:
            logger.error("miss-notify enqueue error: %s", e)


async def handle_intake_callback(update, context):
    """Обрабатывает нажатие кнопок ✅ Принял / ❌ Пропустить в напоминании.

    Парсит callback_data формата «status:medication_id:HH:MM»,
    записывает приём в intake_log и убирает ключ из _pending.
    """
    query = update.callback_query
    await query.answer()

    try:
        parts = query.data.split(":")
        status = parts[0]
        medication_id = int(parts[1])
        scheduled_time = ":".join(parts[2:])
    except (ValueError, IndexError):
        logger.error("Некорректный callback: %s", query.data)
        return

    try:
        telegram_id = update.effective_user.id
        # S1: callback_data контролируется клиентом — проверяем, что лекарство
        # принадлежит нажавшему, иначе можно писать в чужой intake_log / запас.
        # B3: синхронные DB-вызовы — через to_thread, чтобы не блокировать loop.
        user_id = await asyncio.to_thread(get_or_create_user, telegram_id)
        if not await asyncio.to_thread(get_medication_by_id, medication_id, user_id):
            logger.warning(
                "Отклонён callback на чужое/несуществующее лекарство: med=%s от tg=%s",
                medication_id, telegram_id
            )
            return
        user_tz = await asyncio.to_thread(get_tz_for_user, telegram_id)
        start_utc, end_utc = local_day_bounds_utc(user_tz)
        old_status = await asyncio.to_thread(
            log_intake, medication_id, scheduled_time, status, start_utc, end_utc
        )
        # G1: сердечки за приём/пропуск (идемпотентно через old_status).
        await asyncio.to_thread(apply_intake_hearts, user_id, status, old_status)
    except Exception as e:
        logger.error("Ошибка записи приёма: %s", e)
        await query.edit_message_text("⚠️ Не удалось записать приём. Попробуй ещё раз.")
        return

    key = (telegram_id, medication_id, scheduled_time)
    _pending.pop(key, None)
    _repeat_anchor.pop(key, None)
    # Помечаем слот отмеченным на сегодня — чтобы догон/повтор не пере-взвели
    # напоминание в окне CATCHUP_MIN после отметки.
    _marked_today.add((telegram_id, medication_id, scheduled_time,
                       datetime.now(user_tz).date().isoformat()))

    if status == "taken":
        await query.edit_message_text("✅ Отлично! Приём записан.")
    else:
        await query.edit_message_text("❌ Пропуск записан.")

    # F5: автосписание запаса + предупреждение при пересечении порога
    try:
        await _update_stock_on_intake(
            query.message.reply_text, medication_id, status, old_status, telegram_id, user_tz
        )
    except Exception as e:
        logger.error("Ошибка обновления запаса: %s", e)


async def _update_stock_on_intake(reply_fn, medication_id, new_status, old_status, telegram_id, user_tz):
    """Списывает/возвращает запас при отметке приёма; предупреждает при переходе ниже порога.

    reply_fn — корутина для отправки сообщения (message.reply_text или bot.send_message partial).
    """
    info = await asyncio.to_thread(apply_intake_stock, medication_id, new_status, old_status)
    if not info or not info["changed"] or new_status != "taken":
        return
    rules = await asyncio.to_thread(get_schedules_by_medication, medication_id)
    today = datetime.now(user_tz).date()
    qty, units, thr = info["stock_qty"], info["units_per_dose"], info["low_stock_days"]
    after = days_of_stock_left(rules, qty, units, today)
    before = days_of_stock_left(rules, qty + units, units, today)
    # Предупреждаем один раз — на самом пересечении порога (before выше, after на/ниже).
    if after is not None and after <= thr and (before is None or before > thr):
        user_id = await asyncio.to_thread(get_or_create_user, telegram_id)
        med = await asyncio.to_thread(get_medication_by_id, medication_id, user_id)
        name = escape_html(med["name"]) if med else "Препарат"
        await reply_fn(
            f"⚠️ <b>{name}</b> скоро закончится: осталось примерно на {after} дн. ({qty:g} шт.).\n"
            f"Не забудь пополнить запас 📦",
            parse_mode="HTML"
        )
