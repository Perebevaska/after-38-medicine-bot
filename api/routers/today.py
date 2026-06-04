import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import database as db
from api.auth import require_telegram_user, require_db_user, TelegramUser
from utils import get_tz_for_user, local_day_bounds_utc
from schedule_utils import _rule_fires_today
from datetime import datetime

router = APIRouter(prefix="/today", tags=["today"])


class IntakeIn(BaseModel):
    medication_id: int
    scheduled_time: str
    status: str   # "taken" | "skipped" | "pending" (undo)


def _build_today_items(
    rows, statuses, today, now_min, *,
    linked_user_id=None, linked_user_name=None,
    dep_share_id=None, dep_share_name=None,
):
    items = []
    for row in rows:
        if not _rule_fires_today(row, today):
            continue
        mid = row["medication_id"]
        t = row["reminder_time"]
        status = statuses.get((mid, t), "pending")
        try:
            rh, rm = t.split(":")
            is_due = now_min >= int(rh) * 60 + int(rm)
        except (ValueError, AttributeError):
            is_due = False
        item = {
            "medication_id": mid,
            "name": row["name"],
            "dosage": row.get("rule_dosage") or row["med_dosage"],
            "meal_relation": row["meal_relation"],
            "reminder_time": t,
            "status": status,
            "is_due": is_due,
            "dependent_id": row.get("dependent_id"),
            "dependent_name": row.get("dependent_name"),
        }
        if linked_user_id is not None:
            item["linked_user_id"] = linked_user_id
            item["linked_user_name"] = linked_user_name
        if dep_share_id is not None:
            item["dep_share_id"] = dep_share_id
            item["dep_share_name"] = dep_share_name
        items.append(item)
    return items


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
    now_min = now_local.hour * 60 + now_local.minute
    # AX5: is_due считаем по TZ пользователя на сервере
    items = _build_today_items(rows, statuses, today, now_min)
    # F7: append linked dependents' today (read-only for caregiver)
    linked = await asyncio.to_thread(db.get_linked_dependents_for_caregiver, telegram_id)
    for dep in linked:
        dep_tid = dep["telegram_id"]
        dep_tz = await asyncio.to_thread(get_tz_for_user, dep_tid)
        dep_local = datetime.now(dep_tz)
        dep_start, dep_end = local_day_bounds_utc(dep_tz, dep_local)
        dep_statuses = await asyncio.to_thread(
            db.get_today_intake_statuses, dep_tid, dep_start, dep_end
        )
        # F7-fix: только собственные лекарства подопечного, без его локальных близких
        dep_rows = await asyncio.to_thread(db.get_own_schedules_for_user, dep_tid)
        dep_today = dep_local.date()
        dep_now_min = dep_local.hour * 60 + dep_local.minute
        dep_name = dep["username"] or f"id{dep_tid}"
        items.extend(_build_today_items(
            dep_rows, dep_statuses, dep_today, dep_now_min,
            linked_user_id=dep["user_id"], linked_user_name=dep_name,
        ))
    # F8: append shared local dependents' today (read-only for viewer)
    shared_deps = await asyncio.to_thread(db.get_shared_deps_for_viewer, telegram_id)
    for sdep in shared_deps:
        dep_rows = await asyncio.to_thread(db.get_schedules_for_dependent, sdep["dep_id"])
        if not dep_rows:
            continue
        owner_tz = await asyncio.to_thread(get_tz_for_user, sdep["owner_telegram_id"])
        owner_local = datetime.now(owner_tz)
        owner_start, owner_end = local_day_bounds_utc(owner_tz, owner_local)
        dep_statuses = await asyncio.to_thread(
            db.get_today_intake_statuses_for_dep, sdep["dep_id"], owner_start, owner_end
        )
        owner_today = owner_local.date()
        owner_now_min = owner_local.hour * 60 + owner_local.minute
        items.extend(_build_today_items(
            dep_rows, dep_statuses, owner_today, owner_now_min,
            dep_share_id=sdep["dep_id"], dep_share_name=sdep["dep_name"],
        ))
    return sorted(items, key=lambda x: x["reminder_time"], reverse=True)


@router.post("/intake", status_code=204)
async def log_intake(body: IntakeIn, user: TelegramUser = Depends(require_db_user)):
    med = await asyncio.to_thread(db.get_medication_by_id_raw, body.medication_id)
    owner_user_id = med["user_id"] if med else None
    if not med:
        raise HTTPException(404, "Препарат не найден")
    # Доступ: собственное лекарство ИЛИ лекарство shared-близкого (помощник №2
    # отмечает приём за локального близкого — у того нет своего аккаунта).
    if owner_user_id != user.user_id:
        viewer_deps = await asyncio.to_thread(db.get_viewer_shared_deps, user.user_id)
        viewer_dep_ids = {vd["dep_id"] for vd in viewer_deps}
        if med.get("dependent_id") not in viewer_dep_ids:
            raise HTTPException(404, "Препарат не найден")
    # День считаем в TZ владельца лекарства (расписание строится в его TZ).
    owner_tid = (
        user.telegram_id if owner_user_id == user.user_id
        else await asyncio.to_thread(db.get_telegram_id_by_user_id, owner_user_id)
    )
    owner_tz = await asyncio.to_thread(get_tz_for_user, owner_tid)
    now_local = datetime.now(owner_tz)
    start_utc, end_utc = local_day_bounds_utc(owner_tz, now_local)
    old_status = await asyncio.to_thread(
        db.log_intake, body.medication_id, body.scheduled_time,
        body.status, start_utc, end_utc,
    )
    await asyncio.to_thread(
        db.apply_intake_stock, body.medication_id, body.status, old_status,
        body.scheduled_time,
    )
    # G1: сердечки начисляются ВСЕМ в связке — владельцу + всем активным
    # помощникам локального близкого (общая забота = общая награда).
    heart_user_ids = {owner_user_id}
    if med.get("dependent_id") is not None:
        viewers = await asyncio.to_thread(db.get_dep_share_viewer_ids, med["dependent_id"])
        heart_user_ids.update(viewers)
    for uid in heart_user_ids:
        await asyncio.to_thread(db.apply_intake_hearts, uid, body.status, old_status)
