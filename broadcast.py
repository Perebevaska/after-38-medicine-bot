"""
Скрипт рассылки сообщений всем пользователям бота.
Запуск: python3 broadcast.py
"""
import asyncio
import os
import sqlite3
import time

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = "med_bot.db"


def get_all_user_ids() -> list[int]:
    """Возвращает список всех telegram_id из БД; при ошибке — пустой список."""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT telegram_id FROM users").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except sqlite3.Error as e:
        print(f"Ошибка БД: {e}")
        return []


def read_message_text() -> str:
    """Считывает многострочный текст сообщения; ввод завершается строкой «.»."""
    print("Введи текст сообщения. Строка с одной точкой «.» — завершить ввод.")
    print("Поддерживается HTML: <b>жирный</b>, <i>курсив</i>, <code>код</code>")
    print("-" * 40)
    lines = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
    return "\n".join(lines).strip()


async def send_broadcast(targets: list[int], text: str):
    """Отправляет text всем telegram_id из targets; логирует успех/ошибки для каждого."""
    bot = Bot(BOT_TOKEN)
    ok = 0
    fail = 0
    for i, uid in enumerate(targets, 1):
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode="HTML")
            ok += 1
            print(f"  [{i}/{len(targets)}] ✅ {uid}")
        except TelegramError as e:
            fail += 1
            print(f"  [{i}/{len(targets)}] ❌ {uid} — {e}")
        if len(targets) > 1:
            await asyncio.sleep(0.05)  # ~20 сообщений/сек, лимит Telegram 30/сек
    print(f"\nИтог: ✅ {ok} отправлено, ❌ {fail} ошибок")


def main():
    """Интерактивный CLI рассылки: ввод текста → выбор аудитории → подтверждение → отправка."""
    print("=" * 40)
    print("       РАССЫЛКА — After 30 Med Bot")
    print("=" * 40)

    text = read_message_text()
    if not text:
        print("Текст пустой. Отмена.")
        return

    print(f"\nПредпросмотр:\n{'-' * 40}\n{text}\n{'-' * 40}")

    print("\nКуда отправить?")
    print("  1 — только мне (тест)")
    print("  2 — всем пользователям")
    mode = input("> ").strip()

    if mode == "1":
        targets = [ADMIN_ID]
        print(f"\nТест: отправка на {ADMIN_ID}")
    elif mode == "2":
        all_ids = get_all_user_ids()
        confirm = input(f"\nОтправить {len(all_ids)} пользователям? Напиши «да» для подтверждения: ").strip()
        if confirm != "да":
            print("Отменено.")
            return
        targets = all_ids
    else:
        print("Неверный выбор. Отмена.")
        return

    print("\nОтправляю...")
    asyncio.run(send_broadcast(targets, text))


if __name__ == "__main__":
    main()
