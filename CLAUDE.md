# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About
Telegram бот для напоминаний о приёме лекарств с поддержкой гибкого расписания, статистики, экспорта в PDF и определения часовых поясов.

## Stack
- **Language**: Python 3.14
- **Framework**: python-telegram-bot 22.7 (async API)
- **Scheduler**: APScheduler 3.11.2 (задача каждую минуту)
- **Database**: SQLite (`med_bot.db`)
- **Timezone**: pytz, timezonefinder, geopy (Nominatim кэшируется как `_geolocator` на уровне модуля)
- **PDF**: fpdf2 + DejaVuSans TTF (`/usr/share/fonts/truetype/dejavu/`)

## Architecture

### Структура
```
med-bot/
├── bot.py              # точка входа — только main() + регистрация handlers
├── database.py         # SQLite CRUD через get_connection()
├── scheduler.py        # send_reminders() каждую минуту
├── schedule_utils.py   # чистая логика «положенных приёмов» (_rule_fires_today + due/count хелперы)
├── constants.py        # States, MEAL_LABELS, MONTHS_GEN, MAX_MEDICATIONS_PER_USER
├── utils.py            # handle_db_errors, get_tz_for_user, cancel, escape_md, parse_time
├── broadcast.py        # standalone скрипт рассылки (python3 broadcast.py)
└── handlers/
    ├── meds.py         # add/edit/delete medications
    ├── stats.py        # stats_week, show_week_plan
    ├── export.py       # PDF экспорт плана и истории (asyncio.to_thread)
    ├── settings.py     # settings, about, reminder_mode toggle, daily plan
    ├── admin.py        # админ-панель (только ADMIN_ID)
    ├── caregiver.py    # caregiver-режим: подопечные (dependents), вкл/выкл
    ├── stock.py        # F5: экран «📦 Запас» — остаток/расход/порог/прогноз
    └── timezone.py     # start, timezone setup, main menu, Лекарства на сегодня
```

### Схема БД
5 активных таблиц:
- `users` (telegram_id, username, timezone, reminder_mode, time_morning, time_lunch, time_evening, time_night, daily_plan_enabled, daily_plan_time, **caregiver_enabled**)
- `dependents` (user_id FK, name) — подопечные caregiver-режима
- `medications` (user_id FK, name, dosage, meal_relation, times_per_day, active, **dependent_id** FK NULL, **stock_qty** REAL NULL=трекинг выкл, **units_per_dose** REAL, **low_stock_days** INTEGER) — F5: учёт запаса
- `schedule_rules` (medication_id FK, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage) — `dosage NULL` = берётся из `medications.dosage`
- `intake_log` (medication_id FK, scheduled_time, taken_at, status: taken/skipped/pending)

Таблица `schedules` удалена в `migrate()` через `DROP TABLE IF EXISTS schedules`.

**Соединение БД** (`get_connection`): `PRAGMA journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON` — параллельные чтение/запись и контроль FK.
**Индексы** (создаются в `init_db`): `medications(user_id, active)`, `medications(dependent_id)`, `schedule_rules(medication_id)`, `intake_log(medication_id, scheduled_time)`, `intake_log(taken_at)`.
**Внимание про FK**: при удалении подопечного `delete_dependent` обязан занулять `medications.dependent_id` — иначе `DELETE` нарушит включённый `foreign_keys`.

### schedule_rules — типы frequency
| frequency | поля | описание |
|-----------|------|----------|
| `daily` | — | каждый день |
| `interval` | `interval_days`, `anchor_date` | каждые N дней от anchor_date |
| `weekdays` | `weekdays` | по дням недели, '1,3,5' (пн=1, вс=7) |
| `monthly` | `month_day` | раз в месяц, N-го числа |

### Поток данных
1. Пользователь добавляет лекарство → `handlers/meds.py` → `database.add_medication()` + `database.add_schedule_rule()`
2. APScheduler каждую минуту → `scheduler.send_reminders()` → проверяет `_rule_fires_today()` → InlineKeyboard с ✅/❌
3. Нажатие кнопки → `scheduler.handle_intake_callback()` → `database.log_intake()` (upsert)
4. Кнопка PDF → `handlers/export.py` → `asyncio.to_thread(_build_pdf, ...)` → `reply_document`

### Флоу добавления лекарства
```
Название → Дозировка
  ├── (текст) → Когда принимать (multi-select) → Как с пищей → Тип расписания → сохранить
  └── 📊 Разная дозировка
        → Дозировка А → Дозировка Б
        → Слоты А → Слоты Б
        → Как с пищей (один раз для обеих)
        → Расписание А (daily/interval/weekdays/monthly)
        → Расписание Б (+ выбор даты начала для interval)
        → сохранить одно лекарство с rules: А dosage=NULL, Б dosage=dosage_b
```

Время выбирается через multi-select по пресетам (Утро/Обед/Вечер/Ночь). Пресеты настраиваются в /settings.
Каждое выбранное время сохраняется отдельной строкой в `schedule_rules`.
При разных дозировках правила Б хранят `dosage` явно; правила А — `dosage=NULL` (наследуют из `medications`).

### Флоу редактирования лекарства
```
Название → Дозировка А → [Дозировка Б] → Приём с пищей → Тип расписания:
  Оставить расписание → сохранить
  Каждый день / Через N / По дням / Раз в месяц →
    Когда принимать (multi-select) → Как с пищей →
      Каждый день   → сохранить
      Через N дней  → N дней → сохранить
      По дням недели → Дни → сохранить
      Раз в месяц   → Число → сохранить
```

### Handler Pattern
```python
app.add_handler(settings.get_handler())
for h in stats.get_handlers():
    app.add_handler(h)
for h in export.get_handlers():
    app.add_handler(h)
app.add_handler(meds.get_add_handler(cancel_handler))
app.add_handler(meds.get_edit_handler(cancel_handler))
app.add_handler(CallbackQueryHandler(tz_handler.handle_menu_callback, pattern="^menu:"))
```

### utils.py
- `handle_db_errors` — декоратор: ловит `DatabaseError`, отвечает пользователю
- `get_tz_for_user(telegram_id)` → `pytz.timezone` объект
- `cancel` — handler для `/cancel`, завершает любой ConversationHandler
- `escape_md(text)` — экранирует спецсимволы Telegram Markdown v1 (`*`, `_`, `` ` ``, `[`)
- `escape_html(text)` — экранирует `&`, `<`, `>` для `parse_mode="HTML"` (stats.py, план)
- `local_day_bounds_utc(user_tz, now_local=None)` → `(start_utc, end_utc)` — границы локальных суток пользователя как UTC-строки; для запросов «сегодня» по `intake_log`
- `parse_time(time_str)` → `ЧЧ:ММ` с ведущим нулём; поднимает `ValueError` при ошибке
- `NAME_MAX_LEN = 50`, `DOSAGE_MAX_LEN = 30` — лимиты длины пользовательского ввода

## Commands

```bash
# Разработка
source venv/bin/activate
python3 bot.py

# Установка зависимостей
pip install -r requirements.txt

# Рассылка (standalone)
python3 broadcast.py

# Миграция БД вызывается автоматически в bot.py при старте

# Тесты (чистые функции, без БД/Telegram)
pip install -r requirements-dev.txt
pytest -q
```

## Тесты
- `tests/test_pure.py` — unit-тесты чистых функций: `parse_time`, `escape_md`, `escape_html`, `local_day_bounds_utc`, `_rule_fires_today`, `_compute_next_fire`, `_next_fire_label`, `_freq_label`, `_format_schedule_rule`, `_monthday_warning`, `_current_schedule_summary`
- `tests/test_handlers.py` — характеризационные тесты save-хендлеров (add/edit × daily/interval/weekdays/monthly): фиксируют текст «✅ Лекарство добавлено/обновлено» и валидацию диапазонов; БД мокается в namespace `handlers.meds`, Telegram заменён фейками
- `tests/test_menu.py` — навигация меню (`menu:main`/`about`/`stats`) и наличие кнопок «◀️ В меню»
- `tests/test_conv_structure.py` — снапшот структуры `get_add_handler`/`get_edit_handler` (состояния, callback'и, паттерны); защищает дедуп общих состояний (`_schedule_input_states`)
- `tests/test_schedule_utils.py` — «положенные приёмы» за день/период (`due_intakes_on`, `iter_due_by_day`, `count_due_*`) + прогноз запаса `days_of_stock_left` (F5) + реэкспорт `_rule_fires_today`
- `tests/test_stock_db.py` — DB-слой запаса F5 (set/add/units/threshold, `apply_intake_stock` идемпотентно, `log_intake` возвращает старый статус) на временной БД
- `tests/test_stock_intake.py` — интеграция: списание и предупреждение при пересечении порога через `handle_intake_callback`
- `tests/test_delete_user_data.py` — полное удаление данных пользователя по всем таблицам + изоляция от других
- Не трогают реальную БД и сеть — функции/хендлеры вызываются напрямую
- Конфиг — `pytest.ini` (`testpaths = tests`); dev-зависимости — `requirements-dev.txt`
- **Перед рефакторингом хендлеров**: запусти `pytest` до и после — `test_handlers.py` ловит изменения текста сообщений

## Conversational States
Состояния определены в `constants.py`:
- `NAME, DOSAGE, MEAL, TIMES, SCHEDULE` (0-4) — добавление лекарства (SCHEDULE не используется)
- `EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE` (5-9) — редактирование (EDIT_SCHEDULE не используется)
- `SETUP_TZ, SETUP_CITY` (10-11) — настройка часового пояса
- `FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY, FREQ_TIME` (12-16) — тип расписания при добавлении (FREQ_TIME не используется)
- `EDIT_FREQ_TYPE, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS, EDIT_FREQ_MONTHDAY, EDIT_FREQ_TIME` (17-21) — тип расписания при редактировании (EDIT_FREQ_TIME не используется)
- `PRESET_TIME` (22) — ввод времени пресета в настройках
- `DAILY_PLAN_TIME` (23) — ввод времени плана дня
- `DOSAGE_B, TIMES_B, FREQ_TYPE_B, FREQ_INTERVAL_B, FREQ_WEEKDAYS_B, FREQ_MONTHDAY_B` (29-34) — ветка «Разная дозировка» при добавлении
- `EDIT_DOSAGE_B` (35) — ввод дозировки Б при редактировании multi-dosage
- `SELECT_DEPENDENT` (36) — выбор «Для кого?» в начале add-флоу (caregiver)
- `ADD_DEPENDENT_NAME` (37) — ввод имени нового подопечного (settings + add-флоу)

Все диалоги поддерживают `/cancel` для выхода.

## Error Handling
- `DatabaseError` — custom exception в `database.py`
- Декоратор `@handle_db_errors` из `utils.py` — оборачивает handler-функции
- Ошибки БД пишутся в `db_errors.log`
- Ошибки Telegram API молча игнорируются в `send_reminders()` с записью в основной лог
- PDF генерируется в `asyncio.to_thread` чтобы не блокировать event loop

## Configuration
`.env` файл (не коммитится):
```
BOT_TOKEN=токен_от_BotFather
ADMIN_ID=telegram_id_админа
```

Логирование в `bot.py`: httpx, apscheduler, telegram, **fontTools** — уровень WARNING.

## Key Behaviors
- БД создаётся автоматически при первом запуске (`init_db()`)
- Часовой пояс запрашивается при `/start` если не задан (геолокация или город)
- Напоминания в local time пользователя (хранится в `users.timezone`)
- Режим напоминаний: `once` или `repeat` (каждые 5 минут до подтверждения, до 2 часов)
- Лимит лекарств: `MAX_MEDICATIONS_PER_USER = 10` (задан в `constants.py`)
- **Единая точка входа `/menu`** (`menu_command` в `timezone.py`): открывает главное меню. В списке команд бота (`post_init`) только `menu`. `/cancel` остаётся рабочим как fallback диалогов (выход из текстового ввода), но скрыт из меню; `/start` оставлен для онбординга (TZ); `/meds`/`/stats`/`/settings`/`/about` работают, но скрыты
- **Навигация edit-in-place**: пункты меню (`menu:today/meds/stats/settings/about`) редактируют текущее сообщение; `menu:main` возвращает главное меню. Все под-экраны имеют «◀️ В меню» (`back_menu_kb()` в `timezone.py`, `_stats_period_keyboard`/`_report_keyboard`/`_nav_keyboard` в `stats.py`, кнопка в `_settings_keyboard`, в списке лекарств). Слой навигации — глобальный handler `^menu:`, вне диалогов add/edit (не задевается Q1b)
- Главное меню — inline-кнопки: 📋 Лекарства на сегодня, 💊 Мои лекарства, 📊 Статистика, ⚙️ Настройки, ℹ️ О проекте
- **Мои лекарства** — многосообщенный список; «◀️ В меню» на завершающем сообщении (`show_meds_list`)
- **Лекарства на сегодня** (`menu:today`): показывает расписание на текущий день с иконками ✅/❌/⏳ по данным `get_today_intake_statuses()`
- **Статистика** (`menu:stats`): кнопки «📈 За 7 дней» и «📆 План на 7 дней»; под каждым отчётом — кнопка «📄 Скачать PDF»
- `log_intake` — upsert: при повторном нажатии обновляет запись за сегодня вместо дубля
- При удалении лекарства `clear_pending_for_medication()` сразу чистит `_pending` в scheduler
- `parse_time()` в `utils.py` нормализует формат → `ЧЧ:ММ` с ведущим нулём
- `handle_intake_callback` парсит `callback_data` как `status:med_id:HH:MM` → время восстанавливается через `":".join(parts[2:])`
- **Перезапуск после рефакторинга обязателен**: ConversationHandler хранит состояния в памяти
- Пресеты времени (🌅 Утро/☀️ Обед/🌇 Вечер/🌙 Ночь): хранятся в `users.time_morning/lunch/evening/night`, редактируются через `/settings` → "⏰ Настроить время приёмов"
- `SLOT_ORDER`, `SLOT_LABELS` в `constants.py`; `get_user_time_presets()` / `set_user_time_preset()` в `database.py`
- **Смена пресета мигрирует правила**: `set_user_time_preset()` обновляет все активные `schedule_rules` пользователя с `reminder_time == старое значение` на новое (слоты хранятся как снимок времени) — иначе старое время «зависает» в напоминаниях/списке/плане. Возвращает число перенесённых правил
- **Разная дозировка**: одно `medications`-запись, правила А с `dosage=NULL`, правила Б с `dosage=dosage_b`; планировщик использует `rule_dosage or med_dosage`; список лекарств показывает дату следующего срабатывания через `_next_fire_label()` + `_compute_next_fire()`
- **Один проход планировщика**: `send_reminders()` берёт `get_active_schedule_rows()` (все правила активных лекарств + поля пользователя одним запросом) и передаёт их в `_send_daily_plans(app, schedules)`; план дня фильтруется по `daily_plan_enabled` в Python — без второго запроса к БД
- **Plan на день**: `_daily_plan_sent: set` в `scheduler.py` предотвращает дубли (TTL-prune старше 2 дней); строки берутся из общего прохода (`daily_plan_enabled=1`)
- **Настройки одним запросом**: `fetch_settings_data()` использует `get_user_settings_row()` (одна строка вместо 5 соединений); список лекарств — `get_rules_grouped_for_user()` вместо N+1
- **ADMIN_ID**: читается через `os.getenv("ADMIN_ID")` в обоих `admin.py` и `settings.py`; обёрнут в `try/except ValueError`; `load_dotenv()` вызывается в `bot.py` **до** всех импортов
- **broadcast.py**: standalone скрипт, не импортирует handlers; завершение ввода текста — строка `.`; режим 2 требует подтверждения словом `да`
- **PDF export**: `_build_pdf()` в `handlers/export.py` использует DejaVuSans (`/usr/share/fonts/truetype/dejavu/`); вызывается через `asyncio.to_thread` чтобы не блокировать event loop; fontTools лог заглушён до WARNING в `bot.py`
- `escape_md()` применяется ко всем пользовательским строкам при отображении в `parse_mode="Markdown"`; stats.py и план используют HTML — пользовательские строки (название, дозировка, имя подопечного) экранируются через `escape_html()`
- **«Сегодня» по TZ пользователя**: `log_intake()` и `get_today_intake_statuses()` принимают диапазон `[start_utc, end_utc)` из `local_day_bounds_utc()`, а не UTC `date('now')`

## Known Issues & Bug Tracker

### ✅ Исправлено

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
| 35 | `handlers/timezone.py` | После установки TZ новому пользователю непонятно что делать |
| 36 | `handlers/stats.py` | В `/stats` нет плана лекарств на неделю |
| 37 | `handlers/stats.py`, `utils.py` | HTML без экранирования: имена/дозировки с `<`, `>`, `&` ломали статистику и план (сообщение не отправлялось). Добавлен `escape_html()` |
| 38 | `database.py`, `scheduler.py`, `handlers/timezone.py`, `utils.py` | «Сегодня» считалось по UTC `date('now')`, а не по TZ пользователя → рассинхрон статусов и upsert у границы суток. Введён `local_day_bounds_utc()` |
| 39 | `handlers/meds.py` | Multi-dosage edit показывал «Лекарство добавлено» вместо «обновлено» |
| 40 | `database.py` | Нет `PRAGMA busy_timeout/WAL/foreign_keys` → риск `database is locked` |
| 41 | `database.py` | Нет индексов → full-scan в планировщике и статистике. Добавлены 5 индексов |
| 42 | `database.py` | `delete_dependent` не занулял `dependent_id` → нарушение FK после включения `foreign_keys=ON` |
| 43 | `scheduler.py` | Утечки памяти: `_pending` (режим once) и `_daily_plan_sent` не очищались. Добавлен TTL-prune |
| 44 | `database.py`, `scheduler.py` | Планировщик делал 2 full-scan/мин (`get_all_schedules` + `get_users_with_daily_plan`). Объединено в `get_active_schedule_rows()` — один проход |
| 45 | `database.py`, `handlers/settings.py` | `fetch_settings_data` открывала 5 соединений на рендер. Сведено к одному `get_user_settings_row()` |
| 46 | `database.py`, `handlers/meds.py` | Список лекарств делал N+1 (`get_schedules_by_medication` в цикле). Заменено на `get_rules_grouped_for_user()` |
| 47 | `handlers/settings.py`, `handlers/timezone.py`, `bot.py` | Из под-экранов `/settings` (часовой пояс, время приёмов) нельзя вернуться в настройки. Добавлены «◀️ Назад»: `settings:back` для пресетов, reply-кнопка «◀️ Назад в настройки» для гео-флоу (`with_back`) |
| 48 | `constants.py`, `handlers/settings.py`, `handlers/timezone.py` | Дублирование текста «О проекте» в двух местах. Вынесено в `ABOUT_TEXT` |
| 49 | `database.py` | `db_logger` без `propagate=False` — ошибки БД дублировались в консоль root-логгера |
| 50 | `database.py` | `migrate()` повторно создавал таблицу `dependents` (уже в `init_db`). Удалён избыточный `CREATE TABLE` |
| 51 | `tests/`, `pytest.ini`, `requirements-dev.txt` | Не было тестов. Добавлены 58 unit-тестов на чистые функции (pytest) |
| 52 | `handlers/meds.py` | Дубль входа в add-флоу (`add_start` ≈ `handle_add_med_callback`). Объединено в `_begin_add_flow()` |
| 53 | `handlers/meds.py`, `tests/test_handlers.py` | Q1 (частично): success-сообщения сведены в `_med_saved_text()`, валидация диапазонов — в `_parse_int_range()` (8 save-хендлеров + 6 валидаций). Под защитой 24 характеризационных тестов |
| 54 | `handlers/timezone.py`, `stats.py`, `settings.py`, `meds.py`, `bot.py`, `tests/test_menu.py` | Непоследовательные «Назад»: часть экранов меню без возврата. Сделана единая точка входа `/menu` + навигация edit-in-place с «◀️ В меню» (`menu:main`) на всех экранах |
| 55 | `handlers/timezone.py`, `bot.py` | `telegram.error.TimedOut` ронял старт (незащищённый `set_my_commands`) и часто срабатывал на дефолтных 5с. Таймауты 20с + try/except в `post_init` |
| 57 | `database.py`, `handlers/settings.py` | **Баг**: смена пресета времени в `/settings` не прокидывалась в существующие напоминания/список/план (оставалось старое время). `set_user_time_preset` теперь мигрирует правила `reminder_time` старое→новое. Тесты `test_preset_migration` |
| UX | `handlers/meds.py`, `handlers/settings.py` | Пакет UX: подсказка «время слотов меняется в Настройках» на шаге «Когда принимать»; кнопка «Напоминания о приёме лекарств»→«🔔 Напоминания»; кнопка «📦 Указать запас» на сообщении «Лекарство добавлено/обновлено»; список лекарств — кнопки «Добавить»/«В меню» слиты в последнюю карточку (убран отдельный блок «Хочешь добавить ещё?») |
| 56 | `schedule_utils.py`, `database.py`, `handlers/stock.py`, `scheduler.py`, `handlers/meds.py`, `bot.py`, `constants.py` | **F5 реализована** — учёт запаса таблеток. Колонки `stock_qty/units_per_dose/low_stock_days`; экран «📦 Запас» (указать/пополнить/единицы/порог/выключить); автосписание при `taken` (идемпотентно через старый статус из `log_intake`); прогноз `days_of_stock_left`; событийное предупреждение при пересечении порога; индикатор в списке лекарств. Тесты: 18+9+5 |
| Q1b | `handlers/meds.py`, `tests/test_conv_structure.py` | Слияние идентичных наборов состояний add/edit (10 общих состояний) в `_schedule_input_states()` через `**`-распаковку. Под защитой снапшот-теста структуры диалогов |

### 🔲 К исправлению

| # | Файл | Проблема |
|---|------|----------|

### 💡 В планах (фичи)

> **Фундамент готов**: `schedule_utils.py` — чистая логика «положенных приёмов» (`due_intakes_on`, `iter_due_by_day`, `count_due_by_medication`, `count_due_total`). База для F2/F3/F5. `_rule_fires_today` перенесён туда из `scheduler.py` (реэкспортируется для совместимости). Покрыто `tests/test_schedule_utils.py`. ⚠️ Потребители аналитики должны сами ограничивать период началом действия лекарства (хелпер применяет правило к любой дате).

| # | Файл | Описание |
|---|------|----------|
| F1 | `handlers/export.py`, `database.py`, `handlers/stats.py` | **Отчёт для врача** — PDF с историей приёма за месяц для распечатки на приём. Период: последние 30 дней (или выбор месяца). Содержание: шапка (пациент/подопечный, период, дата формирования); по каждому лекарству — название, дозировка, расписание, приверженность % (taken/total); таблица приёмов по дням с отметками ✅/❌; итоговая сводка. Переиспользовать `_build_pdf` (новые `sections`) + `asyncio.to_thread`. Новый коллбэк `export:doctor` + кнопка в `/stats`/меню. Запросы: `get_history_detailed`/`get_history` с `days=30` (диапазон в TZ пользователя через `local_day_bounds_utc`-логику). Учесть caregiver: выбор «для кого» или отдельные секции по подопечным |
| F2 | `database.py`, `handlers/stats.py`, `scheduler.py` | **Streak / серия** — «принимаешь N дней подряд 🔥», мотивирует не пропускать. «Идеальный день» = все запланированные на день приёмы отмечены `taken` (нет `skipped`/`pending`); серия = число подряд идущих идеальных дней до сегодня (текущий день не рвёт серию, пока приёмы ещё `pending`). Расчёт: для каждого дня определить «положенные» приёмы через `_rule_fires_today` + сверить с `intake_log` (в TZ пользователя). Показ: в `/stats`, «Лекарства на сегодня» и/или главном меню — «🔥 N дней подряд»; миля-стоуны (7/30 дней) — поощрительное сообщение. Хранить можно вычисляемо (без новой колонки) либо кешировать `best_streak` в `users`. Учесть caregiver (серия общая или по подопечному — решить) |
| F3 | `database.py`, `handlers/stats.py` | **Процент соблюдения за месяц (adherence rate)** — главная метрика медприложений. Формула: `taken / запланировано` за 30 дней (знаменатель — все «положенные» приёмы из расписания через `_rule_fires_today`, а **не** только залогированные строки `intake_log`, иначе пропуски без отметки не учтутся). Показ: в `/stats` отдельной строкой с цветовым индикатором (🟢 ≥80% / 🟡 ≥50% / 🔴) — переиспользовать существующую логику порогов из `stats.py`; разбивка по каждому лекарству + общий итог. Связано с F1 (метрика идёт в отчёт для врача) и F2 (общий расчёт «положенных» приёмов за период — вынести в общий хелпер) |
| F4 | `database.py`, `handlers/meds.py`, `scheduler.py`, `constants.py` | **Пауза лекарства** — временно отключить напоминания без удаления (например, в отпуске). Новое состояние: колонка `medications.paused` (0/1) ИЛИ `paused_until` (дата автовозобновления). Планировщик `get_active_schedule_rows` фильтрует `paused=0` (и/или `paused_until < today`); `clear_pending_for_medication` при постановке на паузу. UI: кнопка «⏸ Пауза»/«▶️ Возобновить» в списке лекарств рядом с «Изменить/Удалить»; пометка «⏸ на паузе» в списке и «Лекарства на сегодня». Опционально — пауза до даты с автовозобновлением. Не должно ломать adherence (F3): дни на паузе исключать из знаменателя. Связь с F5: на паузе не списывать запас и не слать предупреждения (в `_update_stock_on_intake`/`apply_intake_stock` учесть `paused`) |
| F6 | `scheduler.py`, `handlers/timezone.py`, `database.py` | **Быстрое подтверждение всех лекарств сразу** — одна кнопка «✅ Принять всё». Где: под «Лекарствами на сегодня» и/или в напоминании. Логика: собрать все сегодняшние «положенные» приёмы со статусом `pending`/нет записи (через `get_schedules_for_user` + `_rule_fires_today` + `get_today_intake_statuses`), для каждого `log_intake(..., 'taken')` в диапазоне локальных суток. Коллбэк `take_all` (опц. `take_all:<dependent_id>` для caregiver). После — обновить экран с иконками ✅. Не перетирать уже отмеченные `skipped` без подтверждения (решить) |
| F7 | `database.py`, `handlers/caregiver.py`, `scheduler.py` | **Социальное / Caregiver-расширение** (есть задел: таблица `dependents`, `medications.dependent_id`, режим в `/settings`). Идеи: уведомлять опекуна о пропусках подопечного («Маша не приняла лекарство в 09:00»); сводка приверженности подопечного; возможно — связать двух реальных пользователей (опекун ↔ подопечный по telegram_id, а не только локальная запись), приглашение/подтверждение. Требует продумать приватность и согласие. Строить поверх существующего caregiver-флоу |

### ✅ Исправлено (caregiver)

| # | Файл | Проблема |
|---|------|----------|
| 34 | `database.py`, `handlers/meds.py`, `handlers/caregiver.py`, `scheduler.py`, `constants.py` | **Caregiver-режим**: таблица `dependents`, `medications.dependent_id`, `/settings` кнопка с вкл/выкл, шаг «Для кого?» в add-флоу, лимит 10 лекарств на каждого подопечного, напоминания с «(для Маши)», `MAX_DEPENDENTS=2` |

### Порядок работы с багами
1. Найти баг → добавить в таблицу "К исправлению"
2. Исправить → перенести в "Исправлено"
3. После каждой серии правок — запустить бота и проверить основной флоу: `/start` → `/meds` → добавить → изменить → `/stats`
