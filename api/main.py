"""FastAPI-приложение Med Bot API.

Запуск (из корня проекта):
    uvicorn api.main:app --reload

⚠️ APScheduler запускается только в bot.py — здесь не стартуем,
   иначе будут дубли напоминаний.
"""
import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from database import init_pool, close_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    yield
    close_pool()


app = FastAPI(
    title="Med Bot API",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}
