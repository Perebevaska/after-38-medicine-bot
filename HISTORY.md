# История исправлений

Архив всех закрытых багов и улучшений по хронологии разработки.

---

## Аудит PostgreSQL-версии (2026-06-02)

Все пункты закрыты, 217 тестов зелёные.

| # | Файл | Проблема | Статус |
|---|------|----------|--------|
| S1 | `scheduler.py` | IDOR в `handle_intake_callback`: `med_id` не проверялся на владельца → чужой intake_log / запас | ✅ |
| S2 | `api/routers/medications.py` | IDOR: `dependent_id` из тела не проверялся на принадлежность user_id | ✅ |
| B1 | `broadcast.py` | Рассылка читала мёртвый SQLite вместо PostgreSQL | ✅ |
| S3 | `database.py` | `ON CONFLICT DO UPDATE SET username = EXCLUDED.username` затирал username при API-запросах без username | ✅ |
| B2 | `database.py` | `datetime.utcnow()` устарел в Python 3.14, naive datetime | ✅ |
| B3 | `scheduler.py` | Синхронный psycopg в event loop каждую минуту | ✅ |
| B4 | `schedule_utils.py` | `interval`-правило без `interval_days` → TypeError/ZeroDivisionError | ✅ |
| S4 | `api/main.py` | Rate limiter: пустые ключи не чистились; нет поддержки X-Forwarded-For | ✅ |
| S5 | `api/main.py` | CORS fail-open: дефолт `*` без warning | ✅ |
| B5 | `api/routers/medications.py` | Нет серверной валидации полей schedule_rules | ✅ |
| O1 | репо | Артефакты `med_bot.db`, `db_errors.log`, `bot_run.log` в рабочей копии | ✅ |
| O2 | `.claude/CLAUDE.md` | Устаревший дубль SQLite-архитектуры | ✅ |
| O3 | `handlers/meds.py` | Монолит 108 КБ — разбит на meds_common / meds_add / meds_edit | ✅ |
| O4 | `api/routers/*` | `get_or_create_user` повторялся в ~17 эндпоинтах | ✅ |
| O5 | handlers, scheduler | `parse_mode="Markdown"` + хрупкий escape_md → мигрировано на HTML | ✅ |
| O6 | зависимости | `pip-audit` + пины версий → привязан к D3 в roadmap | 🔲 |

---

## SQLite-фаза (до миграции на PostgreSQL)

42 закрытых бага + UX-пакет + фичи F1–F6.

| # | Файл | Проблема |
|---|------|----------|
| 1 | `scheduler.py` | Scheduler использовал серверный TZ вместо TZ каждого пользователя |
| 2 | `scheduler.py` | Режим "повтор каждые 5 минут" не был реализован |
| 3 | `database.py` | `get_today_stats` / `get_history_detailed` использовали `date('now')` (UTC) вместо TZ пользователя |
| 4 | `handlers/meds.py`, `handlers/timezone.py` | Многие DB-функции без `@handle_db_errors` |
| 5 | `handlers/timezone.py` | Нет обработки таймаута geopy |
| 6 | `handlers/meds.py` | Лишние DB-запросы в цепочке edit (`get_or_create_user` × 5) |
| 7 | `scheduler.py` | `handle_intake_callback` без try/except вокруг `log_intake` |
| 8 | `handlers/meds.py` | TIMES/MEAL состояния без паттернов — ловили любой callback |
| 9 | `database.py` | `log_intake` делал INSERT при каждом нажатии — теперь upsert |
| 10 | `scheduler.py` | Ключи удалённых лекарств висели в `_pending` |
| 11 | `handlers/meds.py` | При смене количества приёмов показывались старые времена |
| 12 | `scheduler.py` | `handle_intake_callback` брал `parts[2]` — обрезал минуты |
| 13 | `handlers/meds.py` | `_check_time` не нормализовал формат |
| 14 | `handlers/timezone.py` | `handle_menu_callback` не был обёрнут в `@handle_db_errors` |
| 15 | `handlers/meds.py` | `keep_edit_schedule` не показывал `🔢 X раз в день` |
| 16 | `handlers/meds.py` | Мёртвый код `add_freq_time` / `edit_freq_time` |
| 17 | `handlers/timezone.py` | `handle_menu_callback` рендерил настройки хардкодом |
| 18 | `handlers/timezone.py` | После установки TZ пишет "Используй /meds" |
| 19 | `scheduler.py` | `meal_labels` dict пересоздавался на каждой итерации |
| 20 | `handlers/stats.py` | Нет защиты от лимита 4096 символов |
| 21 | `handlers/meds.py`, `handlers/settings.py` | `_parse_time` дублирована — перенесена в `utils.py` |
| 22 | `handlers/timezone.py` | `TimezoneFinder()` создавался при каждом запросе |
| 23 | `utils.py` | `handle_db_errors` без `functools.wraps` |
| 24 | `handlers/meds.py` | Нет предупреждения для дней 29–31 в monthly расписании |
| 25 | `handlers/settings.py` | Нет описаний настроек в `/settings` |
| 26 | `broadcast.py` | Отдельный скрипт рассылки |
| 27 | `handlers/admin.py`, `database.py` | Кнопка "🔧 Админ панель" в `/settings` |
| 29 | `handlers/meds.py` | Нельзя отредактировать лекарство с разными дозировками |
| 30 | `handlers/meds.py` | В multi-dosage edit: устаревшее сообщение "нельзя изменить расписание", кнопка питания не там |
| 31 | `handlers/stats.py`, `handlers/export.py` | Экспорт истории и плана в PDF |
| 32 | `database.py` | Таблица `schedules` не удалялась |
| 33 | `handlers/meds.py`, `utils.py`, `scheduler.py` | Аудит валидации: `escape_md()`, лимиты NAME/DOSAGE_MAX_LEN |
| 34 | `database.py`, `handlers/meds.py`, `handlers/caregiver.py`, `scheduler.py`, `constants.py` | **Caregiver-режим**: таблица `dependents`, `medications.dependent_id`, `/settings` кнопка с вкл/выкл, шаг «Для кого?» в add-флоу, лимит 10 лекарств на каждого подопечного, напоминания с «(для Маши)», `MAX_DEPENDENTS=2` |
| 35 | `handlers/timezone.py` | После установки TZ новому пользователю непонятно что делать |
| 36 | `handlers/stats.py` | В `/stats` нет плана лекарств на неделю |
| 37 | `handlers/stats.py`, `utils.py` | HTML без экранирования: имена/дозировки с `<`, `>`, `&` ломали статистику и план. Добавлен `escape_html()` |
| 38 | `database.py`, `scheduler.py`, `handlers/timezone.py`, `utils.py` | «Сегодня» считалось по UTC `date('now')`, а не по TZ пользователя → рассинхрон статусов и upsert у границы суток. Введён `local_day_bounds_utc()` |
| 39 | `handlers/meds.py` | Multi-dosage edit показывал «Лекарство добавлено» вместо «обновлено» |
| 40 | `database.py` | Нет `PRAGMA busy_timeout/WAL/foreign_keys` → риск `database is locked` |
| 41 | `database.py` | Нет индексов → full-scan в планировщике и статистике. Добавлены 5 индексов |
| 42 | `database.py` | `delete_dependent` не занулял `dependent_id` → нарушение FK после включения `foreign_keys=ON` |
| 43 | `scheduler.py` | Утечки памяти: `_pending` (режим once) и `_daily_plan_sent` не очищались. Добавлен TTL-prune |
| 44 | `database.py`, `scheduler.py` | Планировщик делал 2 full-scan/мин. Объединено в `get_active_schedule_rows()` — один проход |
| 45 | `database.py`, `handlers/settings.py` | `fetch_settings_data` открывала 5 соединений на рендер. Сведено к одному `get_user_settings_row()` |
| 46 | `database.py`, `handlers/meds.py` | Список лекарств делал N+1 (`get_schedules_by_medication` в цикле). Заменено на `get_rules_grouped_for_user()` |
| 47 | `handlers/settings.py`, `handlers/timezone.py`, `bot.py` | Из под-экранов `/settings` нельзя вернуться в настройки. Добавлены «◀️ Назад» |
| 48 | `constants.py`, `handlers/settings.py`, `handlers/timezone.py` | Дублирование текста «О проекте» в двух местах. Вынесено в `ABOUT_TEXT` |
| 49 | `database.py` | `db_logger` без `propagate=False` — ошибки БД дублировались в консоль root-логгера |
| 50 | `database.py` | `migrate()` повторно создавал таблицу `dependents` (уже в `init_db`). Удалён избыточный `CREATE TABLE` |
| 51 | `tests/`, `pytest.ini`, `requirements-dev.txt` | Не было тестов. Добавлены 58 unit-тестов на чистые функции (pytest) |
| 52 | `handlers/meds.py` | Дубль входа в add-флоу (`add_start` ≈ `handle_add_med_callback`). Объединено в `_begin_add_flow()` |
| 53 | `handlers/meds.py`, `tests/test_handlers.py` | Success-сообщения сведены в `_med_saved_text()`, валидация диапазонов — в `_parse_int_range()`. Под защитой 24 характеризационных тестов |
| 54 | `handlers/timezone.py`, `stats.py`, `settings.py`, `meds.py`, `bot.py` | Непоследовательные «Назад»: сделана единая точка входа `/menu` + навигация edit-in-place с «◀️ В меню» (`menu:main`) на всех экранах |
| 55 | `handlers/timezone.py`, `bot.py` | `telegram.error.TimedOut` ронял старт. Таймауты 20с + try/except в `post_init` |
| 56 | `schedule_utils.py`, `database.py`, `handlers/stock.py`, `scheduler.py`, `handlers/meds.py`, `bot.py`, `constants.py` | **F5 реализована** — учёт запаса таблеток. Колонки `stock_qty/units_per_dose/low_stock_days`; экран «📦 Запас»; автосписание при `taken`; прогноз `days_of_stock_left`; событийное предупреждение при пересечении порога. Тесты: 18+9+5 |
| 57 | `database.py`, `handlers/settings.py` | **Баг**: смена пресета времени не прокидывалась в существующие напоминания. `set_user_time_preset` теперь мигрирует правила `reminder_time` старое→новое. Тесты `test_preset_migration` |
| Q1b | `handlers/meds.py`, `tests/test_conv_structure.py` | Слияние идентичных наборов состояний add/edit в `_schedule_input_states()`. Под защитой снапшот-теста структуры диалогов |
| UX | `handlers/meds.py`, `handlers/settings.py` | Пакет UX: подсказка «время слотов меняется в Настройках»; кнопка «📦 Указать запас» на сообщении «Лекарство добавлено/обновлено»; список лекарств — кнопки «Добавить»/«В меню» слиты в последнюю карточку |
| F1 | `handlers/export.py`, `database.py`, `schedule_utils.py`, `handlers/stats.py` | **F1 реализована** — «Отчёт для врача»: PDF-календарь приверженности за 30 дней в альбомной ориентации. Дни залиты по соблюдению (🟩≥90/🟨≥50/🟥<50/серый), внутри — лекарства с кружком. Отдельная страница на пациента и каждого подопечного |
| F2 | `streak.py`, `database.py`, `handlers/stats.py`, `handlers/timezone.py` | **F2 реализована** — серия идеальных дней (streak). Чистая логика — отдельный модуль `streak.py`: `compute_streak`, `streaks_by_subject`, `streak_window`. Серия **отдельно** для владельца и каждого подопечного |
| F3 | `schedule_utils.py`, `database.py`, `handlers/stats.py`, `handlers/export.py` | **F3 реализована** — соблюдение режима (adherence) за 30 дней. Экран `stats:adherence`: по каждому активному лекарству `taken / положено` с индикатором 🟢≥80/🟡≥50/🔴 + общий итог |
| F4 | `database.py`, `handlers/meds.py`, `bot.py` | **F4 реализована** — пауза лекарства. Колонка `medications.paused` (0/1). На паузе исключается из напоминаний, плана, adherence. Кнопка «⏸ Пауза»/«▶️ Возобновить» в карточке |
| F6 | `handlers/timezone.py`, `scheduler.py` | **F6 реализована** — «✅ Принять всё». Кнопка появляется если есть непринятый приём, исчезает когда всё отмечено. Рефакторинг: `_render_today_screen` извлечена в отдельную функцию |
