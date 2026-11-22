"""Older adults (65+) are planned earlier than able-bodied riders with the same deadline, never ahead of
people who cannot walk out, and only when the caller says so."""

from api.agent import flow
from api.agent.interpreter import rules
from api.dispatch import greedy
from api.sim import seed


def rider(rid: str, deadline: float, **need) -> greedy.Rider:
    return greedy.Rider(id=rid, loc=(0.0, 0.0), need=greedy.Need(**need), deadline_min=deadline)


def test_priority_order_wheelchair_then_older_adult_then_everyone():
    riders = [rider("walks", 60), rider("older", 60, olderAdult=True), rider("chair", 60, wheelchair=1)]
    assert [r.id for r in sorted(riders, key=greedy.priority_key)] == ["chair", "older", "walks"]


def test_a_much_earlier_deadline_still_comes_first():
    riders = [rider("older", 60, olderAdult=True), rider("walks_soon", 30)]
    assert [r.id for r in sorted(riders, key=greedy.priority_key)] == ["walks_soon", "older"]


def test_need_and_priority_carry_older_adult():
    record = {"peopleCount": 1, "mobility": "walker", "olderAdult": True}
    assert flow.compute_need(record)["olderAdult"] is True
    assert flow.compute_priority(record) == flow.compute_priority({**record, "olderAdult": None}) + 1
    assert greedy.Need.of({"olderAdult": True}).head_start_min() == 15.0


def test_interpreter_hears_an_age_only_when_it_is_said():
    assert rules("I'm 82 and I can't drive").set.get("olderAdult") is True
    assert rules("my mother is elderly").set.get("olderAdult") is True
    assert rules("Tengo 78 años").set.get("olderAdult") is True
    assert "olderAdult" not in rules("I'm 40, there are 2 of us").set
    assert "olderAdult" not in rules("we live at 1200 Oak street").set


def test_seeded_personas_use_their_age():
    assert seed._truth({"age": 81, "truth": {"hasCar": False}}) == {"hasCar": False, "olderAdult": True}
    assert "olderAdult" not in seed._truth({"age": 40, "truth": {}})
