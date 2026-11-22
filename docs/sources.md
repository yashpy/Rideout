# Sources

Primary sources for the data the system runs on: the fire scenario (`data/scenario.json`), the Census rates behind
the simulated homes (`data/population.md`), and the published figures behind the simulation settings
(`docs/simulation.md`). Accessed 2026-11-14 unless noted. Where a source says "undetermined" or "under
investigation", so does the data.

## Scenario: Pocket Fire, Oak Creek Canyon (`data/scenario.json`)

| ID | Claim | Exact figure / wording | Outlet | Date | Link |
|---|---|---|---|---|---|
| S-01 | SR 89A closed between mileposts 374 and 397, both directions | MP 374–397 | FOX 10 Phoenix | 2026-06-23 | https://fox10phoenix.com/news/pocket-fire-burns-near-sedona-hot-windy-weather-challenges-crews |
| S-02 | Official summary: reported 5:01 p.m. June 19; ~7 mi N of Sedona; cause **undetermined (likely lightning)**; 27,393 acres; 1,238 peak personnel; 100% contained July 30; est. cost $62.3M; Red Flag event with gusts >50 mph; Oak Creek Canyon GO 6/19–6/23 then SET; Forest Highlands, Kachina Village, Pine Dell in SET; **no structures or homes lost**; SR 89A closed 25 days (6/19–7/13) | as listed | Coconino National Forest (USDA Forest Service), "Recent Large Wildfires" | accessed 2026-11-14 | https://www.fs.usda.gov/r03/coconino/fire/info/recent-large-wildfires |
| S-03 | First release: evacuations ordered, fire at 100 acres, SR 89A closed Fort Tuthill to north Sedona | 100 acres; posted 7:15 p.m. | City of Sedona (Coconino NF release) | 2026-06-19 | https://www.sedonaaz.gov/Home/Components/News/News/6845/473 |
| S-04 | Coconino County Sheriff gave GO Friday evening for all residents and visitors between Sedona and Forest Highlands; fire reported ~5 p.m. above the western rim of Oak Creek Canyon | — | KNAU Arizona Public Radio | 2026-06-19 | https://www.knau.org/knau-and-arizona-news/2026-06-19/wildfire-north-of-sedona-prompts-evacuation-orders-for-oak-creek-canyon |
| S-05 | Red Cross shelter at Sedona Red Rock High School, 995 Upper Red Rock Loop Rd, open by 10 p.m.; ~500 acres at ~9:20 p.m. (InciWeb) | 500 acres | KNAU; City of Sedona 6/21 update | 2026-06-19 / 06-21 | (S-04 link) · https://www.sedonaaz.gov/Home/Components/News/News/6851/473 |
| S-06 | GO order for Oak Creek Canyon posted 7:16 p.m.; zones 14 and 15 | 7:16 p.m. (Flagscanner). **Conflict:** TheWeather.com says the official GO came "around 10PM". Treat the minute as approximate | Flagscanner; TheWeather.com | 2026-06-19 | https://flagscanner.com/?p=59667 · https://www.theweather.com/news/trending/sedona-brush-fire-prompts-evacuations-and-road-closures-what-you-need-to-know.html |
| S-07 | 293 acres; 302 personnel; GO still in effect | 293 | City of Sedona daily update | 2026-06-21 | https://www.sedonaaz.gov/Home/Components/News/News/6851/473 |
| S-08 | 257 acres after better mapping | 257 | City of Sedona daily update | 2026-06-22 | https://www.sedonaaz.gov/Home/Components/News/News/6854/473 |
| S-09 | GO → SET at 8 a.m.; residents only with proof of residence; SE winds aligned with the canyon, gusts to 45 mph | 8:00 a.m.; 45 mph | City of Sedona daily update | 2026-06-23 | https://www.sedonaaz.gov/Home/Components/News/News/6856/473 |
| S-10 | ~1,187 acres | 1,187 | AZFamily / KOLD | 2026-06-25 | https://www.kold.com/2026/06/20/pocket-fire-burns-500-acres-north-sedona-sparks-evacuations/ |
| S-11 | 1,467 acres; 969 personnel; 0% contained | 1,467 | City of Sedona daily update | 2026-06-26 | https://www.sedonaaz.gov/Home/Components/News/News/6872/473 |
| S-12 | Grew past 6,000 acres from 2,349 the evening before, winds pushing it NE along FR 231 | 2,349 → 6,015 | KTAR (via repost); Ground News | 2026-06-28 | https://treefrogcreative.ca/?p=368973 · https://ground.news/article/pocket-fire-north-of-sedona-surges-to-6k-acres-0-contained |
| S-13 | Oak Creek Canyon, Kachina Village, Forest Highlands, Pine Del under evacuation warnings | — | KJZZ | 2026-06-30 | https://www.kjzz.org/text/fronteras-desk/2026-06-20/pocket-fire-latest-on-the-arizona-wildfire-near-oak-creek-canyon |
| S-14 | ~17,000 acres, 20% contained | "17K-acre" | AZFamily | 2026-07-01 | https://www.azfamily.com/2026/07/01/evacuation-status-adjusted-crews-work-contain-pocket-fire-near-sedona/ |
| S-15 | 27,440 acres; 1,296 personnel; 53% contained | 27,440 | City of Sedona daily update | 2026-07-08 | https://www.sedonaaz.gov/Home/Components/News/News/7897/473 |
| S-16 | SR 89A reopened; official 27,393 acres | 27,393 | City of Sedona | 2026-07-13 | https://www.sedonaaz.gov/Home/Components/News/News/7909/473 |
| S-17 | Oak Creek Canyon back to READY; 83% contained; ~678 personnel | — | AZFamily | 2026-07-14 | https://www.azfamily.com/2026/07/03/pocket-fire-scorches-over-23k-acres-near-sedona/ |

## Census (`data/population.md`)

| ID | Claim | Exact figure | Outlet | Date | Link |
|---|---|---|---|---|---|
| C-01 | Oak Creek Canyon (Census Tract 16.02, Coconino County) | 650 households; 1,197 housing units (45.7% vacant); 49.7% age 65+; 227 households = person 65+ living alone (34.9%); 12.1% ambulatory disability; 3.1% no vehicle; 7.8% Spanish-speaking households | U.S. Census Bureau, ACS 2019–2023 5-year (DP02, DP04, DP05, S1602, S1810) | accessed 2026-11-14 | https://data.census.gov/table/ACSDP5Y2023.DP02?g=1400000US04005001602 |
| C-02 | Sedona city | 5,039 households; 38.6% age 65+; 21.1% of households = 65+ living alone; 6.3% ambulatory disability; 1.4% no vehicle; 13.1% Spanish-speaking households | same | accessed 2026-11-14 | https://data.census.gov/table/ACSDP5Y2023.DP02?g=1600000US0465350 |
| C-03 | Arizona comparison | 18.6% age 65+ | same | accessed 2026-11-14 | https://data.census.gov/table/ACSDP5Y2023.DP05?g=0400000US04 |
| C-04 | Tract 16.02 contains Midgley Bridge, Slide Rock State Park and Pine Flat (Census geocoder) | — | U.S. Census Geocoder (ACS2023 vintage) | accessed 2026-11-14 | https://geocoding.geo.census.gov/geocoder/ |

## Simulation settings (`docs/simulation.md`)

| ID | Claim | Exact figure / wording | Outlet | Date | Link |
|---|---|---|---|---|---|
| F-13 | West Altadena's first evacuation order came at 3:25 a.m., after dispatch had at least 14 reports of fire there | 3:25 a.m.; ≥14 reports (911 logs obtained by the LA Times). **Note:** a 2026 Citygate review found "no failure" in the timing. Say "the order came after 14 reports of fire", not "officials failed" | LA Times (via FireRescue1); LAist (Citygate) | 2025; 2026 | https://www.firerescue1.com/emergency-management/report-criticizes-l-a-county-wildfire-response-muddled-evacuations-weak-coordination · https://laist.com/news/climate-environment/new-report-on-eaton-fire-evacuation-alerts-finds-no-failure-by-officials |
| F-18 | Even when a county calls its registry, it reaches only some | After Hurricane Beryl (2024), Harris County departments reached 605 of 1,030 STEAR registrants (59%) | Domestic Preparedness Journal | 2024 | https://www.domesticpreparedness.com/?p=72764 |
| F-14 | LA Fire Dept 911 volume during the fires | 3,624 calls in 24 hours vs. an average of "just under 1,500" | LAFD Chief Kristin Crowley, press conference (transcript) | 2025-01-08 | https://rev.com/transcripts/california-wildfire-press-conference |
