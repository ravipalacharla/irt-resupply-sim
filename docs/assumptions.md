# Assumptions

All values are invented or taken from public sources. Each entry says where it came from.

## Simulation design

| # | Assumption | Source |
|---|---|---|
| D1 | Each simulated trial (patients, visits, dropouts) is generated once, then both reorder rules run on that same trial. | Design choice |
| D2 | A stockout is recorded but does not change the patient's visit schedule or cause a dropout. Keeps both rules facing identical demand. | Simplification |
| D3 | The simulation moves in 1-week steps. Visits, lead times, and expiry checks round to the week. | Simplification |
| D4 | One kit type per arm. No blinding logic. | Scope |

## Trial structure

| # | Assumption | Source |
|---|---|---|
| T1 | Sites belong to countries; countries belong to regions. | Design choice |
| T2 | A country's approval date sets the earliest date its sites can open. Sites in one country open close together. | Design choice |

## Enrollment

| # | Assumption | Source |
|---|---|---|
| E1 | Each site has its own steady enrollment pace. Paces vary widely: many slow sites, a few fast ones (Gamma distribution). | Enrollment-forecasting literature |
| E2 | Weekly enrollment at a site varies randomly around its pace (Poisson). | Enrollment-forecasting literature |
| E3 | Sites ramp up slowly after opening, then settle at their steady pace. | Domain experience (generic) |
| E4 | 18% of sites stumble: their pace is cut to 10% of normal. About 15% of sites end up with zero patients. | Domain experience (generic) |
| E5 | Enrollment stops when the trial reaches its target. | Standard practice |

## Supply

| # | Assumption | Source |
|---|---|---|
| S1 | Shelf life is set in months; each lot has a real expiry date. Converted to a week index inside the simulation. | Design choice |
| S2 | A kit cannot be handed out if it expires before the patient's next visit (minimum remaining shelf life). Such kits count as waste. | Design choice |
| S3 | Shipping time from depot depends on region: North America 1 week, Europe 2, Asia-Pacific 3. Fixed, no delays. | Invented |

## Phase 1 values (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| P1 | 78 sites in 10 countries, 3 regions. Target 500 patients. 3-year horizon. | Invented, phase 3 oncology scale |
| P2 | Country approval at a random week 4-30. Site opens on average 6 weeks after (exponential, so some open very late). | Invented |
| P3 | Steady pace averages 0.12 patients/site/week (~0.5/month); ramps up in a straight line over 12 weeks. | Invented, typical oncology range |
| P4 | Arm assigned by independent 1:1 random draw per patient (no block randomization). | Simplification |
| P5 | No screen failures modeled; every enrolled patient gets a kit at enrollment. | Simplification |
| P6 | Dispensing visit every 4 weeks, 1 kit per visit. **Superseded by V1-V4** (visit windows). | Invented |
| P7 | Time on treatment (any stop reason): median 40 weeks, protocol max 104 weeks. | Invented |
| P8 | In the week the target is reached, the extra patients are dropped at random so the total is exactly 500. | Simplification |

## Phase 2 values (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| N1 | One central depot with unlimited stock. Depot stockouts and depot waste are not modeled. | Simplification |
| N2 | A new lot of each arm's kit is released every 6 months, already 3 months old. Shelf life 24 months from manufacture. | Invented |
| N3 | Depot always ships the newest released lot. | Simplification |
| N4 | Sites hand out the earliest-expiring kits first. | Standard practice |
| N5 | A kit is removed as expired once it would expire before the next visit (4 weeks). | Design choice (see S2) |
| N6 | Min/max runs per site, per arm: if on hand + in transit <= 2, top up to 5. Values are illustrative, not tuned. | Invented |
| N7 | ~~Each arm reorders on its own.~~ **Superseded by T1** (both arms topped up in one box). | Simplification |
| N8 | The rule starts at (site opening - lead time), so the first box arrives on opening day. | Design choice |
| N9 | No new shipments once enrollment is closed and a site has nobody on treatment. Kits already there stay until the end ("left at end"). | Simplification |
| N10 | ~~The trial is cut off at week 156.~~ **Superseded by H1** (run to the last visit). | Simplification |

## Phase 3: forecast rule (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| F1 | Forecast = average kits needed per week at the site/arm over the last 8 weeks. Uses only weeks up to the current one. | Design choice |
| F2 | Target stock = average x (lead time + 1) + 1.65 x weekly spread x sqrt(lead time + 1). Reorder whenever stock (on hand + in transit) is below target. | Standard safety-stock formula |
| F3 | While enrollment is open, target is at least 2 kits, same as the min/max floor, so a new patient can be served. | Design choice |
| F4 | Comparison is paired: both rules on the same 200 trials; report mean difference and 95% interval (1.96 x standard error). | Standard practice |
| F5 | Min/max values (2/5) are one fixed setting, not tuned per region or site. A tuned min/max would be a stronger baseline. | Limitation |
| F6 | Tuned min/max: one (MIN, MAX) per region, picked on 30 separate tuning trials (seeds 10000-10029), never on the 200 scoring trials. Grid MIN 1-10, MAX = MIN+1..MIN+8. | Design choice |
| F7 | Tuning rule: among settings short no more kits than the forecast rule (per region, tuning trials), take the fewest expired, then fewest shipments. If none qualifies, take the fewest short. | Design choice (avoids weighting a stockout against an expired kit) |
| F8 | Result: North America (4, 5), Europe (6, 8), Asia-Pacific (10, 15). Asia-Pacific hit the edge of the grid without matching the forecast rule's service, so its setting is "closest service", not "matched service". | Tuning output |

## Stress test scenarios (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| X1 | Three scenarios: base (no shock), surge, stall. 200 trials each, same seeds. | Design choice |
| X2 | Surge: 30% of sites enroll at 3x their pace for 12 weeks. | Invented (e.g. competing trial closes, referral push) |
| X3 | Stall: 30% of sites enroll nobody for 16 weeks, then resume. Patients already on treatment keep their visits. | Invented (e.g. enrollment hold, staff loss) |
| X4 | All hit sites are hit in the same week, drawn between weeks 26 and 70 (mid-enrollment). Hitting together is harder than scattered shocks. | Design choice |
| X5 | The shock uses its own random stream, so a shocked trial is the base trial with the same seed plus the shock. | Design choice (keeps scenarios comparable) |
| X6 | No rule is re-tuned for the shocks; tuned min/max keeps its base-scenario settings. | Design choice (the point of the test) |

## Schedule-based rule (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| R1 | The rule knows the visit schedule of patients on treatment now (every 4 weeks from enrollment, up to the 104-week maximum). A real system knows these dates. | Standard practice |
| R2 | It assumes every patient on treatment keeps going; it does not know who will stop early. | Design choice (no peeking) |
| R3 | New-patient rate = site's patients enrolled per week over the last 8 weeks, x arm share. | Design choice |
| R4 | Spare kits for new patients = expected new + 1.65 x sqrt(expected new) (Poisson spread), at least 2 while enrolling, 0 after enrollment closes. Uses the same cushion (1.65) and floor (2) as the forecast rule, so the two differ in what they know, not how cautious they are. | Design choice |
| R5 | First version applied the floor to the total target, leaving no spare kit at sites with patients already on treatment (~18 kits short per trial). Changed to apply the floor to spare kits only (~3 short). Found and fixed on tuning trials (seeds 10000+), not scoring trials. | Design iteration |
| R6 | Tuned min/max was matched to the forecast rule's service level, not the schedule rule's (which is higher). | Limitation |

## ML rule (all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| M1 | Model: LightGBM gradient-boosted trees, Poisson objective (predicts counts). Chosen as the most proven ML method for lumpy demand (M5 competition, retail and commercial demand forecasting). | Literature |
| M2 | Target: kits needed at a site/arm h weeks ahead (h = 1-8). Inputs: only facts known at the current week (scheduled visits, recent use, recent enrollment, patients on treatment, trial progress, site age, shipping time, region, arm). | Design choice (no peeking; tested) |
| M3 | Trained on 40 separate trials (seeds 20000-20039), base scenario only; 8 held out for early stopping. Never retrained for scenarios or knobs. | Design choice |
| M4 | Ordering uses the schedule rule's structure (booked + spare kits, floor 2 while enrolling, 0 spare after closing), so results differ only by the forecast. | Design choice (fair comparison) |
| M5 | Predictions are made in one batch per trial before the weekly loop. Valid because the inputs depend only on the trial, not on shipping decisions. | Implementation (speed) |
| M6 | First version added spare kits after enrollment closed; changed to 0 to match the schedule rule. Found on tuning trials. | Design iteration |
| M7 | The model learns patterns of our own generator (circular validation, scope section 9). Any win is "under these assumptions". | Limitation |

## Realism pass (2026-10-25; all in `sim/config.py`)

| # | Assumption | Source |
|---|---|---|
| V1 | Cycle-based visits: each 4-week cycle is counted from the previous actual visit, so delays accumulate. | Typical oncology cycles |
| V2 | Each visit: 70% in its planned week, 15% one week early, 15% one week late. | Invented (~+/-7 day window) |
| V3 | 2% of visits are missed: no kit; the next cycle is counted from the missed visit's planned week. | Invented |
| V4 | Rules know each patient's planned next visit (last actual visit + 4 weeks), not its shift. An overdue planned visit is expected the following week; a missed visit is recognised one week after its planned week. | Design choice (no peeking) |
| G1 | Country effect: sites in a country share a log-normal pace multiplier (sd 0.3, average 1). | Invented |
| G2 | Pace drift: each site's pace follows a log random walk from opening (sd 0.03 per week), with no upward bias. | Invented |
| G3 | Bursts: 5% of site-weeks enroll at 4x pace; other weeks scaled so the long-run average is unchanged. | Invented |
| G4 | G1-G3 exist so the Bayesian Gamma-Poisson rule faces data it does not perfectly match (scope section 9). Net effect: enrollment 97 weeks on average (was 92). | Design choice |
| H1 | Each trial runs until its last patient's last visit (about weeks 200-220; max horizon 260). Close-out is included. | Design choice |
| T1 | One box per site per week: if either arm orders, the other arm is topped up to its target in the same box. Never adds a box. | Standard practice |
| B1 | Bayesian rule prior: Gamma(0.84, 8.58) on site pace, fitted by method of moments on the 40 ML training trials (removing Poisson noise from short exposure). | Anisimov & Fedorov (2007) method |
| B2 | Exposure counts ramp-up weeks partly (week k after opening counts min(1, (k+1)/12)), the ramp-up profile a planner would assume. | Design choice (uses the generator's ramp-up length) |
| B3 | New patients for one arm over the cover window ~ negative binomial (Gamma-Poisson predictive, thinned by arm share). Spare kits = 95% quantile, at least 2 while enrolling, 0 after closing. | Standard |
| B4 | The model assumes a constant pace per site; it does not model drift, country effects, or bursts. | Limitation (intended) |
