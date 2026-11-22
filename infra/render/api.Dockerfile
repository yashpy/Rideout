# RideOut API for Render (free web service). Same as api/Dockerfile, but built from the repo root
# because Render has no named build contexts. Render sets $PORT.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app/api
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY api/ .
COPY data/ /app/data

ENV PATH="/app/api/.venv/bin:${PATH}"
WORKDIR /app
EXPOSE 8000
CMD uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'
