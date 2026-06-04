import asyncio
import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from api.auth import require_telegram_user
from reports import (
    build_plan_pdf, build_week_stats_pdf,
    build_adherence_pdf, build_doctor_pdf,
)

router = APIRouter(prefix="/export", tags=["export"])

_BUILDERS = {
    "plan":      (build_plan_pdf,      "plan_week.pdf",      None),
    "week":      (build_week_stats_pdf, "history_week.pdf",  None),
    "adherence": (build_adherence_pdf,  "adherence.pdf",     None),
    "doctor":    (None,                 "doctor_report.pdf", True),   # needs label
}

_CAPTIONS = {
    "plan":      "📋 Расписание приёмов на неделю",
    "week":      "📅 История приёмов за 7 дней",
    "adherence": "📊 Соблюдение режима за 30 дней",
    "doctor":    "🩺 Отчёт для врача",
}


def _stream(buf, filename: str):
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _build(slot: str, telegram_id: int):
    if slot == "plan":
        return await asyncio.to_thread(build_plan_pdf, telegram_id)
    if slot == "week":
        return await asyncio.to_thread(build_week_stats_pdf, telegram_id)
    if slot == "adherence":
        return await asyncio.to_thread(build_adherence_pdf, telegram_id)
    if slot == "doctor":
        return await asyncio.to_thread(build_doctor_pdf, telegram_id, f"user_{telegram_id}")
    return None


@router.get("/plan")
async def export_plan(telegram_id: int = Depends(require_telegram_user)):
    buf = await _build("plan", telegram_id)
    if not buf:
        raise HTTPException(404, "Нет данных для экспорта")
    return _stream(buf, "plan_week.pdf")


@router.get("/week")
async def export_week(telegram_id: int = Depends(require_telegram_user)):
    buf = await _build("week", telegram_id)
    if not buf:
        raise HTTPException(404, "Нет данных за последние 7 дней")
    return _stream(buf, "history_week.pdf")


@router.get("/adherence")
async def export_adherence_pdf(telegram_id: int = Depends(require_telegram_user)):
    buf = await _build("adherence", telegram_id)
    if not buf:
        raise HTTPException(404, "Нет активных препаратов")
    return _stream(buf, "adherence.pdf")


@router.get("/doctor")
async def export_doctor(telegram_id: int = Depends(require_telegram_user)):
    buf = await _build("doctor", telegram_id)
    if not buf:
        raise HTTPException(404, "Нет данных для отчёта")
    return _stream(buf, "doctor_report.pdf")


@router.post("/{slot}/send", status_code=204)
async def send_export_to_telegram(slot: str, telegram_id: int = Depends(require_telegram_user)):
    if slot not in _CAPTIONS:
        raise HTTPException(404, "Неизвестный тип отчёта")

    token = os.getenv("BOT_TOKEN")
    if not token:
        raise HTTPException(503, "Бот недоступен")

    buf = await _build(slot, telegram_id)
    if not buf:
        raise HTTPException(404, "Нет данных для отчёта")

    buf.seek(0)
    filename = _BUILDERS[slot][1]
    caption = _CAPTIONS[slot]

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={"chat_id": telegram_id, "caption": caption},
            files={"document": (filename, buf.read(), "application/pdf")},
        )

    if not resp.is_success:
        raise HTTPException(502, "Ошибка отправки через Telegram")
