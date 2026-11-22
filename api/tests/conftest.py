"""Test setup. Uses an in-memory mock Mongo by default.

Set MONGODB_TEST_URI (CI does) to run against a real MongoDB, which is what proves atomic accept.
"""

import os
import uuid

os.environ.setdefault("ENV", "test")
os.environ["RUN_WORKERS"] = "false"
os.environ["INTERNAL_TOKEN"] = "test-token"
# Tests never call real services, even if a developer's .env has keys (env vars override .env).
for _k in (
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "TINYFISH_API_KEY",
    "FIRMS_MAP_KEY",
    "TIGER_DATABASE_URL",  # test_fire.py opts in with TIGER_TEST_URL
):
    os.environ[_k] = ""

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from api.core import db as dbmod  # noqa: E402
from api.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
async def db():
    uri = os.environ.get("MONGODB_TEST_URI")
    if uri:
        from motor.motor_asyncio import AsyncIOMotorClient

        client = AsyncIOMotorClient(uri, tz_aware=True)
        name = f"rideout_test_{uuid.uuid4().hex[:8]}"
        database = client[name]
    else:
        from mongomock_motor import AsyncMongoMockClient

        client = AsyncMongoMockClient(tz_aware=True)
        name = None
        database = client["rideout_test"]

    await dbmod.ensure_indexes(database)
    dbmod.set_db(database)
    yield database
    if name:
        await client.drop_database(name)
        client.close()


@pytest.fixture
async def client(db):
    from api.main import create_app

    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        yield c
