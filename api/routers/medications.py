import asyncio
from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator, model_validator
import database as db
from api.auth import require_db_user, TelegramUser
from constants import MAX_MEDICATIONS_PER_USER
from utils import parse_time

router = APIRouter(prefix="/medications", tags=["medications"])

_MealRelation = Literal["before", "after", "with", "any"]
_Frequency = Literal["daily", "interval", "weekdays", "monthly"]


class RuleIn(BaseModel):
    reminder_time: str
    frequency: _Frequency = "daily"
    interval_days: Optional[int] = None
    weekdays: Optional[str] = None
    month_day: Optional[int] = None
    anchor_date: Optional[str] = None
    dosage: Optional[str] = None

    # B5: серверная валидация полей правила (бот валидирует свои пути сам;
    # тут защищаем API/Mini App от некорректных правил, которые ломают аналитику).
    @field_validator("reminder_time")
    @classmethod
    def _v_time(cls, v):
        try:
            return parse_time(v)
        except (ValueError, AttributeError, TypeError):
            raise ValueError("reminder_time должен быть в формате ЧЧ:ММ")

    @field_validator("month_day")
    @classmethod
    def _v_month_day(cls, v):
        if v is not None and not (1 <= v <= 31):
            raise ValueError("month_day должен быть в диапазоне 1..31")
        return v

    @field_validator("interval_days")
    @classmethod
    def _v_interval(cls, v):
        if v is not None and v <= 0:
            raise ValueError("interval_days должен быть > 0")
        return v

    @field_validator("weekdays")
    @classmethod
    def _v_weekdays(cls, v):
        if v is None:
            return v
        try:
            days = [int(x) for x in v.split(",") if x.strip()]
        except ValueError:
            raise ValueError("weekdays: числа 1..7 через запятую")
        if not days or any(not (1 <= d <= 7) for d in days):
            raise ValueError("weekdays: числа 1..7 через запятую")
        return v

    @field_validator("anchor_date")
    @classmethod
    def _v_anchor(cls, v):
        if v is None:
            return v
        try:
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("anchor_date: формат YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def _v_freq_fields(self):
        if self.frequency == "interval" and (not self.interval_days or not self.anchor_date):
            raise ValueError("frequency=interval требует interval_days > 0 и anchor_date")
        if self.frequency == "weekdays" and not self.weekdays:
            raise ValueError("frequency=weekdays требует поле weekdays")
        if self.frequency == "monthly" and not self.month_day:
            raise ValueError("frequency=monthly требует month_day")
        return self


class MedicationIn(BaseModel):
    name: str
    dosage: str
    meal_relation: _MealRelation
    times_per_day: int
    dependent_id: Optional[int] = None
    rules: list[RuleIn]


class MedicationUpdate(BaseModel):
    name: str
    dosage: str
    meal_relation: _MealRelation
    times_per_day: int
    rules: list[RuleIn]


@router.get("")
async def list_medications(user: TelegramUser = Depends(require_db_user)):
    meds = await asyncio.to_thread(db.get_user_medications, user.user_id)
    rules = await asyncio.to_thread(db.get_rules_grouped_for_user, user.user_id)
    return [
        {**dict(m), "rules": [dict(r) for r in rules.get(m["id"], [])]}
        for m in meds
    ]


@router.post("", status_code=201)
async def create_medication(body: MedicationIn, user: TelegramUser = Depends(require_db_user)):
    # S2: dependent_id приходит от клиента — проверяем владельца, иначе лекарство
    # можно привязать к чужому подопечному.
    if body.dependent_id is not None:
        deps = await asyncio.to_thread(db.get_dependents, user.telegram_id)
        if body.dependent_id not in {d["id"] for d in deps}:
            raise HTTPException(404, "Подопечный не найден")
    count = await asyncio.to_thread(db.count_active_medications, user.user_id, body.dependent_id)
    if count >= MAX_MEDICATIONS_PER_USER:
        raise HTTPException(400, f"Лимит {MAX_MEDICATIONS_PER_USER} лекарств достигнут")
    med_id = await asyncio.to_thread(
        db.add_medication, user.user_id, body.name, body.dosage,
        body.meal_relation, body.times_per_day, body.dependent_id,
    )
    for rule in body.rules:
        await asyncio.to_thread(
            db.add_schedule_rule, med_id, rule.reminder_time, rule.frequency,
            rule.interval_days, rule.weekdays, rule.month_day,
            rule.anchor_date, rule.dosage,
        )
    return {"id": med_id}


@router.put("/{med_id}")
async def update_medication(
    med_id: int, body: MedicationUpdate,
    user: TelegramUser = Depends(require_db_user),
):
    if not await asyncio.to_thread(db.get_medication_by_id, med_id, user.user_id):
        raise HTTPException(404, "Лекарство не найдено")
    await asyncio.to_thread(
        db.update_medication, med_id, user.user_id,
        body.name, body.dosage, body.meal_relation, body.times_per_day,
        [r.model_dump() for r in body.rules],
    )
    return {"ok": True}


@router.delete("/{med_id}", status_code=204)
async def delete_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    if not await asyncio.to_thread(db.get_medication_by_id, med_id, user.user_id):
        raise HTTPException(404, "Лекарство не найдено")
    await asyncio.to_thread(db.deactivate_medication, med_id, user.user_id)


@router.post("/{med_id}/pause", status_code=204)
async def pause_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    if not await asyncio.to_thread(db.get_medication_by_id, med_id, user.user_id):
        raise HTTPException(404, "Лекарство не найдено")
    await asyncio.to_thread(db.set_medication_paused, med_id, user.user_id, True)


@router.post("/{med_id}/resume", status_code=204)
async def resume_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    if not await asyncio.to_thread(db.get_medication_by_id, med_id, user.user_id):
        raise HTTPException(404, "Лекарство не найдено")
    await asyncio.to_thread(db.set_medication_paused, med_id, user.user_id, False)
