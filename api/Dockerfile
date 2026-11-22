# RideOut API. Build from the repo root:
#   docker build -t rideout-api --build-context data=data --build-arg GIT_SHA=$(git rev-parse --short HEAD) api
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app/api
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
# Scenario + personas for /sim/seed (named build context `data` = the repo's data/ folder).
COPY --from=data . /app/data

ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} PATH="/app/api/.venv/bin:${PATH}"

# The package is `api`, so run from its parent.
WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health'); sys.exit(0)"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
