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
                      get_caregiver_tids_for_dependent, get_dep_share_viewer_tids)
from utils import escape_html, get_tz_for_user, local_day_bounds_utc
# _rule_fires_today живёт в schedule_utils (чистая логика, без telegram/db);
# реэкспорт для обратной совместимости: stats/export/timezone импортируют его отсюда.
from schedule_utils import _rule_fires_today, days_of_stock_left

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
# (telegram_id, date_iso) — пользователи, которым план дня уже отправлен сегодня
_daily_plan_sent: set = set()

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
            for tid, d in data.get("daily_plan_sent", []):
                _daily_plan_sent.add((tid, d))
            logger.info("scheduler: состояние восстановлено из Redis (pending=%d)", len(_pending))
    except Exception as e:
        logger.warning("scheduler: не удалось загрузить состояние из Redis: %s", e)


def _save_state():
    """Сохраняет состояние планировщика в Redis (TTL 2ч, как окно _pending)."""
    try:
        data = {
            "pending": [[k[0], k[1], k[2], ts.isoformat()] for k, ts in _pending.items()],
            "daily_plan_sent": [[k[0], k[1]] for k in _daily_plan_sent],
        }
        _redis_sync().set(_STATE_KEY, json.dumps(data), ex=7200)
    except Exception as e:
        logger.warning("scheduler: не удалось сохранить состояние в Redis: %s", e)


def clear_pending_for_medication(medication_id: int):
    """Удаляет все pending-записи для указанного лекарства (вызывается при деактивации)."""
    for key in [k for k in _pending if k[1] == medication_id]:
        del _pending[key]


def _prune_pending(now_utc: datetime):
    """Удаляет из _pending записи старше 12 часов (макс. окно repeat)."""
    cutoff = now_utc - timedelta(seconds=43200)
    for key in [k for k, ts in _pending.items() if ts < cutoff]:
        del _pending[key]


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
            elapsed = (now_utc - _pending[key]).total_seconds()
            repeat_window = ((row.get("reminder_repeat_hours") or 2) * 60 + (row.get("reminder_repeat_minutes") or 0)) * 60
            if 300 <= elapsed < repeat_window:
                should_send = True
            elif elapsed >= repeat_window:
                _pending.pop(key, None)

        if not should_send:
            continue

        dosage = row["rule_dosage"] or row["med_dosage"]
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
            await _arq_pool.enqueue_job(
                'send_reminder',
                chat_id=row["telegram_id"],
                text=text,
                buttons=buttons,
            )
            _pending[key] = now_utc
            sent += 1
        except Exception as e:
            logger.error("Ошибка постановки в очередь: %s", e)
            errors += 1

    if sent or errors:
        logger.info("scheduler: sent=%d errors=%d active_rules=%d", sent, errors, len(schedules))

    await _send_daily_plans(app, schedules)
    # G2: строгий режим — авто-пропуск просроченных приёмов со штрафом сердечком.
    await _apply_strict_autoskip(schedules)
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
        dosage = row["rule_dosage"] or row["med_dosage"]
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
