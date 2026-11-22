"""Impact simulation: the published numbers must come from a model that obeys its own rules."""

import json

import pytest

from api.sim import compare
from api.sim.geo import Road

ROAD = Road()


@pytest.mark.parametrize("column", compare.COLUMNS)
def test_same_seed_same_world(column):
    a = compare.make_world(11, column, ROAD)
    b = compare.make_world(11, column, ROAD)
    assert [(h.loc, h.deadline, h.need) for h in a.homes] == [(h.loc, h.deadline, h.need) for h in b.homes]
    assert len(a.homes) == compare.HOMES
    assert len(a.fleet) == {"low": 4, "middle": 8, "high": 12}[column]


@pytest.mark.parametrize("column", compare.COLUMNS)
def test_first_deadline_matches_the_setting(column):
    w = compare.make_world(3, column, ROAD)
    assert min(h.deadline for h in w.homes) == pytest.approx(compare.SETTINGS[column]["firstArrivalMin"] - 10)


@pytest.mark.parametrize("column", compare.COLUMNS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_safe_seat_never_picks_up_before_it_knows(column, seed):
    w = compare.make_world(seed, column, ROAD)
    r = compare.run_rideout(w, column, seed, ROAD)
    for t in r["trace"]:
        assert t["planned"] >= t["known"]
        # can't arrive before the offer is approved + accepted
        assert t["pickup"] >= t["planned"] + compare.DISPATCH_MIN - 1e-9
    assert 0 <= r["onTime"] <= r["people"]


@pytest.mark.parametrize("column", compare.COLUMNS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_today_respects_the_911_delay_and_queue(column, seed):
    w = compare.make_world(seed, column, ROAD)
    r = compare.run_today(w, column, seed, ROAD)
    delay = compare.SETTINGS[column]["today911DelayMin"]
    calls = [t["calledAt"] for t in r["trace"]]
    assert calls == sorted(calls)  # first come, first served
    for t in r["trace"]:
        assert t["dispatch"] >= delay and t["dispatch"] >= t["calledAt"]
        assert t["pickup"] >= t["dispatch"]


def test_today_uses_agency_vehicles_only_by_default():
    w = compare.make_world(4, "middle", ROAD)
    only_agency = compare.run_today(w, "middle", 4, ROAD)
    with_neighbors = compare.run_today(w, "middle", 4, ROAD, neighbors=True)
    assert with_neighbors["onTime"] >= only_agency["onTime"]


def test_reach_ladder_answer_times():
    w = compare.make_world(5, "middle", ROAD)
    known = compare.reveal_times(w, "middle", 5)
    riders = [i for i, h in enumerate(w.homes) if h.need]
    assert set(known) == set(riders)
    slowest = len(w.homes) / compare.CALLS_PER_MIN + sum(compare.LADDER_GAPS_MIN) + 3 * compare.RING_MIN
    assert all(compare.CALL_MIN <= t <= slowest + compare.DOOR_CHECK_MIN + 1 for t in known.values())


def test_results_file_shape(tmp_path):
    out = tmp_path / "sim-results.json"
    assert compare.main(["--seeds", "3", "--out", str(out)]) == 0
    r = json.loads(out.read_text())
    assert r["simulated"] is True and r["seedsPerColumn"] == 3
    keys = [b["key"] for b in r["bars"]]
    assert keys == ["today", "greedy", "ortools"]
    for b in r["bars"][:2]:
        assert b["min"] <= b["median"] <= b["max"]
        assert set(b["columns"]) == set(compare.COLUMNS)
    assert r["bars"][2]["available"] is False
    assert "Simulated" in r["label"] and "picked up before" in r["headline"]["text"]
    assert r["assumptions"]["today911FleetExcludesNeighbors"] is True
