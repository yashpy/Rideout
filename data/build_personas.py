"""Build data/personas.json. Fictional residents only.

Run from repo root:  python3 data/build_personas.py
Enums match docs/CONTRACT.md `households.record`.
"""

import json
from pathlib import Path

MOBILITY = {"walks", "walker", "manual_wheelchair", "power_wheelchair", "bedbound"}
ASSIST = {"none", "one_person", "two_person_lift"}
CAN_LEAVE = {"yes", "no", "unsure"}
MEDICAL = {"oxygen", "dialysis", "other"}
TRICKY = {"pushes for a promise", "won't leave without dog", "hard of hearing", "speaks Spanish only"}


def p(id_, name, age, lang, truth, script, correction=None, tricky=None, neighbor=None, expect=None):
    t = dict(
        canLeave=truth[0], peopleCount=truth[1], mobility=truth[2], assistance=truth[3],
        medical=truth[4], pets=truth[5], hasCar=truth[6],
    )
    d = {"id": id_, "name": name, "age": age, "language": lang, "truth": t, "script": script}
    if correction:
        d["correction"] = correction
    if tricky:
        d["tricky"] = tricky
    if neighbor:
        d["neighbor"] = neighbor
    if expect:
        d["expect"] = expect
    return d


PERSONAS = [
    # ---- The demo persona -------------------------------------------------------------
    p("p01", "Rosa Delgado", 81, "en", ("no", 2, "power_wheelchair", "two_person_lift", [], False, False),
      ["Hello? Yes, this is Rosa.", "No, I don't think I can leave on my own.", "It's just me.",
       "Oh wait, I'm sorry. My husband is here. He's in a power chair. He needs two people to lift him.",
       "We don't have a car anymore.", "No pets. Is someone coming?"],
      correction="peopleCount 1 -> 2; mobility walks -> power_wheelchair; assistance -> two_person_lift",
      tricky="pushes for a promise",
      expect={"role": "needs_ride", "need": {"seats": 2, "wheelchair": 1, "crew": 2, "lift": True},
              "mustNotSay": ["coming", "on the way", "minutes"]}),

    # ---- Needs a ride -------------------------------------------------------------------
    p("p02", "Harold Brandt", 88, "en", ("no", 1, "walker", "one_person", ["oxygen"], False, False),
      ["Yes?", "I use a walker and I'm on oxygen.", "It's only me here.",
       "I gave up driving two years ago.", "I'd need someone to help me down the steps."],
      expect={"role": "needs_ride"}),
    p("p03", "Margaret Ellison", 79, "en", ("no", 1, "walks", "one_person", [], True, True),
      ["Who is this?", "WHAT? Can you say that again, louder?", "Leave? I can't hear you, dear.",
       "Oh. Yes. I live alone. I have a car but I can't see well enough to drive at night.",
       "I have a cat, Biscuit."],
      tricky="hard of hearing", expect={"role": "needs_ride", "flags": ["asks_repeat"]}),
    p("p04", "Walter Ng", 92, "en", ("no", 1, "bedbound", "two_person_lift", ["oxygen"], False, False),
      ["This is his daughter, Linda, I'm on the phone for him.", "Dad is bedbound. He's on oxygen.",
       "I'm in Phoenix. He's alone right now until the aide comes at six.",
       "He'll need a stretcher or two people."],
      expect={"role": "needs_ride", "need": {"stretcher": 1, "crew": 2}, "escalation": "medical"}),
    p("p05", "Dolores Vega", 84, "es", ("no", 1, "walker", "one_person", [], True, False),
      ["¿Bueno?", "No hablo inglés.", "Vivo sola. Uso andadera.", "No tengo carro.",
       "Tengo un perrito, no lo voy a dejar."],
      tricky="speaks Spanish only", expect={"role": "needs_ride", "language": "es"}),
    p("p06", "George Pappas", 76, "en", ("no", 2, "manual_wheelchair", "one_person", [], True, True),
      ["Yeah, this is George.", "My wife's in a wheelchair, the folding kind.",
       "I can push her but I can't get her and the chair into the truck by myself with my back.",
       "It's the two of us and the dog.", "I'm not leaving Max. He comes or we stay."],
      tricky="won't leave without dog", expect={"role": "needs_ride"}),
    p("p07", "Evelyn Marsh", 83, "en", ("no", 1, "walker", "one_person", ["dialysis"], False, True),
      ["Hello.", "I have dialysis tomorrow morning in Cottonwood.",
       "I have a car, but my daughter drives me. I don't drive on the switchbacks.",
       "Just me.", "When will someone be here? I need to know a time."],
      tricky="pushes for a promise", expect={"role": "needs_ride", "flags": ["wants_time"]}),
    p("p08", "Frank Odom", 71, "en", ("no", 1, "manual_wheelchair", "one_person", [], False, False),
      ["Frank here.", "I'm a below-knee amputee, I use a wheelchair most days.",
       "No car, I sold it.", "I can transfer if someone holds the chair.", "Nobody else here."],
      expect={"role": "needs_ride"}),
    p("p09", "Ruth Calloway", 95, "en", ("no", 2, "walker", "one_person", ["other"], False, False),
      ["Hello?", "My son lives with me. He has Down syndrome, he's 60.",
       "I use a walker. He walks fine but he won't go without me.", "We don't drive.",
       "So two of us."],
      expect={"role": "needs_ride", "need": {"seats": 2}}),
    p("p10", "Tomás Ibarra", 67, "es", ("no", 3, "walks", "one_person", [], False, False),
      ["Sí, buenas tardes.", "Somos tres: yo, mi esposa y mi suegra.",
       "Mi suegra tiene 90 años y camina muy despacio.", "No tenemos carro, se descompuso ayer.",
       "¿Cuándo llegan?"],
      tricky="speaks Spanish only", expect={"role": "needs_ride", "language": "es", "need": {"seats": 3}}),
    p("p11", "Irene Kowalski", 74, "en", ("no", 1, "walks", "none", ["oxygen"], False, False),
      ["Yes, hello.", "I'm on oxygen, I have a portable tank with about three hours.",
       "I walk fine but I don't have a car.", "Just me."],
      expect={"role": "needs_ride"}),
    p("p12", "Leonard Fisk", 89, "en", ("no", 1, "power_wheelchair", "two_person_lift", [], False, False),
      ["Fisk.", "I'm in a power chair. It weighs three hundred pounds.",
       "You'd need a van with a ramp or two strong people.", "I'm by myself.",
       "Are you sending someone or not? Yes or no."],
      tricky="pushes for a promise", expect={"role": "needs_ride", "mustNotSay": ["yes", "coming"]}),
    p("p13", "Agnes Whitfield", 86, "en", ("unsure", 1, "walker", "one_person", [], True, True),
      ["Oh, I don't know.", "I have a car, but I haven't driven it since my hip.",
       "Maybe my neighbor can take me, I'm not sure he's home.", "I have two birds."],
      expect={"role": "needs_ride"}),
    p("p14", "Samuel Rourke", 63, "en", ("no", 1, "walks", "none", [], True, False),
      ["Yep.", "No car, I bike into town.", "Can't bike out in this smoke.",
       "Me and my dog, Juniper. She's big, sixty pounds.", "She comes with me."],
      tricky="won't leave without dog", expect={"role": "needs_ride"}),
    p("p15", "Beatrice Lam", 78, "en", ("no", 1, "walks", "one_person", ["other"], False, True),
      ["Hello?", "I have dementia, my aide wrote it on the fridge for me.",
       "There's a car but I don't have the keys.", "I'm here by myself. My aide comes back tonight."],
      expect={"role": "needs_ride"}),

    # ---- Medical / flames escalation ---------------------------------------------------
    p("p16", "Carl Henning", 69, "en", ("no", 1, "walks", "none", [], False, True),
      ["I can see flames on the ridge behind my house right now!", "The road's full of smoke.",
       "I've got a car but I don't think I can get through.", "It's just me."],
      expect={"role": "needs_ride", "escalation": "flames", "agentMustSay": "call 911"}),
    p("p17", "Nadia Farouk", 58, "en", ("no", 2, "walks", "one_person", [], False, True),
      ["My husband just collapsed, he's breathing but he won't wake up.",
       "Please, I need an ambulance.", "We have a car but I can't carry him."],
      expect={"role": "needs_ride", "escalation": "medical", "agentMustSay": "call 911"}),

    # ---- Can help a neighbor -------------------------------------------------------------
    p("p18", "Jake Morrow", 41, "en", ("yes", 3, "walks", "none", [], True, True),
      ["Yeah, we're packing now.", "Three of us, two kids.", "We've got a minivan, there's room.",
       "We could grab someone on the way down if they're close."],
      neighbor="the older lady two houses up, she uses a walker", expect={"role": "can_help"}),
    p("p19", "Priya Raman", 36, "en", ("yes", 2, "walks", "none", [], False, True),
      ["Hi, yes, we're leaving in ten minutes.", "Me and my partner.",
       "We have an SUV with the back seats down, we could fit a folding wheelchair."],
      expect={"role": "can_help"}),
    p("p20", "Luis Herrera", 45, "es", ("yes", 1, "walks", "none", [], False, True),
      ["Sí, ya me voy.", "Estoy solo, tengo una camioneta grande.", "Puedo llevar a dos o tres personas.",
       "Mi vecina, la señora de la casa azul, no tiene carro."],
      neighbor="la señora de la casa azul, no tiene carro", expect={"role": "can_help", "language": "es"}),
    p("p21", "Hannah Becker", 29, "en", ("yes", 1, "walks", "none", [], True, True),
      ["Yep, heading out.", "Just me and my dog.", "I drive a Subaru, I've got a back seat free."],
      expect={"role": "can_help"}),
    p("p22", "Dale Yazzie", 52, "en", ("yes", 2, "walks", "none", [], False, True),
      ["We're fine to go.", "I'm a retired EMT, my wife's with me.",
       "Pickup truck, I can lift someone if they need it.",
       "Mr. Fisk down the road is in a big power chair, I don't know if he's got a ride."],
      neighbor="Mr. Fisk down the road, big power chair", expect={"role": "can_help"}),
    p("p23", "Monica Sato", 47, "en", ("yes", 4, "walks", "none", [], True, True),
      ["Yes, we got the alert.", "Four of us and two cats.", "We have two cars, so one is free.",
       "My son is 19, he can drive one out."],
      expect={"role": "can_help"}),
    p("p24", "Rafael Ortiz", 38, "en", ("yes", 1, "walks", "none", [], False, True),
      ["Yeah, I work at the lodge, I'm leaving now.", "Just me.",
       "I've got the lodge's shuttle van keys, it seats twelve. I'd need someone to tell me where to go."],
      expect={"role": "can_help"}),

    # ---- Already out ---------------------------------------------------------------------
    p("p25", "Gail Thornton", 70, "en", ("yes", 2, "walks", "none", [], True, True),
      ["We're already in Sedona, at the high school.", "Both of us and the dog, we're fine."],
      expect={"role": "left"}),
    p("p26", "Bernard Coyle", 66, "en", ("yes", 1, "walks", "none", [], False, True),
      ["I left an hour ago, I'm in Flagstaff.", "House is empty."],
      expect={"role": "left"}),
    p("p27", "Ana Lucía Reyes", 33, "es", ("yes", 3, "walks", "none", [], False, True),
      ["Ya salimos, estamos en Cottonwood.", "Los tres estamos bien."],
      expect={"role": "left", "language": "es"}),
    p("p28", "Steve Kaminski", 55, "en", ("yes", 1, "walks", "none", [], False, True),
      ["This is a rental, I'm the owner. Nobody's staying there this week.", "I'm in Scottsdale."],
      expect={"role": "left"}),

    # ---- Staying / unsure / tricky -----------------------------------------------------
    p("p29", "Lyle Prescott", 73, "en", ("yes", 1, "walks", "none", [], True, True),
      ["I'm staying. I've got a sprinkler on the roof.", "I've been through the Slide Fire.",
       "I have a truck if it gets bad."],
      expect={"role": "stay", "agentMustSay": "leave now"}),
    p("p30", "Norma Jean Tate", 82, "en", ("unsure", 1, "walks", "one_person", [], True, True),
      ["I'm fine, honey, don't worry about me.", "Well, my knees aren't great.",
       "I have a car but my hands shake when I'm nervous.",
       "Actually, I'd rather someone drove me. Is that silly?"],
      correction="canLeave yes -> unsure; assistance none -> one_person", expect={"role": "needs_ride"}),
    p("p31", "Douglas Reed", 68, "en", ("yes", 1, "walks", "none", [], False, True),
      ["Is this a scam? How'd you get my number?", "Fine. I can leave. I have a car.",
       "I don't need anything from you."],
      expect={"role": "unknown", "note": "hostile/suspicious caller; agent stays calm, gives the safety line, ends politely"}),
    p("p32", "Imelda Cruz", 77, "es", ("no", 1, "walker", "one_person", [], True, False),
      ["¿Qué? No le oigo bien.", "Más fuerte, por favor.", "Vivo sola con mi gato.",
       "Uso andadera y no manejo."],
      tricky="hard of hearing", expect={"role": "needs_ride", "language": "es"}),
    p("p33", "Victor Lindqvist", 90, "en", ("no", 2, "walker", "two_person_lift", ["oxygen"], True, False),
      ["Hello, Victor speaking.", "My wife Elsa and me.", "She's on oxygen and she can't stand by herself.",
       "I use a walker. We'd both need help.", "And our old dog, Pepper. Please don't make us leave her."],
      tricky="won't leave without dog", expect={"role": "needs_ride", "need": {"seats": 2, "crew": 2}}),
    p("p34", "Chloe Abernathy", 24, "en", ("yes", 1, "walks", "none", [], False, False),
      ["Hi, I'm house-sitting, I don't have a car here.", "Just me.",
       "Can I walk down to Sedona? How far is it?"],
      expect={"role": "needs_ride"}),
    p("p35", "Arthur Bellamy", 85, "en", ("no", 1, "walks", "one_person", [], False, True),
      ["Yes, hello.", "I'm alone. My car's here.", "I had a small stroke in March, my right side is weak.",
       "I'm not supposed to drive.", "Will they be here before the fire? Promise me."],
      tricky="pushes for a promise", expect={"role": "needs_ride", "mustNotSay": ["promise", "before the fire"]}),
    p("p36", "Kenji Watanabe", 72, "en", ("yes", 2, "walks", "none", [], False, True),
      ["We're fine, we're loading the car.", "Two of us.",
       "Oh, and the man across the street, he's blind, lives alone. I don't know if anyone called him."],
      neighbor="the man across the street, he's blind, lives alone", expect={"role": "can_help"}),
    p("p37", "Sofía Martínez", 61, "es", ("yes", 2, "walks", "none", [], True, True),
      ["Hola, sí.", "Mi mamá y yo. Tenemos carro.", "Podemos llevar a alguien más si es cerca."],
      expect={"role": "can_help", "language": "es"}),
    p("p38", "Phyllis Grant", 80, "en", ("no", 1, "walker", "one_person", [], False, False),
      ["Hello?", "Sorry, what was the question?", "Oh. I live by myself. I don't drive.",
       "I use a walker, I can get to the door."],
      tricky="hard of hearing", expect={"role": "needs_ride"}),
    p("p39", "Mateo Salinas", 70, "es", ("no", 2, "manual_wheelchair", "one_person", [], False, False),
      ["Sí.", "Mi esposa y yo.", "Ella usa silla de ruedas. Yo no puedo manejar, mis ojos.",
       "Necesitamos ayuda."],
      tricky="speaks Spanish only", expect={"role": "needs_ride", "language": "es", "need": {"wheelchair": 1}}),
    p("p40", "Edna Pruitt", 87, "en", ("no", 1, "walker", "one_person", [], True, True),
      ["It's just me.", "Well, and my grandson is visiting, he's twelve.",
       "I have a car but he can't drive, and I can't anymore.", "And the dog."],
      correction="peopleCount 1 -> 2", expect={"role": "needs_ride", "need": {"seats": 2}}),
]


def validate(ps):
    ids = set()
    for x in ps:
        t = x["truth"]
        assert x["id"] not in ids, x["id"]
        ids.add(x["id"])
        assert x["language"] in {"en", "es"}
        assert t["canLeave"] in CAN_LEAVE, x["id"]
        assert t["mobility"] in MOBILITY, x["id"]
        assert t["assistance"] in ASSIST, x["id"]
        assert set(t["medical"]) <= MEDICAL, x["id"]
        assert isinstance(t["pets"], bool) and isinstance(t["hasCar"], bool)
        assert 1 <= t["peopleCount"] <= 30
        assert x.get("tricky") in TRICKY | {None}, x["id"]
        assert x["script"], x["id"]
        assert x.get("expect", {}).get("role", "unknown") in {"unknown", "needs_ride", "can_help", "left", "stay"}, x["id"]
    assert len(ps) == 40


if __name__ == "__main__":
    validate(PERSONAS)
    # Top-level JSON array: [{id, name, age, language, truth, script, correction?, tricky?, neighbor?, expect?}]
    out = PERSONAS
    path = Path(__file__).resolve().parent / "personas.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(PERSONAS)} personas to {path}")
