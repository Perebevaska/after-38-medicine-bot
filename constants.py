"""Константы и состояния ConversationHandler для med-bot."""

MAX_MEDICATIONS_PER_USER = 10

# Состояния диалогов
NAME, DOSAGE, MEAL, TIMES, SCHEDULE = range(5)
EDIT_NAME, EDIT_DOSAGE, EDIT_MEAL, EDIT_TIMES, EDIT_SCHEDULE = range(5, 10)
SETUP_TZ, SETUP_CITY = range(10, 12)
FREQ_TYPE, FREQ_INTERVAL, FREQ_WEEKDAYS, FREQ_MONTHDAY, FREQ_TIME = range(12, 17)
EDIT_FREQ_TYPE, EDIT_FREQ_INTERVAL, EDIT_FREQ_WEEKDAYS, EDIT_FREQ_MONTHDAY, EDIT_FREQ_TIME = range(17, 22)
PRESET_TIME = 22       # состояние ввода времени пресета в настройках
DAILY_PLAN_TIME = 23   # состояние ввода времени плана дня

# Добавление лекарства с разными дозировками
DOSAGE_B = 29
TIMES_B = 30
FREQ_TYPE_B = 31
FREQ_INTERVAL_B = 32
FREQ_WEEKDAYS_B = 33
FREQ_MONTHDAY_B = 34
EDIT_DOSAGE_B = 35

CANCEL_TIP = "_(/cancel для отмены)_"

SLOT_ORDER = ["morning", "lunch", "evening", "night"]
SLOT_LABELS = {
    "morning": "🌅 Утро",
    "lunch":   "☀️ Обед",
    "evening": "🌇 Вечер",
    "night":   "🌙 Ночь",
}

MEAL_LABELS = {
    "before": "До еды",
    "after": "После еды",
    "with": "Во время еды",
    "any": "Независимо",
}

MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

MONTHS_SHORT = ["янв","фев","мар","апр","мая","июн","июл","авг","сен","окт","ноя","дек"]
