# RideOut — VillageHacks Lite '26 Submission Kit

## 2. ElevenLabs: present? YES
- Real phone calls: ElevenLabs Conversational AI listens and speaks (matched by conversation id).
- /calls/dial returns 503 when it isn't configured. Simulated homes use stand-in voices.
- Missing and worth adding: **Spanish voice proof in the video**, plus ElevenLabs TTS for the callback ("a wheelchair van is 7 minutes away, driver is Luis"). Show one real phone ringing live. That's the moment that wins demos.

## 3. Description (paste into the form)
**Problem:** When a wildfire evacuation order goes out, the people who can't drive out (wheelchair users, bedbound people, people without a car) get help last. Dispatch learns who needs a ride one phone call at a time while the lines are jammed. LAFD took 3,624 calls in 24 hours during the Jan 2025 fires. After Hurricane Beryl, Harris County reached only 59% of its own registry by phone.
**Solution:** RideOut calls every home in the zone at the same time with an AI voice agent (ElevenLabs + Gemini, English/Spanish) and turns the answers into a live census. A matcher sends responder vans and neighbor volunteers to the riders with the earliest fire deadlines first, with elderly, wheelchair and stretcher riders prioritized and no vehicle over its seats. In our North Scottsdale simulation (6,000 homes), 16 of 17 riders got out before the fire. RideOut runs on any phone, including basic feature phones with no app or internet. That makes it work in remote places 911 can't reach in time and in developing countries with no central emergency dispatch.


## 3b. Use-case scenarios to demo

### Scenario A: Elderly first (feature already built)
- **Setting:** North Scottsdale, Pocket-Fire-style warning, zone goes to SET.
- **Who:** Margaret, 82, lives alone, uses a walker, has no car.
- **Flow:** The AI calls her landline. She says "I'm 82, I can't drive, I use a walker." Gemini records her age, mobility, and that she has no car. The matcher ranks her ahead of able-bodied riders with the same fire deadline. A dispatcher approves, a neighbor volunteer accepts, and she gets the callback: "Luis is coming in a car, 6 minutes away."
- **What to show:** her row moves to the top of Open requests, with an elderly/mobility tag. On the map her pin goes from "needs a ride" to "picked up" to "shelter".
- **Line for the video:** "The oldest and least mobile people aren't left until last. RideOut gets to them first."

### Scenario B: Remote places 911 can't reach
- **Setting:** Oak Creek Canyon, Arizona, or a Navajo Nation chapter. One road in, the nearest station 45+ minutes away, weak cell coverage.
- **Problem:** 911 dispatch gets a call that is already too late, and crews can't knock on every door along a 14-mile canyon.
- **Flow:** RideOut calls every home along the canyon road at the same time, in English, Spanish, or Navajo. Residents with trucks offer seats, and the matcher pairs them with neighbors who can't leave (Close a road shows rerouting when 89A is blocked). Homes that never answer go on the door-knock list for the one available crew.
- **What to show:** Oak Creek Canyon on /console. Close a road, press Solve, watch volunteers being assigned. Real figure: 1 in 8 residents has an ambulatory disability, and half are 65+.
- **Line:** "Where help is 45 minutes away, the fastest responder is the neighbor with a truck. RideOut finds them."

### Scenario C: Developing countries (floods and cyclones)
- **Setting:** a coastal village in Bangladesh, Mozambique, or the Philippines before a cyclone lands. No 911, no dispatch software. Many people own basic feature phones.
- **Flow:** a local NGO or district officer starts a zone. The voice agent calls every number in the village registry in the local language (ElevenLabs multilingual voices). The census shows who is elderly, disabled, or pregnant, and who owns a boat, tuk-tuk, or truck. The matcher sends community vehicles to cyclone shelters. It works over plain voice calls, with no app and no internet for residents.
- **Business angle:** sold to NGOs and national disaster agencies, paid from humanitarian and climate-adaptation funds. Per-call cost stays low, and there are no smartphones to buy.
- **Line:** "Most of the world doesn't have 911. Almost everyone has a phone. RideOut turns that phone into an evacuation plan."

### Rule to say out loud
Priority order: wheelchair/stretcher, then elderly, then everyone else without a ride. Within each group, the earliest fire deadline goes first. No vehicle ever goes over its seats or wheelchair spaces.

## 4. How it makes money
- **Customer:** county emergency management offices (about 3,000 US counties), fire districts, and utilities running PSPS shutoffs. Secondary: senior-living operators and hospitals that have evacuation-plan mandates (CMS Emergency Preparedness Rule).
- **Pricing:** SaaS priced by population. About $0.10 per resident per year, so a 250k-person county pays about $25k/yr. Includes unlimited drills. Live-event calling is metered at cost +30%. Mid-term: a state contract covers every county in the state.
- **Global customers:** NGOs and aid agencies (Red Cross/Red Crescent, IFRC, UN OCHA, World Food Programme) and national disaster agencies, paid through humanitarian and climate-adaptation funds (World Bank, Green Climate Fund). Tribal nations and rural US counties qualify for FEMA tribal and rural grants.
- **Funding paths:** FEMA BRIC / HMGP and EMPG grants pay for exactly this, so the buyer doesn't need new budget.
- **Main costs:** voice minutes (about $0.08–0.10/min x ~1.5 min per home, which only comes up during events and drills), LLM tokens, telephony (Twilio), hosting (MongoDB Atlas, Render), and sales/compliance (CJIS-style security, accessibility). Gross margin on SaaS: about 80%.

## 5. Scalability (say this explicitly)
- Calls run in parallel and stateless, so 200 homes or 20,000 homes takes the same wall-clock time. Telephony scales horizontally.
- Costs are event-driven: idle counties cost almost nothing (one shared multi-tenant DB, static frontend on Vercel).
- The batched matcher is near-linear per zone, and zones are solved independently, so it shards by county.
- Same engine works for hurricanes, floods, and chemical spills. More disasters, same product.
- Works on voice calls to any phone, so new regions need no app installs and no smartphones. A new country only needs a local phone number and a voice language.

## 6. 5-minute video script
- 0:00–0:30 **Hook:** "In January 2025, LA's fire department got 3,624 calls in one day. The people who couldn't drive out were waiting on hold." Show the stat card.
- 0:30–1:00 **Who's affected:** 1 in 8 Oak Creek Canyon residents has an ambulatory disability. A registry plus phone calls reached only 59%.
- 1:00–3:00 **Live demo:** /console, zone set to SET, 200 homes called at once. Ring a REAL phone, answer in Spanish ("mi mamá usa silla de ruedas"). The census map updates live. Press Solve, approve, the driver accepts on a phone, and the callback plays. Show Margaret, 82, jumping to the top of the queue (elderly priority). Then Play evacuation: 16/17 out before the fire.
- 3:00–3:30 **Beyond the suburbs:** Scenario B (Oak Creek Canyon, close a road) and Scenario C (a feature-phone call to a cyclone village). "Most of the world has no 911, but almost everyone has a phone."
- 3:30–3:45 **Scale + tech:** parallel calls, change streams, the matcher, eval accuracy numbers.
- 3:45–4:30 **Business:** counties, about $0.10/resident/yr, FEMA grant-funded, about 80% margin.
- 4:30–5:00 **Close:** "Everyone gets a safe seat out." Show the links.

## 7. Links
Demo: https://rideout-nine.vercel.app/console · API: https://rideout-api-grg6.onrender.com/docs · Code: https://github.com/yashpy/rideout (private, so add the judges or make it public before 1:00 AM)
