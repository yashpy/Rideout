# Population: Oak Creek Canyon and Sedona

The **Tract 16.02** column gives the rates for the simulated canyon homes. The Sedona column is a cross-check with smaller error bars. Sources: `docs/sources.md` (C-01 to C-04).

**Source:** U.S. Census Bureau, American Community Survey **2019–2023 5-year estimates** (tables DP02, DP04, DP05, S1602, S1810), pulled from data.census.gov on 2026-11-14.
The 2020–2024 5-year release has no data for this tract on data.census.gov yet, so 2019–2023 is the newest year with every column filled.

**Which tract:** the Census geocoder puts Midgley Bridge (lower canyon), Slide Rock State Park (mid) and Pine Flat (upper canyon) all inside **Census Tract 16.02, Coconino County, AZ** (GEOID 04005001602). That makes it a good stand-in for "Oak Creek Canyon".

## Rates table

| Measure | Tract 16.02 (Oak Creek Canyon) | Sedona city | Arizona | U.S. | ACS variable |
|---|---|---|---|---|---|
| Total households | **650** (±130) | 5,039 (±330) | 2,796,790 | 127,482,865 | DP02_0001E |
| Total housing units | **1,197** (±114) | 6,822 | — | — | DP04_0001E |
| Vacant housing units | **45.7%** (547) | 26.1% | — | — | DP04_0003PE |
| Population | 983 | 9,770 | 7,268,175 | 332,387,540 | DP05_0001E |
| **% of people age 65+** | **49.7%** (±13.7) | 38.6% (±3.6) | 18.6% | 16.8% | DP05_0024PE |
| **% of households = someone 65+ living alone** | **34.9%** (227 of 650) | 21.1% (1,064 of 5,039) | 11.9% | 11.6% | (DP02_0009E + DP02_0013E) / DP02_0001E |
| % of people 65+ who live alone | ~46% (227 of 489) | ~28% (1,064 of 3,773) | — | — | same numerator / DP05_0024E |
| **% with an ambulatory disability** (all ages) | **12.1%** (±6.9) | 6.3% (±2.2) | 6.8% | 6.7% | S1810_C03_047E |
| % of people 65+ with an ambulatory disability | 11.0% (±9.0) | 8.1% (±2.5) | 19.6% | 20.7% | S1810_C03_052E |
| **% of households with no vehicle** | **3.1%** (±3.2), 20 households | 1.4% (±0.9) | 5.4% | 8.3% | DP04_0058PE |
| **% of households speaking Spanish at home** | **7.8%** (±7.0), 51 households | 13.1% (±4.3) | 19.4% | 12.9% | S1602_C02_002E |
| Spanish-speaking households with limited English | 0 | 310 (6.2%) | 68,739 | 3,186,816 | S1602_C03_002E |

± is the ACS 90% margin of error. A tract of 650 households has wide margins, so treat these as approximate ("about half" rather than "49.7%").

## What this means for the stand-ins

- **The canyon is old.** About **half** of residents are 65+, **2.7×** the Arizona share (49.7% vs 18.6%). About **1 in 3 households** is a person 65+ living alone.
- **Cars aren't the main gap; help is.** Only ~3% of canyon households have no car. The risk is a 65+ person alone who can't walk out, can't drive in smoke, or can't lift a spouse. That is exactly the Rosa persona.
- **Spanish matters less in the canyon than in Sedona.** ~8% of canyon households speak Spanish at home, ~13% in Sedona. Keep Spanish in the agent, but weight canyon stand-ins around 8%.
- **Many homes are empty.** 46% of units are vacant (seasonal or short-term rentals). In the sim, a share of homes should be "no answer because nobody lives there", which is exactly why "silence is never safe" needs a door-knock list.

## Suggested sampling rates for the simulated homes (200)

| Field | Rate to sample | Basis |
|---|---|---|
| Household has someone 65+ | 0.60 | ~50% of people are 65+ and many households are 1–2 people (assumption from the rates above) |
| 65+ and living alone | 0.35 | 34.9% of households |
| Ambulatory disability in household | 0.15 | 12.1% of people ±6.9; rounded up because it counts per person, not per household (assumption) |
| No vehicle | 0.03 | 3.1% |
| Spanish at home | 0.08 | 7.8% |
| Unoccupied (no answer) | 0.25 | Fewer than the 46% vacancy, so most simulated calls are answered (assumption; simulated) |

Rows marked *assumption* are modeling choices, not Census numbers.
