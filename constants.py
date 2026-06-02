"""Константы и состояния ConversationHandler для med-bot."""

MAX_MEDICATIONS_PER_USER = 10
MAX_DEPENDENTS = 2
DEPENDENT_NAME_MAX_LEN = 30

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

SELECT_DEPENDENT = 36       # выбор «для кого» в начале add-флоу (caregiver)
ADD_DEPENDENT_NAME = 37     # ввод имени нового подопечного (caregiver settings + add-флоу)

STOCK_INPUT = 38            # ввод числа в экране «Запас» (F5): остаток/пополнение/единицы/порог

CANCEL_TIP = "<i>(/cancel для отмены)</i>"

ABOUT_TEXT = (
    "ℹ️ <b>О проекте</b>\n\n"
    "After 30 Med Bot — вайб-кодинг проект: написан в паре с AI (Claude).\n"
    "Код живой, рабочий, итерируем дальше 🚀\n\n"
    "<b>Что умею:</b>\n"
    "💊 Напоминания по гибкому расписанию (каждый день / через N / по дням / раз в месяц)\n"
    "⏰ Свои пресеты времени, режим повтора, план на день\n"
    "📦 Учёт запаса таблеток с прогнозом и предупреждением\n"
    "⏸ Пауза лекарства без удаления\n"
    "📊 Статистика, соблюдение за 30 дней и серия идеальных дней 🔥\n"
    "🩺 PDF-отчёт для врача и экспорт истории/плана\n"
    "👨‍👩‍👧 Caregiver-режим — следить за приёмами близких\n\n"
    '📦 <a href="https://github.com/Perebevaska/after-30-medicine-bot">GitHub</a>\n\n'
    "<b>В планах:</b>\n"
    "✅ Быстрое подтверждение всех лекарств одной кнопкой\n"
    "🔔 Уведомления опекуну о пропусках подопечного\n"
    "📱 Telegram Mini App"
)

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
