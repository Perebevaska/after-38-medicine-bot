import asyncio
from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
import database as db
from constants import MAX_MEDICATIONS_PER_USER
from api.auth import require_db_user, TelegramUser
from utils import parse_time, NAME_MAX_LEN, DOSAGE_MAX_LEN

# SEC-2: верхняя граница числа правил на лекарство — иначе модифицированный
# клиент мог бы вставить тысячи schedule_rules одним запросом (DoS/раздувание).
MAX_RULES_PER_MED = 24

router = APIRouter(prefix="/medications", tags=["medications"])

_MealRelation = Literal["before", "after", "with", "any"]
_Frequency = Literal["daily", "interval", "weekdays", "monthly"]


class RuleIn(BaseModel):
    reminder_time: str
    frequency: _Frequency = "daily"
    interval_days: Optional[int] = Field(default=None, ge=1, le=3650)
    weekdays: Optional[str] = None
    month_day: Optional[int] = None
    anchor_date: Optional[str] = None
    dosage: Optional[str] = Field(default=None, max_length=DOSAGE_MAX_LEN)

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


_MAX_DOSE = 1_000_000


def _assert_unique_rules(rules: list[RuleIn]):
    """Запрет дублей: два одинаковых приёма схлопываются в один слот
    (UNIQUE intake_log по (medication_id, reminder_time, день)) и тикаются разом."""
    seen = set()
    for r in rules:
        key = (r.reminder_time, r.frequency, r.interval_days, r.weekdays,
               r.month_day, r.anchor_date)
        if key in seen:
            raise ValueError("Нельзя добавить два одинаковых приёма на одно и то же время")
        seen.add(key)


class _PackageFields(BaseModel):
    """Новая модель упаковки/курса (A1): дозировка 1 ед., назначенная доза, запас, курс."""
    unit_dose_value: Optional[float] = Field(default=None, gt=0, le=_MAX_DOSE)
    unit_dose_label: str = Field(default="мг", max_length=16)
    dose_per_intake: Optional[float] = Field(default=None, gt=0, le=_MAX_DOSE)
    pack_size: Optional[float] = Field(default=None, ge=0, le=_MAX_DOSE)
    course_total: Optional[int] = Field(default=None, ge=1, le=100_000)


class MedicationIn(_PackageFields):
    name: str = Field(min_length=1, max_length=NAME_MAX_LEN)
    dosage: str = Field(max_length=DOSAGE_MAX_LEN)
    meal_relation: _MealRelation
    times_per_day: int = Field(ge=1, le=24)
    dependent_id: Optional[int] = None
    for_linked_user_id: Optional[int] = None  # F7: user_id linked dependent
    for_dep_share_id: Optional[int] = None    # F8: share_id viewer → shared dep
    rules: list[RuleIn] = Field(default_factory=list, max_length=MAX_RULES_PER_MED)

    @model_validator(mode="after")
    def _v_unique_rules(self):
        _assert_unique_rules(self.rules)
        return self


class MedicationUpdate(_PackageFields):
    name: str = Field(min_length=1, max_length=NAME_MAX_LEN)
    dosage: str = Field(max_length=DOSAGE_MAX_LEN)
    meal_relation: _MealRelation
    times_per_day: int = Field(ge=1, le=24)
    rules: list[RuleIn] = Field(default_factory=list, max_length=MAX_RULES_PER_MED)

    @model_validator(mode="after")
    def _v_unique_rules(self):
        _assert_unique_rules(self.rules)
        return self


@router.get("")
async def list_medications(user: TelegramUser = Depends(require_db_user)):
    meds = await asyncio.to_thread(db.get_user_medications, user.user_id)
    rules = await asyncio.to_thread(db.get_rules_grouped_for_user, user.user_id)
    result = [{**dict(m), "rules": [dict(r) for r in rules.get(m["id"], [])]} for m in meds]
    # F7: include linked dependents' medications
    linked = await asyncio.to_thread(db.get_linked_dependents_for_caregiver, user.telegram_id)
    for dep in linked:
        dep_uid = dep["user_id"]
        dep_meds = await asyncio.to_thread(db.get_user_medications, dep_uid)
        dep_rules = await asyncio.to_thread(db.get_rules_grouped_for_user, dep_uid)
        dep_name = dep["username"] or f"id{dep['telegram_id']}"
        for m in dep_meds:
            # F7-fix: помощник видит только собственные лекарства подопечного,
            # НЕ его локальных близких (dependent_id IS NULL).
            if m["dependent_id"] is not None:
                continue
            result.append({
                **dict(m),
                "rules": [dict(r) for r in dep_rules.get(m["id"], [])],
                "linked_user_id": dep_uid,
                "linked_user_name": dep_name,
            })
    # F8: include shared deps' medications (viewer has CRUD access)
    viewer_deps = await asyncio.to_thread(db.get_viewer_shared_deps, user.user_id)
    for vd in viewer_deps:
        dep_meds = await asyncio.to_thread(db.get_medications_for_dep, vd["dep_id"])
        dep_rules = await asyncio.to_thread(db.get_rules_grouped_for_dep, vd["dep_id"])
        for m in dep_meds:
            result.append({
                **dict(m),
                "rules": [dict(r) for r in dep_rules.get(m["id"], [])],
                "dep_share_id": vd["share_id"],
                "dep_share_name": vd["dep_name"],
            })
    # A1: прогресс курса — только для лекарств с заданным course_total
    # (запрос на лекарство, но таких единицы). course_done ≥ course_total → курс завершён.
    for entry in result:
        if entry.get("course_total"):
            entry["course_done"] = await asyncio.to_thread(db.get_course_progress, entry["id"])
    return result


@router.post("", status_code=201)
async def create_medication(body: MedicationIn, user: TelegramUser = Depends(require_db_user)):
    # F8: creating med for a shared (viewer) dep
    if body.for_dep_share_id is not None:
        viewer_deps = await asyncio.to_thread(db.get_viewer_shared_deps, user.user_id)
        vd = next((d for d in viewer_deps if d["share_id"] == body.for_dep_share_id), None)
        if not vd:
            raise HTTPException(403, "Нет активного доступа к этому близкому")
        target_user_id = vd["owner_user_id"]
        dep_id = vd["dep_id"]
    # F7: creating med for a linked dependent
    elif body.for_linked_user_id is not None:
        ok = await asyncio.to_thread(
            db.is_caregiver_for_user_id, user.telegram_id, body.for_linked_user_id
        )
        if not ok:
            raise HTTPException(403, "Нет активной связи с этим близким")
        target_user_id = body.for_linked_user_id
        dep_id = None
    else:
        # S2: dependent_id приходит от клиента — проверяем владельца.
        if body.dependent_id is not None:
            deps = await asyncio.to_thread(db.get_dependents, user.telegram_id)
            if body.dependent_id not in {d["id"] for d in deps}:
                raise HTTPException(404, "Близкий не найден")
        target_user_id = user.user_id
        dep_id = body.dependent_id
    count = await asyncio.to_thread(db.count_active_medications, target_user_id, dep_id)
    if count >= MAX_MEDICATIONS_PER_USER:
        raise HTTPException(400, f"Лимит {MAX_MEDICATIONS_PER_USER} препаратов достигнут")
    med_id = await asyncio.to_thread(
        db.add_medication, target_user_id, body.name, body.dosage,
        body.meal_relation, body.times_per_day, dep_id,
        unit_dose_value=body.unit_dose_value, unit_dose_label=body.unit_dose_label,
        dose_per_intake=body.dose_per_intake, pack_size=body.pack_size,
        course_total=body.course_total,
    )
    for rule in body.rules:
        await asyncio.to_thread(
            db.add_schedule_rule, med_id, rule.reminder_time, rule.frequency,
            rule.interval_days, rule.weekdays, rule.month_day,
            rule.anchor_date, rule.dosage,
        )
    return {"id": med_id}


async def _resolve_med(med_id: int, user: TelegramUser):
    """Returns med_row. Allows caregiver (F7) and viewer of shared dep (F8) to manage meds."""
    linked = await asyncio.to_thread(db.get_linked_dependents_for_caregiver, user.telegram_id)
    allowed_ids = [user.user_id] + [d["user_id"] for d in linked]
    med = await asyncio.to_thread(db.get_medication_by_id_any_user, med_id, allowed_ids)
    if med:
        return med
    # F8: check if med belongs to a shared dep the user is viewing
    viewer_deps = await asyncio.to_thread(db.get_viewer_shared_deps, user.user_id)
    if viewer_deps:
        viewer_dep_ids = {vd["dep_id"] for vd in viewer_deps}
        med = await asyncio.to_thread(db.get_medication_by_id_raw, med_id)
        if med and med.get("dependent_id") in viewer_dep_ids:
            return med
    raise HTTPException(404, "Препарат не найден")


@router.put("/{med_id}")
async def update_medication(
    med_id: int, body: MedicationUpdate,
    user: TelegramUser = Depends(require_db_user),
):
    med = await _resolve_med(med_id, user)
    await asyncio.to_thread(
        db.update_medication, med_id, med["user_id"],
        body.name, body.dosage, body.meal_relation, body.times_per_day,
        [r.model_dump() for r in body.rules],
        unit_dose_value=body.unit_dose_value, unit_dose_label=body.unit_dose_label,
        dose_per_intake=body.dose_per_intake, pack_size=body.pack_size,
        course_total=body.course_total,
    )
    return {"ok": True}


@router.delete("/{med_id}", status_code=204)
async def delete_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    med = await _resolve_med(med_id, user)
    await asyncio.to_thread(db.deactivate_medication, med_id, med["user_id"])


@router.post("/{med_id}/course/continue", status_code=204)
async def continue_course(med_id: int, user: TelegramUser = Depends(require_db_user)):
    """Продолжить завершённый курс: снять лимит course_total (приёмы идут дальше)."""
    med = await _resolve_med(med_id, user)
    await asyncio.to_thread(db.set_course_total, med_id, med["user_id"], None)


@router.post("/{med_id}/pause", status_code=204)
async def pause_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    med = await _resolve_med(med_id, user)
    await asyncio.to_thread(db.set_medication_paused, med_id, med["user_id"], True)


@router.post("/{med_id}/resume", status_code=204)
async def resume_medication(med_id: int, user: TelegramUser = Depends(require_db_user)):
    med = await _resolve_med(med_id, user)
    await asyncio.to_thread(db.set_medication_paused, med_id, med["user_id"], False)
