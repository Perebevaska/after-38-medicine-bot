"""Общие фикстуры для DB-тестов и API-тестов на PostgreSQL."""
import os
import pytest

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "postgresql://medbot:medbot@127.0.0.1/medbot_test")
TEST_TELEGRAM_ID = 77001

# Устанавливаем env vars до любых импортов database/api
os.environ.setdefault("DATABASE_URL", TEST_DSN)
os.environ.setdefault("BOT_TOKEN", "test-bot-token-1234567890")
os.environ.setdefault("MINIAPP_ORIGIN", "*")


@pytest.fixture(scope="session", autouse=True)
def _pg_schema():
    """Сессионная инициализация: пул + схема. Запускается один раз на всю сессию."""
    import database as d
    d.init_pool(TEST_DSN)
    d.init_db()
    d.migrate()
    yield
    d.close_pool()


@pytest.fixture
def db(_pg_schema):
    """Функциональная фикстура: чистит все таблицы перед каждым тестом."""
    import database as d
    with d.get_connection() as conn:
        conn.execute(
            "TRUNCATE TABLE intake_log, schedule_rules, medications, dependents, users "
            "RESTART IDENTITY CASCADE"
        )
    return d


@pytest.fixture(autouse=True)
def _clear_rate_counters():
    """Сбрасывает счётчики rate limiter перед каждым тестом."""
    try:
        import api.main as m
        m._counters.clear()
    except Exception:
        pass


@pytest.fixture(scope="module")
def api_client(_pg_schema):
    """TestClient для API с переопределённой авторизацией (telegram_id=TEST_TELEGRAM_ID)."""
    from starlette.testclient import TestClient
    from api.main import app
    from api.auth import require_telegram_user

    app.dependency_overrides[require_telegram_user] = lambda: TEST_TELEGRAM_ID
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()
