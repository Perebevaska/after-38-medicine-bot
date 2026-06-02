import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
import database as db
from api.auth import require_db_user, TelegramUser
from schedule_utils import count_due_by_medication
from streak import streaks_by_subject
from utils import get_tz_for_user

router = APIRouter(prefix="/stats", tags=["stats"])

_ADHERENCE_DAYS = 30


def _adherence_window():
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=_ADHERENCE_DAYS)
    return (
        start.strftime("%Y-%m-%d %H:%M:%S"),
        end.strftime("%Y-%m-%d %H:%M:%S"),
    )


@router.get("/week")
async def stats_week(user: TelegramUser = Depends(require_db_user)):
    rows = await asyncio.to_thread(db.get_history_by_days, user.user_id, 7)
    return [dict(r) for r in rows]


@router.get("/adherence")
async def stats_adherence(user: TelegramUser = Depends(require_db_user)):
    start_utc, end_utc = _adherence_window()
    rules = await asyncio.to_thread(db.get_adherence_rules, user.user_id)
    taken = await asyncio.to_thread(db.get_taken_counts, user.user_id, start_utc, end_utc)
    if not rules:
        return {"medications": [], "total_pct": None}
    result = []
    total_due = total_taken = 0
    for rule in rules:
        mid = rule["medication_id"]
        due = count_due_by_medication(rule, start_utc[:10], end_utc[:10])
        t = taken.get(mid, 0)
        pct = round(t / due * 100) if due else 0
        total_due += due
        total_taken += t
        result.append({
            "medication_id": mid,
            "name": rule["name"],
            "dosage": rule["med_dosage"],
            "dependent_name": rule.get("dependent_name"),
            "due": due,
            "taken": t,
            "pct": pct,
        })
    # Схлопываем дубли по medication_id (несколько rules на одно лекарство)
    merged: dict[int, dict] = {}
    for item in result:
        mid = item["medication_id"]
        if mid not in merged:
            merged[mid] = {**item}
        else:
            merged[mid]["due"] += item["due"]
            merged[mid]["taken"] += item["taken"]
            d = merged[mid]["due"]
            merged[mid]["pct"] = round(merged[mid]["taken"] / d * 100) if d else 0
    total_pct = round(total_taken / total_due * 100) if total_due else None
    return {"medications": list(merged.values()), "total_pct": total_pct}


@router.get("/streak")
async def stats_streak(user: TelegramUser = Depends(require_db_user)):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=90)
    start_utc = start.strftime("%Y-%m-%d %H:%M:%S")
    end_utc = end.strftime("%Y-%m-%d %H:%M:%S")
    user_tz = await asyncio.to_thread(get_tz_for_user, user.telegram_id)
    rules = await asyncio.to_thread(db.get_streak_rows, user.user_id)
    intakes = await asyncio.to_thread(db.get_intake_statuses_window, user.user_id, start_utc, end_utc)
    return streaks_by_subject(rules, intakes, user_tz, end.date())
