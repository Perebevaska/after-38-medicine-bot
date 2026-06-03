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
    hours: Optional[int] = Field(default=None, ge=1, le=12)


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
    hours: Optional[int] = Field(default=None, ge=1, le=24)


@router.get("")
async def get_settings(telegram_id: int = Depends(require_telegram_user)):
    row = await asyncio.to_thread(db.get_user_settings_row, telegram_id)
    if not row:
        return {}
    result = dict(row)
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    result["is_admin"] = bool(admin_id and telegram_id == admin_id)
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
    await asyncio.to_thread(db.set_reminder_mode, telegram_id, body.mode, body.hours)


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
    await asyncio.to_thread(db.set_strict_mode, telegram_id, body.enabled, body.hours)


@router.delete("/account", status_code=204)
async def delete_account(telegram_id: int = Depends(require_telegram_user)):
    await asyncio.to_thread(db.delete_user_data, telegram_id)
