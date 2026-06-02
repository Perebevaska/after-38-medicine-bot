import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import database as db
from api.auth import require_telegram_user, require_db_user, TelegramUser
from utils import get_tz_for_user, local_day_bounds_utc
from schedule_utils import due_intakes_on
from datetime import datetime

router = APIRouter(prefix="/today", tags=["today"])


class IntakeIn(BaseModel):
    medication_id: int
    scheduled_time: str
    status: str   # "taken" | "skipped"


@router.get("")
async def get_today(telegram_id: int = Depends(require_telegram_user)):
    user_tz = await asyncio.to_thread(get_tz_for_user, telegram_id)
    now_local = datetime.now(user_tz)
    start_utc, end_utc = local_day_bounds_utc(user_tz, now_local)
    statuses = await asyncio.to_thread(
        db.get_today_intake_statuses, telegram_id, start_utc, end_utc
    )
    rows = await asyncio.to_thread(db.get_schedules_for_user, telegram_id)
    today = now_local.date()
    items = []
    for row in rows:
        from schedule_utils import _rule_fires_today
        if not _rule_fires_today(row, today):
            continue
        mid = row["medication_id"]
        t = row["reminder_time"]
        status = statuses.get((mid, t), "pending")
        items.append({
            "medication_id": mid,
            "name": row["name"],
            "dosage": row.get("rule_dosage") or row["med_dosage"],
            "meal_relation": row["meal_relation"],
            "reminder_time": t,
            "status": status,
            "dependent_name": row.get("dependent_name"),
        })
    return sorted(items, key=lambda x: x["reminder_time"])


@router.post("/intake", status_code=204)
async def log_intake(body: IntakeIn, user: TelegramUser = Depends(require_db_user)):
    if not await asyncio.to_thread(db.get_medication_by_id, body.medication_id, user.user_id):
        raise HTTPException(404, "Лекарство не найдено")
    user_tz = await asyncio.to_thread(get_tz_for_user, user.telegram_id)
    now_local = datetime.now(user_tz)
    start_utc, end_utc = local_day_bounds_utc(user_tz, now_local)
    old_status = await asyncio.to_thread(
        db.log_intake, body.medication_id, body.scheduled_time,
        body.status, start_utc, end_utc,
    )
    await asyncio.to_thread(
        db.apply_intake_stock, body.medication_id, body.status, old_status
    )
