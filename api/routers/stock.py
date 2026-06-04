import asyncio
import math
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
import database as db
from api.auth import require_db_user, TelegramUser
from schedule_utils import days_of_stock_left
from datetime import date

router = APIRouter(prefix="/medications", tags=["stock"])

# SEC-3: верхняя граница на величины запаса — отсекаем абсурдные значения,
# которые ломали бы прогноз days_of_stock_left / PDF.
_MAX_QTY = 1_000_000


def _finite(v: float) -> float:
    """Отклоняет NaN/inf — иначе расчёты запаса/PDF дают мусор или падают."""
    if not math.isfinite(v):
        raise ValueError("значение должно быть конечным числом")
    return v


class StockSet(BaseModel):
    qty: float = Field(ge=0, le=_MAX_QTY)
    _v = field_validator("qty")(_finite)


class StockAdd(BaseModel):
    amount: float = Field(gt=0, le=_MAX_QTY)
    _v = field_validator("amount")(_finite)


class UnitsSet(BaseModel):
    units: float = Field(gt=0, le=10_000)
    _v = field_validator("units")(_finite)


class ThresholdSet(BaseModel):
    days: int = Field(ge=1, le=3650)


async def _get_med_or_404(med_id: int, user_id: int):
    med = await asyncio.to_thread(db.get_medication_by_id, med_id, user_id)
    if not med:
        raise HTTPException(404, "Препарат не найден")
    return med


@router.get("/{med_id}/stock")
async def get_stock(med_id: int, user: TelegramUser = Depends(require_db_user)):
    med = await _get_med_or_404(med_id, user.user_id)
    rules = await asyncio.to_thread(db.get_schedules_by_medication, med_id)
    days_left = (
        days_of_stock_left(rules, med["stock_qty"], med["units_per_dose"], date.today())
        if med["stock_qty"] is not None else None
    )
    return {
        "stock_qty": med["stock_qty"],
        "units_per_dose": med["units_per_dose"],
        "low_stock_days": med["low_stock_days"],
        "days_left": days_left,
    }


@router.put("/{med_id}/stock", status_code=204)
async def set_stock(med_id: int, body: StockSet, user: TelegramUser = Depends(require_db_user)):
    await _get_med_or_404(med_id, user.user_id)
    await asyncio.to_thread(db.set_medication_stock, med_id, user.user_id, body.qty)


@router.post("/{med_id}/stock/add", status_code=204)
async def add_stock(med_id: int, body: StockAdd, user: TelegramUser = Depends(require_db_user)):
    await _get_med_or_404(med_id, user.user_id)
    await asyncio.to_thread(db.add_medication_stock, med_id, user.user_id, body.amount)


@router.put("/{med_id}/stock/units", status_code=204)
async def set_units(med_id: int, body: UnitsSet, user: TelegramUser = Depends(require_db_user)):
    await _get_med_or_404(med_id, user.user_id)
    await asyncio.to_thread(db.set_units_per_dose, med_id, user.user_id, body.units)


@router.put("/{med_id}/stock/threshold", status_code=204)
async def set_threshold(med_id: int, body: ThresholdSet, user: TelegramUser = Depends(require_db_user)):
    await _get_med_or_404(med_id, user.user_id)
    await asyncio.to_thread(db.set_low_stock_days, med_id, user.user_id, body.days)


@router.delete("/{med_id}/stock", status_code=204)
async def disable_stock(med_id: int, user: TelegramUser = Depends(require_db_user)):
    await _get_med_or_404(med_id, user.user_id)
    await asyncio.to_thread(db.disable_stock_tracking, med_id, user.user_id)
