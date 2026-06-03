import asyncio
import os
import subprocess

import psutil
import redis as _redis_lib
from fastapi import APIRouter, Depends, HTTPException

import database as db
from api.auth import require_telegram_user
from database import get_connection

router = APIRouter(prefix="/admin", tags=["admin"])

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


def _require_admin(telegram_id: int = Depends(require_telegram_user)) -> int:
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    if not admin_id or telegram_id != admin_id:
        raise HTTPException(403, "Forbidden")
    return telegram_id


def _collect_system() -> dict:
    cpu_pct = psutil.cpu_percent(interval=0.2)
    load1, load5, load15 = psutil.getloadavg()
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage("/")
    cpu_count = psutil.cpu_count(logical=True) or 1
    return {
        "cpu_pct": round(cpu_pct, 1),
        "cpu_count": cpu_count,
        "load_1m": round(load1, 2),
        "ram_used_mb": mem.used // (1024 * 1024),
        "ram_total_mb": mem.total // (1024 * 1024),
        "ram_pct": mem.percent,
        "swap_used_mb": swap.used // (1024 * 1024),
        "swap_total_mb": swap.total // (1024 * 1024),
        "swap_pct": swap.percent,
        "disk_used_gb": round(disk.used / (1024 ** 3), 1),
        "disk_free_gb": round(disk.free / (1024 ** 3), 1),
        "disk_total_gb": round(disk.total / (1024 ** 3), 1),
        "disk_pct": disk.percent,
    }


def _collect_redis() -> dict:
    r = _redis_lib.from_url(_REDIS_URL)
    info = r.info("memory")
    clients = r.info("clients")
    arq_queue_len = r.llen("arq:queue:default")
    return {
        "redis_mem": info.get("used_memory_human", "?"),
        "redis_clients": clients.get("connected_clients", "?"),
        "arq_queue": arq_queue_len,
    }


_SYSTEMD_SERVICES = [
    ("medbot-bot",    "Bot"),
    ("medbot-api",    "API"),
    ("medbot-worker", "Worker"),
    ("caddy",         "Caddy"),
    ("postgresql@16-main", "PostgreSQL"),
    ("redis-server",  "Redis"),
]


def _collect_services() -> list:
    result = []
    for unit, label in _SYSTEMD_SERVICES:
        try:
            r = subprocess.run(
                ["systemctl", "is-active", unit],
                capture_output=True, text=True, timeout=3
            )
            status = r.stdout.strip()
        except Exception:
            status = "unknown"
        result.append({"name": label, "unit": unit, "status": status})
    return result


def _collect_db_pool() -> dict:
    pool = db._pool
    if pool is None:
        return {"db_pool": None}
    stats = pool.get_stats()
    return {
        "db_pool_size": stats.get("pool_size", "?"),
        "db_pool_available": stats.get("pool_available", "?"),
        "db_pool_requests": stats.get("requests_waiting", "?"),
    }


@router.get("/stats")
async def admin_stats(_: int = Depends(_require_admin)):
    def _db_check():
        with get_connection() as conn:
            conn.execute("SELECT 1")

    db_status = redis_status = "ok"
    redis_extra: dict = {}
    try:
        await asyncio.to_thread(_db_check)
    except Exception as e:
        db_status = f"error: {e}"

    try:
        redis_extra = await asyncio.to_thread(_collect_redis)
    except Exception as e:
        redis_status = f"error: {e}"

    system, app_stats, pool_stats, services = await asyncio.gather(
        asyncio.to_thread(_collect_system),
        asyncio.to_thread(db.get_admin_stats),
        asyncio.to_thread(_collect_db_pool),
        asyncio.to_thread(_collect_services),
    )

    return {
        "db": db_status,
        "redis": redis_status,
        **redis_extra,
        **system,
        **app_stats,
        **pool_stats,
        "services": services,
    }
