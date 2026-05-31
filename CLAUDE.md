# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## About
Telegram бот для напоминаний о приёме лекарств с поддержкой гибкого расписания, статистики и определения часовых поясов.

## Stack
- **Language**: Python 3.14
- **Framework**: python-telegram-bot 22.7 (async API)
- **Scheduler**: APScheduler 3.11.2 (задача каждую минуту)
- **Database**: SQLite (`med_bot.db`)
- **Timezone**: pytz, timezonefinder, geopy

## Architecture

### Структура
```
med-bot/
├── bot.py              # точка входа — только main() + регистрация handlers
├── database.py         # SQLite CRUD через get_connection()
├── scheduler.py        # send_reminders() каждую минуту
├── constants.py        # States, MEAL_LABELS, MONTHS_GEN, MAX_MEDICATIONS_PER_USER
├── utils.py            # handle_db_errors, get_tz_for_user, cancel
└── handlers/
    ├── meds.py         # add/edit/delete medications
    ├── stats.py        # stats_today, stats_week
    ├── settings.py     # settings, about, reminder_mode toggle
    └── timezone.py     # start, timezone setup, main menu
```

### Схема БД
5 таблиц:
- `users` (telegram_id, username, timezone, reminder_mode)
- `medications` (user_id FK, name, dosage, meal_relation, times_per_day, active)
- `schedules` (medication_id FK, reminder_time HH:MM) — устаревшая, оставлена для совместимости
- `schedule_rules` (medication_id FK, reminder_time, frequency, interval_days, weekdays, month_day, anchor_date)
- `intake_log` (medication_id FK, scheduled_time, taken_at, status: taken/skipped/pending)

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

### Флоу добавления лекарства
```
Название → Дозировка → Сколько раз в день → Время × N → Как принимать с пищей → Тип расписания:
  📅 Каждый день   → сохранить
  🔄 Через N дней  → N дней → сохранить
  📆 По дням недели → Дни (toggle) → сохранить
  🗓 Раз в месяц   → Число → сохранить
```

Время всегда собирается сразу после "сколько раз", до выбора типа расписания.
Каждое время сохраняется отдельной строкой в `schedule_rules` с одинаковыми frequency-параметрами.

### Флоу редактирования лекарства
```
Название → Дозировка → Тип расписания:
  Оставить расписание → сохранить (имя/дозировка, прочее без изменений)
  Каждый день / Через N / По дням / Раз в месяц →
    Кол-во раз → Время × N → Как принимать с пищей →
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
app.add_handler(meds.get_add_handler(cancel_handler))
app.add_handler(meds.get_edit_handler(cancel_handler))
app.add_handler(CallbackQueryHandler(tz_handler.handle_menu_callback, pattern="^menu:"))
```

### utils.py
- `handle_db_errors` — декоратор: ловит `DatabaseError`, отвечает пользователю
- `get_tz_for_user(telegram_id)` → `pytz.timezone` объект
- `cancel` — handler для `/cancel`, завершает любой ConversationHandler

## Commands

```bash
# Разработка
source venv/bin/activate
python3 bot.py

# Установка зависимостей
pip install -r requirements.txt

# Миграция БД (при изменении схемы)
# database.migrate() вызывается автоматически в bot.py при старте
# Автоматически переносит schedules → schedule_rules с frequency='daily'
```

## Conversational States
Состояния определены в `constants.py`:
- `NAME, DOSAGE, MEAL, TIMES, SCHEDULE` (0-4) — добавление лекарства
- `EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE` (5-9) — редактирование
- `SETUP_TZ, SETUP_CITY` (10-11) — настройка часового пояса
- `FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY` (12-15) — тип расписания при добавлении
- `EDIT_FREQ_TYPE, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS, EDIT_FREQ_MONTHDAY` (17-20) — тип расписания при редактировании

Примечание: `FREQ_TIME` (16) и `EDIT_FREQ_TIME` (21) определены в constants.py для совместимости, но не используются в handlers — время собирается в SCHEDULE/EDIT_SCHEDULE до выбора типа расписания.

Все диалоги поддерживают `/cancel` для выхода.

## Error Handling
- `DatabaseError` — custom exception в `database.py`
- Декоратор `@handle_db_errors` из `utils.py` — оборачивает handler-функции
- Ошибки БД пишутся в `db_errors.log`
- Ошибки Telegram API молча игнорируются в `send_reminders()` с записью в основной лог

## Configuration
`.env` файл (не коммитится):
```
BOT_TOKEN=токен_от_BotFather
TIMEZONE=Asia/Yekaterinburg
```

## Key Behaviors
- БД создаётся автоматически при первом запуске (`init_db()`)
- Часовой пояс запрашивается при `/start` если не задан (геолокация или город)
- Напоминания в local time пользователя (хранится в `users.timezone`)
- Режим напоминаний: `once` или `repeat` (каждые 5 минут до подтверждения)
- Лимит лекарств: `MAX_MEDICATIONS_PER_USER = 10` (задан в `constants.py`)
- Главное меню `/start` — inline-кнопки (💊 Мои лекарства, 📊 Статистика, ⚙️ Настройки, ℹ️ О проекте)
- `log_intake` — upsert: при повторном нажатии обновляет запись за сегодня вместо дубля
- При удалении лекарства `clear_pending_for_medication()` сразу чистит `_pending` в scheduler
- Время нормализуется через `_parse_time()` → формат `ЧЧ:ММ` с ведущим нулём (гарантирует совпадение с `strftime("%H:%M")` в планировщике)
- `handle_intake_callback` парсит `callback_data` как `status:med_id:HH:MM` → время восстанавливается через `":".join(parts[2:])`
- **Перезапуск после рефакторинга обязателен**: ConversationHandler хранит состояния в памяти; старые сессии могут блокировать новые handlers до перезапуска

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
| 8 | `handlers/meds.py` | TIMES/MEAL состояния без паттернов — ловили любой callback (в т.ч. `add_med`) |
| 9 | `database.py` | `log_intake` делал `INSERT` при каждом нажатии — теперь upsert по (medication_id, scheduled_time, date) |
| 10 | `scheduler.py` | Ключи удалённых лекарств висели в `_pending` — теперь очищаются через `clear_pending_for_medication()` |
| 11 | `handlers/meds.py` | При смене количества приёмов показывались старые времена в подсказке |
| 12 | `scheduler.py` | `handle_intake_callback` брал `parts[2]` как время — обрезал минуты (`"09:30"` → `"09"`) |
| 13 | `handlers/meds.py` | `_check_time` не нормализовал формат — `"9:5"` хранилось и никогда не совпадало с `"09:05"` |
| 14 | `handlers/timezone.py` | `handle_menu_callback` не был обёрнут в `@handle_db_errors` |
| 15 | `handlers/meds.py` | `keep_edit_schedule` не показывал `🔢 X раз в день` в подтверждении |
| 16 | `handlers/meds.py` | Мёртвый код `add_freq_time` / `edit_freq_time` (убраны из states, но остались в файле) |

### 🔲 К исправлению

Багов нет.

### Порядок работы с багами
1. Найти баг → добавить в таблицу "К исправлению"
2. Исправить → перенести в "Исправлено"
3. После каждой серии правок — запустить бота и проверить основной флоу: `/start` → `/meds` → добавить → изменить → `/stats`
