import asyncio
import os
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

import database as db
from api.auth import require_telegram_user

router = APIRouter(prefix="/dependent-shares", tags=["dependent-shares"])

_DEP_SHARE_CODE_RE = re.compile(
    r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$"
)


class JoinRequest(BaseModel):
    code: str = Field(min_length=14, max_length=14)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not _DEP_SHARE_CODE_RE.match(v.upper()):
            raise ValueError("Неверный формат кода (ожидается XXXX-XXXX-XXXX)")
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


@router.post("/{dep_id}/code", status_code=200)
async def get_or_create_share_code(dep_id: int, telegram_id: int = Depends(require_telegram_user)):
    try:
        code = await asyncio.to_thread(db.ensure_dep_share_code, dep_id, telegram_id)
    except db.DatabaseError as e:
        raise HTTPException(404, str(e))
    return {"share_code": code}


@router.post("/join", status_code=201)
async def join_dep_share(body: JoinRequest, telegram_id: int = Depends(require_telegram_user)):
    try:
        result = await asyncio.to_thread(db.request_dep_share, telegram_id, body.code)
    except db.DatabaseError as e:
        raise HTTPException(400, str(e))
    asyncio.create_task(_bot_notify(
        result["owner_telegram_id"],
        f"Кто-то хочет наблюдать за «{result['dep_name']}».\n"
        f"Подтвердите в приложении в разделе Настройки → Забота."
    ))
    return {"ok": True}


@router.post("/{share_id}/confirm", status_code=200)
async def confirm_share(share_id: int, telegram_id: int = Depends(require_telegram_user)):
    try:
        result = await asyncio.to_thread(db.confirm_dep_share, share_id, telegram_id)
    except db.DatabaseError as e:
        raise HTTPException(400, str(e))
    if result.get("viewer_telegram_id"):
        asyncio.create_task(_bot_notify(
            result["viewer_telegram_id"],
            f"Доступ к «{result['dep_name']}» подтверждён. Откройте приложение."
        ))
    return {"ok": True}


@router.post("/{share_id}/decline", status_code=200)
async def decline_share(share_id: int, telegram_id: int = Depends(require_telegram_user)):
    ok = await asyncio.to_thread(db.decline_dep_share, share_id, telegram_id)
    if not ok:
        raise HTTPException(404, "Запрос не найден")
    return {"ok": True}


@router.delete("/{share_id}", status_code=204)
async def revoke_share(share_id: int, telegram_id: int = Depends(require_telegram_user)):
    ok = await asyncio.to_thread(db.revoke_dep_share, share_id, telegram_id)
    if not ok:
        raise HTTPException(404, "Не найдено")


@router.delete("/{share_id}/leave", status_code=204)
async def leave_share(share_id: int, telegram_id: int = Depends(require_telegram_user)):
    ok = await asyncio.to_thread(db.leave_dep_share, share_id, telegram_id)
    if not ok:
        raise HTTPException(404, "Не найдено")
