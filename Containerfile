# ── Stage 1: зависимости ────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# DV3: образ из запиненных версий — детерминизм с прод/CI.
COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt


# ── Stage 2: runtime ────────────────────────────────────────────────────────
FROM python:3.14-slim

# DejaVu-шрифты для PDF-экспорта (fpdf2 ищет /usr/share/fonts/truetype/dejavu/)
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Непривилегированный пользователь
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Зависимости из builder-стадии
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Код приложения
COPY --chown=appuser:appuser . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

CMD ["python3", "bot.py"]
