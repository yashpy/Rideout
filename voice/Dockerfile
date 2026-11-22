# RideOut voice relay (ElevenLabs Custom LLM). Build from voice/:  docker build -t rideout-voice .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY main.py client.py ./
ENV PATH="/app/.venv/bin:${PATH}" PORT=8080
EXPOSE 8080
CMD ["python", "main.py"]
