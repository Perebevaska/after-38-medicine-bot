import asyncio
import os
from typing import Literal, Optional
import pytz
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from timezonefinder import TimezoneFinder
import database as db
from api.auth import require_telegram_user
from constants import SLOT_ORDER
from utils import parse_time

router = APIRouter(prefix="/settings", tags=["settings"])

_tf = TimezoneFinder()

# SEC-4: «HH:MM» — общий валидатор времени для пресетов/плана дня.
def _v_time(v):
    if v is None:
        return v
    try:
        return parse_time(v)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("время должно быть в формате ЧЧ:ММ")


class TimezoneIn(BaseModel):
    timezone: str = Field(max_length=64)


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ReminderModeIn(BaseModel):
    mode: Literal["once", "repeat"]
    hours: Optional[int] = Field(default=None, ge=0, le=23)
    minutes: Optional[int] = Field(default=0, ge=0, le=59)


class PresetIn(BaseModel):
    time: str
    _v = field_validator("time")(_v_time)


class DailyPlanIn(BaseModel):
    enabled: bool
    time: Optional[str] = None
    _v = field_validator("time")(_v_time)


class CaregiverIn(BaseModel):
    enabled: bool


class StrictModeIn(BaseModel):
    enabled: bool
    hours: Optional[int] = Field(default=None, ge=0, le=23)
    minutes: Optional[int] = Field(default=0, ge=0, le=59)


class DependentReminderModeIn(BaseModel):
    link_id: int
    mode: Literal["once", "repeat"]
    hours: Optional[int] = Field(default=None, ge=0, le=23)
    minutes: Optional[int] = Field(default=0, ge=0, le=59)


class DependentStrictModeIn(BaseModel):
    link_id: int
    enabled: bool
    hours: Optional[int] = Field(default=None, ge=0, le=23)
    minutes: Optional[int] = Field(default=0, ge=0, le=59)


@router.get("")
async def get_settings(telegram_id: int = Depends(require_telegram_user)):
    row = await asyncio.to_thread(db.get_user_settings_row, telegram_id)
    if not row:
        return {}
    result = dict(row)
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    result["is_admin"] = bool(admin_id and telegram_id == admin_id)
    # F7: ensure caregiver code exists, then fetch link data
    code = await asyncio.to_thread(db.ensure_caregiver_code, telegram_id)
    result["caregiver_code"] = code
    links = await asyncio.to_thread(db.get_caregiver_links, telegram_id)
    result["pending_requests"] = links["pending_for_me"]
    result["active_caregiver"] = links["active_caregiver"]
    result["active_dependents"] = [l for l in links["as_caregiver"] if l["status"] == "active"]
    result["pending_sent"] = [l for l in links["as_caregiver"] if l["status"] == "pending"]
    # F8: dep shares
    dep_shares = await asyncio.to_thread(db.get_dep_shares_for_owner, telegram_id)
    result["dep_shares"] = {str(k): v for k, v in dep_shares.items()}
    viewing = await asyncio.to_thread(db.get_shared_deps_for_viewer, telegram_id)
    result["viewing_deps"] = [
        {
            "share_id": s["share_id"],
            "dep_id": s["dep_id"],
            "dep_name": s["dep_name"],
            "owner_username": s["owner_username"] or f"id{s['owner_telegram_id']}",
        }
        for s in viewing
    ]
    pending_viewing = await asyncio.to_thread(db.get_pending_viewing_deps, telegram_id)
    result["pending_viewing_deps"] = [
        {
            "share_id": s["share_id"],
            "dep_name": s["dep_name"],
            "owner_username": s["owner_username"] or f"id{s['owner_telegram_id']}",
        }
        for s in pending_viewing
    ]
    return result


@router.put("/timezone", status_code=204)
async def set_timezone(body: TimezoneIn, telegram_id: int = Depends(require_telegram_user)):
    try:
        pytz.timezone(body.timezone)
    except pytz.exceptions.UnknownTimeZoneError:
        raise HTTPException(400, "Неизвестный часовой пояс")
    await asyncio.to_thread(db.set_user_timezone, telegram_id, body.timezone)


@router.put("/timezone/by-location", status_code=204)
async def set_timezone_by_location(body: LocationIn, telegram_id: int = Depends(require_telegram_user)):
    tz = await asyncio.to_thread(_tf.timezone_at, lat=body.lat, lng=body.lng)
    if not tz:
        raise HTTPException(400, "Не удалось определить часовой пояс по координатам")
    await asyncio.to_thread(db.set_user_timezone, telegram_id, tz)


@router.put("/reminder-mode", status_code=204)
async def set_reminder_mode(body: ReminderModeIn, telegram_id: int = Depends(require_telegram_user)):
    if await asyncio.to_thread(db.is_active_dependent, telegram_id):
        raise HTTPException(403, "Помощник управляет этой настройкой")
    await asyncio.to_thread(db.set_reminder_mode, telegram_id, body.mode, body.hours, body.minutes or 0)


@router.put("/presets/{slot}", status_code=204)
async def set_preset(slot: str, body: PresetIn, telegram_id: int = Depends(require_telegram_user)):
    # SEC-4: неизвестный слот иначе уронил бы set_user_time_preset в 500.
    if slot not in SLOT_ORDER:
        raise HTTPException(400, "Неизвестный слот времени")
    await asyncio.to_thread(db.set_user_time_preset, telegram_id, slot, body.time)


@router.put("/daily-plan", status_code=204)
async def set_daily_plan(body: DailyPlanIn, telegram_id: int = Depends(require_telegram_user)):
    await asyncio.to_thread(db.set_daily_plan_enabled, telegram_id, body.enabled)
    if body.time:
        await asyncio.to_thread(db.set_daily_plan_time, telegram_id, body.time)


@router.put("/caregiver", status_code=204)
async def set_caregiver(body: CaregiverIn, telegram_id: int = Depends(require_telegram_user)):
    await asyncio.to_thread(db.set_caregiver_mode, telegram_id, body.enabled)


@router.put("/strict-mode", status_code=204)
async def set_strict_mode(body: StrictModeIn, telegram_id: int = Depends(require_telegram_user)):
    if await asyncio.to_thread(db.is_active_dependent, telegram_id):
        raise HTTPException(403, "Помощник управляет этой настройкой")
    await asyncio.to_thread(db.set_strict_mode, telegram_id, body.enabled, body.hours, body.minutes or 0)


@router.put("/dependent-reminder-mode", status_code=204)
async def set_dependent_reminder_mode(
    body: DependentReminderModeIn,
    telegram_id: int = Depends(require_telegram_user),
):
    ok = await asyncio.to_thread(
        db.set_dependent_settings, telegram_id, body.link_id,
        reminder_mode=body.mode, reminder_hours=body.hours, reminder_minutes=body.minutes or 0,
    )
    if not ok:
        raise HTTPException(403, "Нет активной связи с близким")


@router.put("/dependent-strict-mode", status_code=204)
async def set_dependent_strict_mode(
    body: DependentStrictModeIn,
    telegram_id: int = Depends(require_telegram_user),
):
    ok = await asyncio.to_thread(
        db.set_dependent_settings, telegram_id, body.link_id,
        strict_mode=body.enabled, strict_hours=body.hours, strict_minutes=body.minutes or 0,
    )
    if not ok:
        raise HTTPException(403, "Нет активной связи с близким")


@router.delete("/account", status_code=204)
async def delete_account(telegram_id: int = Depends(require_telegram_user)):
    await asyncio.to_thread(db.delete_user_data, telegram_id)
