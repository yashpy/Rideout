"""Every sentence the agent says, in English and Spanish. The AI never writes these.

Ride-status lines follow CONTRACT §4 word for word. Questions have a normal and a simpler
re-ask form, plus a one-line reason for when the resident asks why we need it (principle 6).
"""

from typing import Any

Lang = str  # "en" | "es"

# ── ride status (CONTRACT §4) ─────────────────────────────────────────────────

_ON_LIST = {
    "en": (
        "You're on the rescue list as high priority. No driver has accepted yet. "
        "I'll call you back the moment one does. If you can leave safely, leave now. "
        "If fire reaches your home, call 911."
    ),
    "es": (
        "Usted está en la lista de rescate con prioridad alta. Ningún conductor ha aceptado todavía. "
        "Le llamaré en cuanto uno acepte. Si puede salir de forma segura, salga ahora. "
        "Si el fuego llega a su casa, llame al 911."
    ),
}

STATUS: dict[Lang, dict[str, str]] = {
    "en": {
        # No request exists yet: we can't say they're on the list, because they aren't.
        "none": "No driver is assigned to you. I need a few answers first to put you on the rescue list.",
        "received": _ON_LIST["en"],
        "approved": _ON_LIST["en"],
        "driver_accepted": (
            "A {vehicle} with {crew} is {eta} minutes away. The driver's name is {name}. "
            "I'll call again if anything changes."
        ),
        "driver_accepted_no_detail": "A driver has accepted your pickup. I'll call again if anything changes.",
        "en_route": "{name} is about {eta} minutes away.",
        "reassigning": (
            "Your driver can no longer reach you. You're still at the top of the list. "
            "I'll call the moment a new driver accepts. If you can leave safely, leave now."
        ),
        "arrived": "Your driver has arrived.",
        "closed": "Your driver has arrived.",
        "not_needed": "You told me you can leave on your own, so no driver is assigned to you.",
    },
    "es": {
        "none": "No tiene un conductor asignado. Necesito unas respuestas para ponerle en la lista de rescate.",
        "received": _ON_LIST["es"],
        "approved": _ON_LIST["es"],
        "driver_accepted": (
            "Un {vehicle} con {crew} está a {eta} minutos. El conductor se llama {name}. "
            "Le llamaré otra vez si algo cambia."
        ),
        "driver_accepted_no_detail": "Un conductor aceptó recogerle. Le llamaré otra vez si algo cambia.",
        "en_route": "{name} está a unos {eta} minutos.",
        "reassigning": (
            "Su conductor ya no puede llegar a usted. Sigue al principio de la lista. "
            "Le llamaré en cuanto acepte otro conductor. Si puede salir de forma segura, salga ahora."
        ),
        "arrived": "Su conductor ha llegado.",
        "closed": "Su conductor ha llegado.",
        "not_needed": "Me dijo que puede salir por su cuenta, así que no tiene un conductor asignado.",
    },
}

_VEHICLE = {
    "en": {"paratransit": "wheelchair van", "agency_van": "county van", "neighbor": "neighbor's car"},
    "es": {
        "paratransit": "camioneta para sillas de ruedas",
        "agency_van": "camioneta del condado",
        "neighbor": "carro de un vecino",
    },
}
_CREW = {
    "en": {1: "one driver", 2: "a two-person crew"},
    "es": {1: "un conductor", 2: "un equipo de dos personas"},
}


def status_line(lang: Lang, status: str | None, ride: dict[str, Any] | None = None) -> str:
    """The one sentence block allowed for this request status. `ride` = {vehicleKind, crew, eta, name}."""
    t = STATUS[_l(lang)]
    key = status or "none"
    if key in ("driver_accepted", "en_route"):
        ride = ride or {}
        if not (ride.get("name") and ride.get("eta") is not None):
            return t["driver_accepted_no_detail"]
        crew_n = 2 if (ride.get("crew") or 1) >= 2 else 1
        eta = max(1, round(float(ride["eta"])))
        text = t[key].format(
            vehicle=_VEHICLE[_l(lang)].get(ride.get("vehicleKind") or "", _VEHICLE[_l(lang)]["agency_van"]),
            crew=_CREW[_l(lang)][crew_n],
            eta=eta,
            name=ride["name"],
        )
        if eta == 1:  # "1 minutes" → "1 minute"
            text = text.replace("1 minutes", "1 minute").replace("1 minutos", "1 minuto")
        return text
    return t.get(key, t["none"])


# ── fixed lines ───────────────────────────────────────────────────────────────

LINES: dict[Lang, dict[str, str]] = {
    "en": {
        "greet": (
            "Hello. I'm the RideOut automated assistant, working with the evacuation dispatchers. "
            "Your area is under a Set warning, so get ready to leave. I have a few quick questions."
        ),
        "greet_callback": "Hello. This is the RideOut automated assistant with an update on your ride.",
        "spanish_offer": "Para español, diga español.",
        "switched": "Muy bien, seguimos en español.",
        "medical": "If someone needs medical help right now, call 911. I'm flagging this for the dispatchers now.",
        "flames": "If fire is at your home, leave now if you can, and call 911. I'm flagging this now.",
        "advice": "If you can leave safely, leave now. If fire reaches your home, call 911.",
        "dont_know": "I don't know that yet.",
        "noted": "I've noted that for the dispatchers.",
        "readback_fix": "What should I change?",
        "leave_now": "Please leave now if you can do it safely. If fire reaches your home, call 911.",
        "callback_more": "If anything changes, I'll call again.",
        "goodbye": "Thank you. Goodbye.",
    },
    "es": {
        "greet": (
            "Hola. Soy el asistente automático de RideOut y trabajo con los despachadores de la evacuación. "
            "Su zona está en alerta Set, así que prepárese para salir. Tengo unas preguntas rápidas."
        ),
        "greet_callback": "Hola. Le habla el asistente automático de RideOut con noticias sobre su transporte.",
        "spanish_offer": "",
        "switched": "Muy bien, seguimos en español.",
        "medical": "Si alguien necesita ayuda médica ahora, llame al 911. Estoy avisando a los despachadores.",
        "flames": "Si el fuego está en su casa, salga ahora si puede y llame al 911. Estoy avisando ahora.",
        "advice": "Si puede salir de forma segura, salga ahora. Si el fuego llega a su casa, llame al 911.",
        "dont_know": "Eso todavía no lo sé.",
        "noted": "Lo anoté para los despachadores.",
        "readback_fix": "¿Qué debo cambiar?",
        "leave_now": (
            "Por favor, salga ahora si puede hacerlo de forma segura. Si el fuego llega a su casa, llame al 911."
        ),
        "callback_more": "Si algo cambia, le llamaré otra vez.",
        "goodbye": "Gracias. Adiós.",
    },
}

# goal → (ask, simpler re-ask, why we ask)
QUESTIONS: dict[Lang, dict[str, tuple[str, str, str]]] = {
    "en": {
        "address": (
            "Are you at {address}?",
            "Is your home at {address}? Please say yes or no.",
            "So a driver comes to the right house.",
        ),
        "can_leave": (
            "Can everyone in your home leave on their own right now?",
            "Can you leave by yourself? Yes or no.",
            "So we know who needs a ride out.",
        ),
        "people": (
            "How many people are at home, counting you?",
            "How many people are there? For example, just me, or two.",
            "So the vehicle has a seat for everyone.",
        ),
        "pets": (
            "Are there any pets at home?",
            "Any pets? Yes or no.",
            "So we can plan room for them.",
        ),
        "car": (
            "Do you have a car you can leave in?",
            "Do you have a car? Yes or no.",
            "So we know if you need a ride.",
        ),
        "mobility": (
            "Does anyone need help walking, or use a walker or a wheelchair?",
            "Does anyone use a walker or wheelchair, or stay in bed? Or can everyone walk?",
            "So we send a vehicle that fits.",
        ),
        "oxygen": (
            "Does anyone use oxygen or other medical equipment?",
            "Any oxygen? Yes or no.",
            "So the crew brings what they need.",
        ),
        "chair_kind": (
            "Is it a manual chair or a power chair?",
            "Is the chair electric? Yes or no.",
            "So we send a vehicle that fits the chair.",
        ),
        "assistance": (
            "How much help is needed getting out: none, one person, or two people to lift?",
            "Does it take two people to lift? Yes or no.",
            "So we send enough crew.",
        ),
        "readback": (
            "Let me check I have this right: {summary}. Is that right?",
            "I have: {summary}. Yes or no?",
            "So the crew gets it right.",
        ),
        "neighbor_rider": (
            "Do you know a neighbor who may need help getting out?",
            "Any neighbor who might need help? Yes or no.",
            "We try to reach everyone nearby.",
        ),
        "neighbor_driver": (
            "Do you have room to take a neighbor who needs a ride?",
            "Could you give a neighbor a ride? Yes or no.",
            "Neighbors who are leaving can help people without a ride.",
        ),
        "hold": (
            "Is there anything else the dispatchers should know?",
            "Anything else? Yes or no.",
            "So nothing important gets missed.",
        ),
    },
    "es": {
        "address": (
            "¿Está usted en {address}?",
            "¿Su casa está en {address}? Diga sí o no.",
            "Para que el conductor llegue a la casa correcta.",
        ),
        "can_leave": (
            "¿Pueden todos en su casa salir por su cuenta ahora mismo?",
            "¿Puede salir solo? Sí o no.",
            "Para saber quién necesita transporte.",
        ),
        "people": (
            "¿Cuántas personas hay en casa, contándole a usted?",
            "¿Cuántas personas hay? Por ejemplo, solo yo, o dos.",
            "Para que haya asiento para todos.",
        ),
        "pets": (
            "¿Hay mascotas en casa?",
            "¿Mascotas? Sí o no.",
            "Para planear espacio para ellas.",
        ),
        "car": (
            "¿Tiene un carro para salir?",
            "¿Tiene carro? Sí o no.",
            "Para saber si necesita transporte.",
        ),
        "mobility": (
            "¿Alguien necesita ayuda para caminar, o usa andador o silla de ruedas?",
            "¿Alguien usa andador o silla de ruedas, o está en cama? ¿O todos caminan?",
            "Para enviar un vehículo adecuado.",
        ),
        "oxygen": (
            "¿Alguien usa oxígeno u otro equipo médico?",
            "¿Oxígeno? Sí o no.",
            "Para que el equipo lleve lo necesario.",
        ),
        "chair_kind": (
            "¿La silla es manual o eléctrica?",
            "¿La silla es eléctrica? Sí o no.",
            "Para enviar un vehículo donde quepa la silla.",
        ),
        "assistance": (
            "¿Cuánta ayuda se necesita para salir: ninguna, una persona, o dos personas para levantar?",
            "¿Se necesitan dos personas para levantar? Sí o no.",
            "Para enviar suficiente personal.",
        ),
        "readback": (
            "Déjeme confirmar: {summary}. ¿Es correcto?",
            "Tengo: {summary}. ¿Sí o no?",
            "Para que el equipo lo tenga bien.",
        ),
        "neighbor_rider": (
            "¿Conoce a algún vecino que pueda necesitar ayuda para salir?",
            "¿Algún vecino que necesite ayuda? Sí o no.",
            "Intentamos llegar a todos los vecinos.",
        ),
        "neighbor_driver": (
            "¿Tiene espacio para llevar a un vecino que necesite transporte?",
            "¿Podría llevar a un vecino? Sí o no.",
            "Los vecinos que salen pueden ayudar a quien no tiene transporte.",
        ),
        "hold": (
            "¿Hay algo más que deban saber los despachadores?",
            "¿Algo más? Sí o no.",
            "Para no pasar nada importante por alto.",
        ),
    },
}

_NUM = {
    "en": ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"],
    "es": ["cero", "una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez"],
}
_SUMMARY = {
    "en": {
        "people_1": "one person",
        "people_n": "{n} people",
        "walks": "everyone can walk",
        "walker": "someone uses a walker",
        "manual_wheelchair": "a manual wheelchair",
        "power_wheelchair": "a power wheelchair",
        "wheelchair": "a wheelchair",
        "bedbound": "someone who stays in bed",
        "oxygen": "oxygen",
        "dialysis": "dialysis",
        "other": "other medical needs",
        "none": "no help needed getting out",
        "one_person": "one person to help",
        "two_person_lift": "two people to lift",
        "pets": "a pet",
        "and": "and",
    },
    "es": {
        "people_1": "una persona",
        "people_n": "{n} personas",
        "walks": "todos caminan",
        "walker": "alguien usa andador",
        "manual_wheelchair": "una silla de ruedas manual",
        "power_wheelchair": "una silla de ruedas eléctrica",
        "wheelchair": "una silla de ruedas",
        "bedbound": "alguien que está en cama",
        "oxygen": "oxígeno",
        "dialysis": "diálisis",
        "other": "otras necesidades médicas",
        "none": "no necesita ayuda para salir",
        "one_person": "una persona para ayudar",
        "two_person_lift": "dos personas para levantar",
        "pets": "una mascota",
        "and": "y",
    },
}


def _l(lang: Lang | None) -> Lang:
    return lang if lang in LINES else "en"


def line(lang: Lang, key: str) -> str:
    return LINES[_l(lang)][key]


def question(lang: Lang, goal: str, *, simple: bool = False, **fmt: Any) -> str:
    ask, simpler, _ = QUESTIONS[_l(lang)][goal]
    return (simpler if simple else ask).format(**fmt)


def why(lang: Lang, goal: str) -> str:
    return QUESTIONS[_l(lang)][goal][2]


def summary(lang: Lang, record: dict[str, Any], chair_pending: bool = False) -> str:
    """Read-back of the record in plain words, e.g. "two people, a power wheelchair, oxygen, and a pet"."""
    s = _SUMMARY[_l(lang)]
    parts: list[str] = []
    n = record.get("peopleCount")
    if n:
        word = _NUM[_l(lang)][n] if n < len(_NUM[_l(lang)]) else str(n)
        parts.append(s["people_1"] if n == 1 else s["people_n"].format(n=word))
    mob = "wheelchair" if chair_pending else record.get("mobility")
    if mob:
        parts.append(s[mob])
    parts += [s[m] for m in record.get("medical") or [] if m in s]
    if record.get("assistance") and mob not in (None, "walks"):
        parts.append(s[record["assistance"]])
    if record.get("pets"):
        parts.append(s["pets"])
    if len(parts) < 2:
        return "".join(parts)
    head, last = parts[:-1], f"{s['and']} {parts[-1]}"
    return f"{', '.join(head)}, {last}" if len(head) > 1 else f"{head[0]} {last}"
