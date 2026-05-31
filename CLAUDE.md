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
├── constants.py        # States, MEAL_LABELS, MONTHS_GEN, MAX_MEDICATIONS_PER_USER
├── utils.py            # handle_db_errors, get_tz_for_user, cancel, escape_md, parse_time
├── broadcast.py        # standalone скрипт рассылки (python3 broadcast.py)
└── handlers/
    ├── meds.py         # add/edit/delete medications
    ├── stats.py        # stats_week, show_week_plan
    ├── export.py       # PDF экспорт плана и истории (asyncio.to_thread)
    ├── settings.py     # settings, about, reminder_mode toggle, daily plan
    ├── admin.py        # админ-панель (только ADMIN_ID)
    └── timezone.py     # start, timezone setup, main menu, Лекарства на сегодня
```

### Схема БД
4 активные таблицы:
- `users` (telegram_id, username, timezone, reminder_mode, time_morning, time_lunch, time_evening, time_night, daily_plan_enabled, daily_plan_time)
- `medications` (user_id FK, name, dosage, meal_relation, times_per_day, active)
- `schedule_rules` (medication_id FK, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date, dosage) — `dosage NULL` = берётся из `medications.dosage`
- `intake_log` (medication_id FK, scheduled_time, taken_at, status: taken/skipped/pending)

Таблица `schedules` удалена в `migrate()` через `DROP TABLE IF EXISTS schedules`.

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
```

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
- Главное меню `/start` — inline-кнопки: 📋 Лекарства на сегодня, 💊 Мои лекарства, 📊 Статистика, ⚙️ Настройки, ℹ️ О проекте
- **Лекарства на сегодня** (`menu:today`): показывает расписание на текущий день с иконками ✅/❌/⏳ по данным `get_today_intake_statuses()`
- **Статистика** (`menu:stats`): кнопки «📈 За 7 дней» и «📆 План на 7 дней»; под каждым отчётом — кнопка «📄 Скачать PDF»
- `log_intake` — upsert: при повторном нажатии обновляет запись за сегодня вместо дубля
- При удалении лекарства `clear_pending_for_medication()` сразу чистит `_pending` в scheduler
- `parse_time()` в `utils.py` нормализует формат → `ЧЧ:ММ` с ведущим нулём
- `handle_intake_callback` парсит `callback_data` как `status:med_id:HH:MM` → время восстанавливается через `":".join(parts[2:])`
- **Перезапуск после рефакторинга обязателен**: ConversationHandler хранит состояния в памяти
- Пресеты времени (🌅 Утро/☀️ Обед/🌇 Вечер/🌙 Ночь): хранятся в `users.time_morning/lunch/evening/night`, редактируются через `/settings` → "⏰ Настроить время приёмов"
- `SLOT_ORDER`, `SLOT_LABELS` в `constants.py`; `get_user_time_presets()` / `set_user_time_preset()` в `database.py`
- **Разная дозировка**: одно `medications`-запись, правила А с `dosage=NULL`, правила Б с `dosage=dosage_b`; планировщик использует `rule_dosage or med_dosage`; список лекарств показывает дату следующего срабатывания через `_next_fire_label()` + `_compute_next_fire()`
- **Plan на день**: `_daily_plan_sent: set` в `scheduler.py` предотвращает дубли; `get_users_with_daily_plan()` возвращает строки только для пользователей с `daily_plan_enabled=1`
- **ADMIN_ID**: читается через `os.getenv("ADMIN_ID")` в обоих `admin.py` и `settings.py`; обёрнут в `try/except ValueError`; `load_dotenv()` вызывается в `bot.py` **до** всех импортов
- **broadcast.py**: standalone скрипт, не импортирует handlers; завершение ввода текста — строка `.`; режим 2 требует подтверждения словом `да`
- **PDF export**: `_build_pdf()` в `handlers/export.py` использует DejaVuSans (`/usr/share/fonts/truetype/dejavu/`); вызывается через `asyncio.to_thread` чтобы не блокировать event loop; fontTools лог заглушён до WARNING в `bot.py`
- `escape_md()` применяется ко всем пользовательским строкам при отображении в `parse_mode="Markdown"`; stats.py использует HTML и не требует экранирования

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

### 🔲 К исправлению

| # | Файл | Проблема |
|---|------|----------|
| 34 | `database.py`, `handlers/meds.py`, `scheduler.py`, `constants.py` | **Caregiver-режим**: новая таблица `dependents (id, user_id FK, name)` + колонка `medications.dependent_id FK NULL`. UX: шаг "Для кого?" в начале add-флоу → `[👤 Для себя] [👧 Маша] [➕ Новый подопечный]`. Список `/meds` разбит на секции. Напоминание: `💊 Амоксициллин (для Маши) — 250 мг`. Лимит 10 лекарств считается отдельно на каждого. Новое состояние `SELECT_DEPENDENT = 36`. |

### Порядок работы с багами
1. Найти баг → добавить в таблицу "К исправлению"
2. Исправить → перенести в "Исправлено"
3. После каждой серии правок — запустить бота и проверить основной флоу: `/start` → `/meds` → добавить → изменить → `/stats`
