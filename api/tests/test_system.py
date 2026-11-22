"""GET /system/metrics: real numbers from calls, evals and the census."""

import json

import pytest

from api.agent import standin
from api.core.config import get_settings
from api.sim import data as sim_data
from api.tests.factories import make_household


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    for k in ("gemini_api_key", "anthropic_api_key"):
        monkeypatch.setattr(get_settings(), k, "")


async def test_metrics_from_a_real_stand_in_call(client, db, tmp_path, monkeypatch):
    hh = await make_household(db, personaId="p01")
    await standin.run_call(db, hh["_id"], "call_sys")  # needs the real personas (data/)
    monkeypatch.setattr(sim_data, "DATA_DIR", tmp_path)  # then hide eval/sim files from /system

    body = (await client.get("/system/metrics")).json()
    live = body["live"]
    assert live["calls"] == 1 and live["latencyMs"]["standIns"]["turns"] > 5
    assert live["latencyMs"]["standIns"]["p50"] is not None and live["latencyMs"]["realPhone"]["turns"] == 0
    assert live["interpreter"] == {"rules": live["latencyMs"]["standIns"]["turns"]}
    assert body["census"]["openRequests"] == {"received": 1}
    assert body["evals"] is None and body["dispatch"] is None  # no files yet: null, never a placeholder
    assert any(a["kind"] == "request_created" for a in body["audit"])


async def test_metrics_read_eval_and_sim_files(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(sim_data, "DATA_DIR", tmp_path)
    (tmp_path / "eval-results.json").write_text(json.dumps({"modes": {"script": {"summary": {"personas": 40}}}}))
    (tmp_path / "sim-results.json").write_text(json.dumps({"onTime": {"median": 0.8}}))
    body = (await client.get("/system/metrics")).json()
    assert body["evals"]["modes"]["script"]["summary"]["personas"] == 40
    assert body["dispatch"]["onTime"]["median"] == 0.8
