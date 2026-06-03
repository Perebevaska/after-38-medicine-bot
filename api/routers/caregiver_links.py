import asyncio
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

import database as db
from api.auth import require_telegram_user

router = APIRouter(prefix="/caregiver-links", tags=["caregiver-links"])

_CODE_RE = re.compile(r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")


class LinkRequest(BaseModel):
    code: str = Field(min_length=9, max_length=9)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not _CODE_RE.match(v.upper()):
            raise ValueError("Неверный формат кода (ожидается XXXX-XXXX)")
        return v.upper()


async def _bot_notify(chat_id: int, text: str):
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
    except Exception:
        pass


@router.get("")
async def get_links(telegram_id: int = Depends(require_telegram_user)):
    return await asyncio.to_thread(db.get_caregiver_links, telegram_id)


@router.post("", status_code=201)
async def create_link(body: LinkRequest, telegram_id: int = Depends(require_telegram_user)):
    # F7-3.5: подопечный не может одновременно быть опекуном
    if await asyncio.to_thread(db.is_active_dependent, telegram_id):
        raise HTTPException(403, "Близкий не может привязывать других близких")
    try:
        result = await asyncio.to_thread(db.create_caregiver_link, telegram_id, body.code)
    except db.DatabaseError as e:
        raise HTTPException(400, str(e))
    await _bot_notify(
        result["dependent_telegram_id"],
        "👨‍👩‍👦 Вам поступил запрос на подключение помощника.\n"
        "Откройте приложение, чтобы принять или отклонить.",
    )
    return {"id": result["id"]}


@router.post("/{link_id}/confirm", status_code=204)
async def confirm_link(link_id: int, telegram_id: int = Depends(require_telegram_user)):
    result = await asyncio.to_thread(db.confirm_caregiver_link, link_id, telegram_id)
    if result == "not_found":
        raise HTTPException(404, "Запрос не найден или уже обработан")
    if result == "limit":
        raise HTTPException(400, "Лимит близких достигнут (максимум 2)")


@router.post("/{link_id}/decline", status_code=204)
async def decline_link(link_id: int, telegram_id: int = Depends(require_telegram_user)):
    ok = await asyncio.to_thread(db.decline_caregiver_link, link_id, telegram_id)
    if not ok:
        raise HTTPException(404, "Запрос не найден или уже обработан")


@router.post("/{link_id}/request-break", status_code=204)
async def request_break(link_id: int, telegram_id: int = Depends(require_telegram_user)):
    """Подопечный запрашивает разрыв связи. Опекун подтверждает через DELETE."""
    ok = await asyncio.to_thread(db.request_caregiver_link_break, link_id, telegram_id)
    if not ok:
        raise HTTPException(404, "Активная связь не найдена")
    # Notify caregiver
    links = await asyncio.to_thread(db.get_caregiver_links, telegram_id)
    active = links.get("active_caregiver")
    if active:
        care_tid = active.get("caregiver_telegram_id")
        if care_tid:
            await _bot_notify(
                care_tid,
                "⚠️ Близкий хочет отключиться. "
                "Откройте приложение → Настройки → Забота для подтверждения.",
            )


@router.delete("/{link_id}", status_code=204)
async def delete_link(link_id: int, telegram_id: int = Depends(require_telegram_user)):
    ok = await asyncio.to_thread(db.delete_caregiver_link, link_id, telegram_id)
    if not ok:
        raise HTTPException(403, "Только помощник может разорвать связь")
