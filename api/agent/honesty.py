"""Honesty guard: the last check on the AI's short acknowledgment before it is spoken.

The AI writes only an ack of at most 6 words ("A power chair."). Everything about a ride comes
from templates.py. This guard drops the ack when it:
  - contains any digit (numbers are where made-up ETAs and counts hide), always;
  - is longer than 6 words, always;
  - talks about timing ("soon", "ten minutes"), always, because only templates carry ETAs;
  - offers comfort ("you're safe", "don't worry") or advice ("stay put", "leave now"), always,
    because those sentences belong to templates;
  - sounds like a promise of help or timing while no driver has accepted
    (status none / received / approved / reassigning).

Patterns cover English and Spanish. When in doubt the guard drops: losing an ack costs nothing,
a false promise can cost a life.
"""

import re
from dataclasses import dataclass

MAX_WORDS = 6
UNCONFIRMED = frozenset({None, "none", "received", "approved", "reassigning"})

_PROMISE = [
    # English
    r"\bhelp\b.*\b(com|way|rout|arriv|near|close|soon|here|there)",
    r"\b(on|in) (the|their|its|our|his|her) way\b",
    r"\b(coming|arriving|dispatch|en route|assigned|sent|sending|send)\w*",
    r"\b(someone|somebody|driver|crew|van|ambulance|firefighter|responder|unit|rescue|they|we)\w*\b.*"
    r"\b(is|are|will|'ll|'re|'s|gonna|going to)\b.*\b(come|get|pick|be there|be here|arriv|reach|on it|send)",
    r"\b(we|i)('ll| will| are going to|'m going to| am going to|'re going to| can) "
    r"(get|send|pick|rescue|save|come|bring|take|have someone)",
    r"\bpick(ing|ed)? (you|them|him|her|y'all) up\b",
    r"\bbe (there|here|with you)\b",
    r"\b(promise|guarantee|rest assured|make sure (you|they))\b",
    r"\byou('ll| will) (be|get) (picked|rescued|helped|out|evacuated)",
    r"\bhelp is\b",
    # Spanish
    r"\ben camino\b",
    r"\bya (viene|vienen|va|van|llega|llegan)\b",
    r"\b(viene|vienen|llega|llegan|llegará|llegarán|enviamos|mandamos)\b",
    r"\b(vamos a|van a|voy a) (enviar|mandar|recoger|rescatar|sacar|ir|llegar)",
    r"\b(le|la|lo|los|las) (recoger|rescatar|sacar)\w*",
    r"\b(le )?(prometo|garantizo)\b",
    r"\bla ayuda\b",
]

# Timing words: an ETA said by the AI is made up even after a driver accepts. Templates carry ETAs.
_TIMING = [
    r"\b(soon|shortly|right away|quickly|in no time|any (minute|moment|second))\b",
    r"\b(minute|minutes|hour|hours|mins?)\b",
    r"\b(pronto|enseguida|ahorita|en seguida|minutos?|horas?)\b",
]

_COMFORT = [
    r"\b(don'?t|do not|no need to|nothing to|not to) (worry|panic|be afraid|be scared)\b",
    r"\bsafe\b",
    r"\b(be|are|'re|is|'s) (fine|ok|okay|alright|all right|good)\b",
    r"\b(going to|gonna|will) be (fine|ok|okay|alright|all right|good)\b",
    r"\beverything\b",
    r"\b(relax|calm down)\b",
    r"\bthe fire (is|isn'?t|won'?t|will|has|hasn'?t)\b",
    r"\bno (danger|risk)\b",
    r"\b(you'?re|you are) (in good hands|not alone|covered|protected)\b",
    # Spanish
    r"\bno se preocupe\b",
    r"\b(está|estará|estarán|están|estamos|va a estar|van a estar) (a salvo|bien|segur[oa]s?|tranquil[oa]s?)\b",
    r"\btodo\b",
    r"\b(a salvo|seguro|segura|tranquilo|tranquila|cálmese|calmese)\b",
]

_ADVICE = [
    r"\bstay\b",
    r"\bwait\b",
    r"\b(don'?t|do not) (leave|go|move)\b",
    r"\bshelter\b",
    r"\b(should|must|need to|have to|ought to|better)\b",
    r"\b(leave|go|head|get out|evacuate|drive|run)\b.*\b(now|immediately|to|toward|towards)\b",
    r"\bevacuate\b",
    r"\b(call|dial) (911|nine one one)\b",
    # Spanish
    r"\b(quédese|quedese|espere|esperen|no salga|salga|vaya|váyase|vayase|debe|tiene que|evacúe|evacue)\b",
]

_P = re.compile("|".join(f"(?:{p})" for p in _PROMISE), re.IGNORECASE)
_T = re.compile("|".join(f"(?:{p})" for p in _TIMING), re.IGNORECASE)
_C = re.compile("|".join(f"(?:{p})" for p in _COMFORT), re.IGNORECASE)
_A = re.compile("|".join(f"(?:{p})" for p in _ADVICE), re.IGNORECASE)
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Verdict:
    ack: str | None  # the ack to speak, or None if dropped
    blocked: bool
    reason: str | None = None


def check(ack: str | None, status: str | None) -> Verdict:
    """Return the ack if it may be spoken while the request is in `status`, else drop it."""
    text = (ack or "").strip()
    if not text:
        return Verdict(None, False)
    norm = text.replace("’", "'")
    if _DIGIT.search(norm):
        return Verdict(None, True, "digits")
    if len(norm.split()) > MAX_WORDS:
        return Verdict(None, True, "too_long")
    if _T.search(norm):
        return Verdict(None, True, "timing")
    if _C.search(norm):
        return Verdict(None, True, "comfort")
    if _A.search(norm):
        return Verdict(None, True, "advice")
    if status in UNCONFIRMED and _P.search(norm):
        return Verdict(None, True, "promise")
    return Verdict(text, False)
