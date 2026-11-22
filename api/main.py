"""RideOut API.

Run from the repo root:   uv run --project api uvicorn api.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from api import live, workers
from api.core import db as dbmod
from api.core.config import VERSION, get_settings
from api.hazard import tiger
from api.routes import (
    agent,
    assignments,
    calls,
    hazards,
    health,
    households,
    persona,
    plans,
    ride_requests,
    roads,
    sim,
    system,
    vehicles,
    zones,
)
from api.sim import world

log = logging.getLogger("api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROUTERS = [
    # core
    health,
    households,
    ride_requests,
    assignments,
    live,
    # resident side
    agent,
    calls,
    persona,
    zones,
    system,
    # responder side
    plans,
    vehicles,
    roads,
    hazards,
    sim,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db = dbmod.get_db()
    await dbmod.ensure_indexes(db)
    await world.load(db)  # which scenario (canyon or North Scottsdale) the stored world is in
    tasks = workers.start(db) if get_settings().run_workers else []
    yield
    await workers.stop(tasks)
    await tiger.close()
    dbmod.close()


class ErrorsAsJson:
    """Unexpected errors → `500 {"detail": "<Type>: <message>"}` instead of a bare 500.

    Without this, a crash returns from outside the CORS middleware, the browser hides it as "Failed to
    fetch", and the console can't say what broke.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as e:
            log.exception("unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if started:
                raise
            detail = f"{type(e).__name__}: {str(e)[:300]}"
            await JSONResponse({"detail": detail}, status_code=500)(scope, receive, send)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="RideOut API", version=VERSION, lifespan=lifespan)
    # gzip JSON over ~1 KB: the homes list is ~3 MB raw at 6,000 homes, ~10x smaller compressed
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(ErrorsAsJson)  # added first = inside CORS, so 500s still carry CORS headers
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in s.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for module in ROUTERS:
        app.include_router(module.router)
    return app


app = create_app()
