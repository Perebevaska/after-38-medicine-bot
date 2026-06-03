import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
import database as db
from api.auth import require_telegram_user
from constants import MAX_DEPENDENTS, DEPENDENT_NAME_MAX_LEN

router = APIRouter(prefix="/dependents", tags=["dependents"])


class DependentIn(BaseModel):
    name: str = Field(min_length=1, max_length=DEPENDENT_NAME_MAX_LEN)

    @field_validator("name")
    @classmethod
    def _strip(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("имя не может быть пустым")
        return v


@router.get("")
async def list_dependents(telegram_id: int = Depends(require_telegram_user)):
    return await asyncio.to_thread(db.get_dependents, telegram_id)


@router.post("", status_code=201)
async def create_dependent(body: DependentIn, telegram_id: int = Depends(require_telegram_user)):
    # SEC-5: лимит числа подопечных — в боте он есть, в API не было (модифицированный
    # клиент мог создавать их без ограничений).
    # F7-3.4: лимит суммарный (локальные + linked)
    count = await asyncio.to_thread(db.count_total_dependents, telegram_id)
    if count >= MAX_DEPENDENTS:
        raise HTTPException(400, f"Лимит {MAX_DEPENDENTS} близких достигнут")
    dep_id = await asyncio.to_thread(db.add_dependent, telegram_id, body.name)
    return {"id": dep_id}


@router.delete("/{dep_id}", status_code=204)
async def delete_dependent(dep_id: int, telegram_id: int = Depends(require_telegram_user)):
    # F8: if dep has active viewer, transfer ownership instead of deleting
    transferred = await asyncio.to_thread(db.transfer_dep_to_viewer, telegram_id, dep_id)
    if transferred:
        return
    await asyncio.to_thread(db.delete_dependent, telegram_id, dep_id)
