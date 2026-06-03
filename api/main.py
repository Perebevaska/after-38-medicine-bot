"""FastAPI-приложение Med Bot API.

Запуск (из корня проекта):
    uvicorn api.main:app --reload

⚠️ APScheduler запускается только в bot.py — здесь не стартуем,
   иначе будут дубли напоминаний.
"""
import asyncio
import logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

import uuid
import redis as _redis_lib
import redis.asyncio as _aioredis
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import database as _db
from database import init_pool, close_pool, get_connection, migrate

logger = logging.getLogger("api")

# ── Rate limiting ────────────────────────────────────────────────────────────

_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
# За обратным прокси (Caddy) реальный IP — в X-Forwarded-For. Включать только
# если прокси доверенный, иначе клиент может подделать заголовок.
_TRUST_PROXY = os.getenv("TRUST_PROXY", "").lower() in ("1", "true", "yes")
_RATE_MSG = "Притормози чуть-чуть — слишком много запросов сразу 🙂"

# AX7: лимит в Redis (sliding window через sorted set) — работает при >1 воркера
# uvicorn (per-process dict не делил состояние). Fallback на in-memory при сбое Redis.
_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
_redis_rl = None
_counters: dict[str, list[float]] = defaultdict(list)
_sweep_counter = 0


def _get_redis():
    global _redis_rl
    if _redis_rl is None:
        _redis_rl = _aioredis.from_url(_REDIS_URL)
    return _redis_rl


def _client_ip(request: Request) -> str:
    if _TRUST_PROXY:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _redis_allowed(ip: str, now: float) -> bool:
    """Sliding window в Redis: чистим окно, добавляем текущий хит, считаем."""
    r = _get_redis()
    key = f"ratelimit:{ip}"
    async with r.pipeline(transaction=True) as p:
        p.zremrangebyscore(key, 0, now - 60.0)
        p.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
        p.zcard(key)
        p.expire(key, 60)
        res = await p.execute()
    return res[2] <= _RATE_LIMIT


def _memory_allowed(ip: str, now: float) -> bool:
    """Fallback per-process (если Redis недоступен)."""
    global _sweep_counter
    hits = [t for t in _counters[ip] if now - t < 60.0]
    if len(hits) >= _RATE_LIMIT:
        _counters[ip] = hits
        return False
    hits.append(now)
    _counters[ip] = hits
    _sweep_counter += 1
    if _sweep_counter % 1000 == 0:
        for k in [k for k, v in _counters.items()
                  if not v or all(now - t >= 60.0 for t in v)]:
            _counters.pop(k, None)
    return True


class _RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = _client_ip(request)
        now = time.time()
        try:
            allowed = await _redis_allowed(ip, now)
        except Exception as e:
            logger.warning("rate limit: Redis недоступен, fallback in-memory: %s", e)
            allowed = _memory_allowed(ip, now)
        if not allowed:
            return JSONResponse({"detail": _RATE_MSG}, status_code=429)
        return await call_next(request)


# ── App ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    owned = _db._pool is None   # не закрывать пул, если он создан снаружи (тесты)
    init_pool()
    # API не должен зависеть от того, что bot.py уже выполнил миграцию: гонять
    # её здесь тоже (идемпотентно — ADD COLUMN IF NOT EXISTS / индексы). Иначе
    # при рассинхроне рестартов API стучится в несуществующие колонки (500).
    try:
        await asyncio.to_thread(migrate)
    except Exception as e:
        logger.warning("migrate в API lifespan не выполнен: %s", e)
    yield
    if owned:
        close_pool()


app = FastAPI(title="Med Bot API", version="1.0.0", lifespan=lifespan)

# CORS: MINIAPP_ORIGIN через запятую, по умолчанию — все (только для dev)
_cors_origins = [o.strip() for o in os.getenv("MINIAPP_ORIGIN", "*").split(",")]
_allow_credentials = _cors_origins != ["*"]
if _cors_origins == ["*"]:
    # S5: fail-open по умолчанию — в проде обязательно задавать MINIAPP_ORIGIN.
    logger.warning(
        "CORS открыт для всех источников (MINIAPP_ORIGIN не задан). "
        "Для продакшена укажите конкретный домен Mini App."
    )

app.add_middleware(_RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Exception handlers ───────────────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    """Нормализует 422: detail всегда строка, а не список."""
    parts = []
    for e in exc.errors():
        loc = ".".join(str(l) for l in e["loc"] if l != "body")
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return JSONResponse({"detail": "; ".join(parts)}, status_code=422)

# ── Routers ──────────────────────────────────────────────────────────────────

from api.routers import medications, today, stats, stock, dependents, settings, export, admin

app.include_router(medications.router)
app.include_router(today.router)
app.include_router(stats.router)
app.include_router(stock.router)
app.include_router(dependents.router)
app.include_router(settings.router)
app.include_router(export.router)
app.include_router(admin.router)


@app.get("/health")
async def health(response: Response):
    checks: dict[str, str] = {}

    def _db_check():
        with get_connection() as conn:
            conn.execute("SELECT 1")

    def _redis_check():
        _redis_lib.from_url(_REDIS_URL).ping()

    try:
        await asyncio.to_thread(_db_check)
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    try:
        await asyncio.to_thread(_redis_check)
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", **checks}
