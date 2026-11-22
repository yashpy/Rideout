"""Honesty guard: promises, comfort and advice never reach the resident before a driver accepts."""

import pytest

from api.agent import honesty

PROMISES = [
    "Help is on the way.",
    "Help is coming.",
    "Someone is coming for you.",
    "A driver is on the way.",
    "We'll send someone.",
    "We will get you out.",
    "We're going to pick you up.",
    "They'll be there soon.",
    "Rescue is coming.",
    "The van is coming.",
    "Firefighters are on their way.",
    "Someone will be there shortly.",
    "Help will arrive soon.",
    "Hang tight, they're coming.",
    "We'll come get you.",
    "A crew is being dispatched.",
    "I'll have someone there.",
    "Somebody will pick you up.",
    "Any minute now.",
    "Just a few minutes.",
    "I promise we'll help.",
    "Help is close by.",
    "You'll be picked up.",
    "La ayuda va en camino.",
    "Ya vienen por usted.",
    "Vamos a enviar a alguien.",
    "Llegan pronto.",
    "Le prometo ayuda.",
    "Lo vamos a recoger.",
    "Ya llega el conductor.",
]

COMFORT_AND_ADVICE = [
    "Don't worry.",
    "You're safe now.",
    "You'll be fine.",
    "Everything will be okay.",
    "Stay where you are.",
    "Wait inside for them.",
    "Don't leave the house.",
    "You should leave now.",
    "No se preocupe.",
    "Está a salvo.",
    "Quédese en casa.",
    "Todo va a estar bien.",
]

DIGITS = ["About 5 minutes.", "Two people, 2 chairs.", "Unit 7 assigned.", "Got it, 3 of you."]
TIMING = ["Ten minutes away.", "Very soon.", "Unos minutos.", "Right away."]

NEUTRAL = [
    "A power chair.",
    "Thanks, a power chair.",
    "Got it, two of you.",
    "Okay, a walker.",
    "Understood, oxygen.",
    "A dog, noted.",
    "Thank you for telling me.",
    "That sounds frightening.",
    "I hear you.",
    "Your husband, got it.",
    "Okay.",
    "Thank you.",
    "Just you, understood.",
    "A manual chair.",
    "Noted, he needs lifting.",
    "Two cats, okay.",
    "Your son is with you.",
    "Got it, no car.",
    "Bedbound, understood.",
    "Thanks for your patience.",
    "Sorry, I missed that.",
    "Understood, your choice.",
    "Okay, the house across.",
    "A walker and oxygen.",
    "Gracias, una silla eléctrica.",
    "Entendido, dos personas.",
    "Un perro, anotado.",
    "Gracias por decirme.",
    "Entiendo.",
    "Su esposo, entendido.",
]


@pytest.mark.parametrize("ack", PROMISES)
@pytest.mark.parametrize("status", [None, "received", "approved", "reassigning"])
def test_promises_blocked_before_accept(ack, status):
    v = honesty.check(ack, status)
    assert v.blocked and v.ack is None, ack


def test_thirty_promise_lines():
    assert len(PROMISES) == 30 and len(NEUTRAL) == 30


@pytest.mark.parametrize("ack", COMFORT_AND_ADVICE)
@pytest.mark.parametrize("status", [None, "received", "driver_accepted", "en_route"])
def test_comfort_and_advice_always_blocked(ack, status):
    assert honesty.check(ack, status).blocked, ack


@pytest.mark.parametrize("ack", DIGITS)
@pytest.mark.parametrize("status", [None, "driver_accepted"])
def test_digits_always_blocked(ack, status):
    v = honesty.check(ack, status)
    assert v.blocked and v.reason == "digits"


@pytest.mark.parametrize("ack", TIMING)
@pytest.mark.parametrize("status", [None, "driver_accepted"])
def test_timing_always_blocked(ack, status):
    """Even after a driver accepts, only templates carry an ETA."""
    assert honesty.check(ack, status).reason == "timing"


@pytest.mark.parametrize("ack", NEUTRAL)
@pytest.mark.parametrize("status", [None, "received", "approved", "reassigning", "driver_accepted"])
def test_neutral_acks_pass(ack, status):
    v = honesty.check(ack, status)
    assert not v.blocked and v.ack == ack, (ack, v.reason)


def test_long_ack_dropped():
    assert honesty.check("Thanks so much, I have written all that down.", None).reason == "too_long"


def test_empty_ack_is_not_a_block():
    v = honesty.check("  ", None)
    assert v.ack is None and not v.blocked
