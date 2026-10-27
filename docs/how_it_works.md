# How it works

Plain-English guide to what this project does and how. For the exact numbers behind each
step, see `docs/assumptions.md`. For how to run things, see `docs/workflow.md`.

---

## Methods at a glance

| Method | Status | Where | What it does here |
|---|---|---|---|
| **Gamma-Poisson enrollment model** | Built | Trial generator (`sim/generator.py`), section 3 | Gives each site its own enrollment pace (Gamma: many slow sites, a few fast) and random weekly patient counts around that pace (Poisson). The standard model in published clinical enrollment forecasting. Country effects, pace drift, and bursts are added on top for realism. |
| **Monte Carlo simulation** | Built | Runner (`sim/run.py`), sections 2, 6–8 | Runs 200 random trials per scenario and replays each under every reorder rule. Results are averages and 95% ranges across those trials. This is how every rule, including ML, is tested. |
| Min/max reorder rules | Built | `sim/policies/minmax.py`, `minmax_tuned.py`, section 5 | Fixed reorder trigger and refill level (plain arithmetic). |
| Rolling-average forecast rule | Built | `sim/policies/forecast.py`, section 5 | Recent average use + standard safety-stock formula (plain arithmetic). |
| Schedule-based forecast rule | Built | `sim/policies/schedule.py`, section 5 | Planned visits of patients on treatment + spare kits for new patients (plain arithmetic). The baseline ML must beat. |
| **Bayesian Gamma-Poisson forecast** | Built | `sim/bayes.py`, `sim/policies/schedule_bayes.py`, section 5 | Updates each site's enrollment pace estimate as patients arrive (prior + data = posterior) and forecasts new patients as a probability distribution. Used for the spare kits in the schedule + Bayesian rule. |
| **Gradient-boosted trees (LightGBM)** | Built | `sim/ml.py`, `sim/train_ml.py`, `sim/policies/ml.py`, section 5 | Machine-learning forecast of weekly kit need, used inside a reorder rule and tested with the same Monte Carlo runs. |

Monte Carlo and ML are not alternatives: Monte Carlo is the test track, and each reorder rule
(including the ML one) is a driver tested on it.

---

## 1. The question

A clinical trial ships drug kits from a depot to sites. Send too few and a patient arrives
with no kit (a **stockout**). Send too many and kits sit on the shelf until they **expire**.

We compare different **reorder rules** — the rule that decides, each week, whether to
ship kits to a site and how many — and ask:

> Under the same trials, which rule gives fewer stockouts, less waste, and fewer shipments?

Everything is made up (synthetic). The point is to compare rules fairly, not to predict
any real trial.

---

## 2. The big picture

```mermaid
flowchart LR
    A[config.py<br/>all settings + seed] --> B[Make one trial<br/>generator.py]
    B --> C1[Replay with<br/>min/max]
    B --> C2[Replay with<br/>tuned min/max]
    B --> C3[Replay with<br/>forecast]
    C1 & C2 & C3 --> D[Score each rule<br/>metrics.py]
    D --> E[(Postgres<br/>irt_sim)]
    D --> F[Compare rules<br/>across 200 trials]
```

1. **Make a trial.** Invent sites, patients, and visits.
2. **Replay it under each rule.** Same patients, same visits, only the shipping decisions differ.
3. **Score each rule.** Count stockouts, expired kits, shipments, stock on hand.
4. **Repeat 200 times** with different random trials.
5. **Compare.** For each trial, take rule B's score minus rule A's score, then average.

Because every rule faces the exact same trials, any difference comes from the rule, not
from one rule getting an easier trial.

### Is this a Monte Carlo simulation?
Yes. "Monte Carlo" just means: run the same experiment many times with random inputs, then
look at the average and the spread of the outcomes. Here, one experiment = one made-up trial
replayed under each rule. We run 200 of them per scenario. The 95% ranges in the results come
from how much the outcome varies across those 200 trials.

### Is this machine learning?
One rule is. Four rules are plain arithmetic: comparing counts to fixed numbers (min/max), an
average of recent weeks plus a standard safety-stock formula (forecast), or known visits plus
spare kits (schedule). "Tuning" min/max means trying 80 combinations and keeping the best one;
nothing is trained. The fifth rule (ML) uses a LightGBM model trained on separate made-up
trials to predict how many kits each site will need (Rule 5 in section 5).

---

## 3. Making a trial (`sim/generator.py`)

### Sites, countries, regions
78 sites in 10 countries in 3 regions (North America, Europe, Asia-Pacific).

### When sites open
- Each **country** gets an approval week (somewhere in weeks 4–30).
- Each **site** opens some weeks after its country is approved (6 weeks on average; a few
  open very late).

### How fast sites enroll
Each site gets its own life story:

| Stage | What happens |
|---|---|
| Startup | Site opens and enrolls slowly; pace climbs over its first 12 weeks. |
| Auto pilot | Site settles at its own steady pace. Most sites are slow, a few are fast. |
| Stumbling | About 1 in 6 sites never really gets going (pace cut to 10%). |
| Stop | Everyone stops enrolling once the trial reaches 500 patients. |

Week to week, enrollment at a site is random around its pace — a site averaging one
patient a month will see some months with 0 and some with 2 or 3.

*How:* a site's steady pace is drawn from a Gamma distribution (gives many slow sites and a
long tail of fast ones). Weekly counts are drawn from a Poisson distribution (the standard
model for random arrivals).

### Real-world messiness on top
Three things make enrollment less tidy than a pure Gamma-Poisson model. They are there on
purpose, so that the Bayesian rule (which assumes pure Gamma-Poisson) is tested on data it
does not perfectly match, as in real life:

| Effect | What happens | Real-life cause |
|---|---|---|
| Country effect | All sites in a country share a pace multiplier (some countries faster, some slower) | Standard of care, referral networks |
| Pace drift | Each site's pace slowly wanders up or down over time | Staff turnover, fatigue, competing trials |
| Bursts | In about 5% of weeks a site enrolls at 4x its usual pace | Tumor boards, referral batches |

Each is built so the long-run average pace is unchanged; they add spread and surprises, not speed.

### Patients and visits
- Each patient is randomly assigned to arm A or B (50/50). Each arm has its own kit.
- A patient gets 1 kit at enrollment, then 1 kit at the start of each 4-week cycle.
- **Visit windows, cycle-based:** each cycle is counted from the previous *actual* visit, so
  delays add up (as with oncology cycles and dose delays). Each visit lands:
  - 70% in its planned week, 15% a week early, 15% a week late.
- **Missed visits:** 2% of visits are skipped. No kit that week; the next cycle is counted
  from the planned week of the missed one.
- Patients stop treatment at random (half stop within 40 weeks) or at the 104-week maximum.

### Result
On average enrollment takes about 97 weeks (75-118), the cumulative curve is S-shaped (slow
start, steady middle, flat end), the top 20% of sites enroll about 55% of the patients, and
about 16% of sites enroll nobody.

### How long a trial runs
Each trial is simulated until its **last patient's last visit** (around week 200-220), so
site close-out and the kits left over at the very end are counted. The simulation allows up
to 260 weeks and checks every trial fits.

---

## 4. Supplying the sites (`sim/network.py`)

### Kits and lots
- One central depot with unlimited stock.
- A new lot of each arm's kit is released every 6 months. Each lot expires 24 months after
  it was made. The depot always ships the newest lot.
- A site will not hand out a kit that expires before the patient's next visit (4 weeks).
  Such kits are removed and counted as **expired**.

### Shipping time
North America 1 week, Europe 2 weeks, Asia-Pacific 3 weeks. Fixed.

### What happens every week, at every site (both arms together)

1. **Receive** any shipment due this week.
2. **Remove** kits that would expire before the next visit (counted as expired).
3. **Hand out** kits to this week's visits, earliest expiry first. If there are not enough,
   the gap is counted as **kits short** (a stockout). The visit still happens — we do not
   delay or drop the patient, so every rule faces the same demand.
4. **Ask the reorder rule**, for each arm, how many kits to send.
5. **One box per site:** if either arm orders, the other arm is topped up to its target in
   the same box (if it is below target). This never adds a box, and matches how real
   resupply works. The box arrives after the region's shipping time.

The rule starts working one shipping-time before the site opens, so the first box lands on
opening day. It stops once enrollment is closed and the site has nobody left on treatment.

---

## 5. The reorder rules (`sim/policies/`)

A **reorder rule** decides, once a week, for each site and each arm: ship kits or not, and
how many. That is the only thing that differs between the runs of a trial (one run per rule).

### What every rule can see (and cannot)

The simulator hands every rule the same bundle of facts each week (called `known` in the
code). Each rule uses only the parts it needs.

| Can see (this week and earlier) | Used by | Cannot see |
|---|---|---|
| Kits on hand, kits in transit | all rules | Any future week's actual demand |
| Kits the site needed each week so far | forecast | Who will enroll next |
| Patients enrolled at the site each week so far | schedule | Which patients will stop early |
| Planned week of each on-treatment patient's next visits (from their last actual visit), assuming they all keep going | schedule, schedule + Bayesian, ML | Whether a visit will land early, on time, or late; who will miss a visit; which sites will stumble or surge |
| Shipping time, region, arm, weeks since opening, enrollment open or closed | all / some | |

The visit schedule counts as known because a real system knows when each enrolled patient's
next visit is *planned*: one cycle after their last actual visit. It does not know whether
the visit will land a week early or late, or be missed. If a planned week passes with no
visit, the rule expects it the following week (still inside its window). A missed visit is
recognised once its window has closed. The rule also cannot know who will drop out, so it
assumes everyone keeps going.

Two tests check that no rule peeks ahead: erase everything after week 60 (future visits,
future patients, future end dates) and confirm that no decision before week 60 changes.

**Stock position** = on hand + in transit. All rules work from this number, so a box already
on the way is never ordered twice.

Every rule returns two numbers: how many kits to order, and its **target stock** (the stock
position it is aiming for). The target is saved each week for the dashboard.

### Current settings at a glance

| Rule | Code | Settings (`sim/config.py`) |
|---|---|---|
| Min/max | `minmax.py` | MIN 2, MAX 5, every site |
| Tuned min/max | `minmax_tuned.py` | North America 4/5, Europe 8/10, Asia-Pacific 9/12 (`MINMAX_TUNED`) |
| Forecast | `forecast.py` | Look back 8 weeks, cushion 1.65, floor 2 while enrolling |
| Schedule | `schedule.py` | Visits due in next (shipping + 1) weeks, + spare kits for new patients (cushion 1.65, at least 2 while enrolling) |
| Schedule + Bayesian | `schedule_bayes.py` | Planned visits in next (shipping + 1) weeks, + spare kits = 95% cap on new patients from each site's Bayesian pace estimate (at least 2 while enrolling) (`BAYES_PRIOR`, `BAYES_QUANTILE`) |
| ML | `ml.py` | LightGBM-predicted need over next (shipping + 1) weeks, same spare-kit logic as Schedule (`ML_PARAMS`) |

All rules also follow two shared rules from the supply side (section 4): start one shipping
time before the site opens, and stop once enrollment is closed and the site has nobody on
treatment.

### Rule 1: Min/max

**In words:** if stock position is at or below MIN, order enough to bring it back to MAX.
Otherwise do nothing.

**Example** (MIN 2, MAX 5):

| Week | On hand | In transit | Position | Decision |
|---|---|---|---|---|
| 10 | 4 | 0 | 4 | 4 > 2, no order |
| 11 | 3 | 0 | 3 | 3 > 2, no order |
| 12 | 2 | 0 | 2 | 2 <= 2, order 5 - 2 = **3** |
| 13 | 1 | 3 | 4 | 4 > 2, no order (box already on the way) |

**Strength:** simple, predictable, ships in batches.
**Weakness:** the same two numbers everywhere. Too low for a busy site far from the depot
(runs out while waiting for a box), too high for a slow site (kits sit until they expire).

### Rule 2: Tuned min/max

**In words:** exactly Rule 1, but each region has its own MIN and MAX.

| Region | Shipping time | MIN | MAX |
|---|---|---|---|
| North America | 1 week | 4 | 5 |
| Europe | 2 weeks | 8 | 10 |
| Asia-Pacific | 3 weeks | 9 | 12 |

**How the numbers were picked** (`sim/tune_minmax.py`):
1. Make 30 practice trials, separate from the 200 scoring trials (otherwise the rule would be
   graded on the same test it studied for).
2. Try every MIN from 1 to 10, with MAX from MIN+1 to MIN+8 (80 combinations).
3. For each region, keep combinations that ran short no more often than the forecast rule.
4. Of those, pick the one with the fewest expired kits (then fewest shipments).
5. Every region found a setting that matched the forecast rule's service. (Before the visit
   windows were added, Asia-Pacific could not match it even at 10/15.)

**Strength:** fixes most of Rule 1's stockouts.
**Weakness:** still one setting for every site in a region, so a busy site and a dead site get
the same 9-12 kits. That is where its waste comes from.

### Rule 3: Forecast

**In words:** look at how many kits this site needed per week over the last 8 weeks.
Keep enough to last until the next box could arrive, plus a safety cushion. If stock position
is below that target, order the difference.

**The formula:**

```
cover   = shipping weeks + 1        (the +1: next chance to reorder is next week)
average = mean kits needed per week, last 8 weeks
spread  = how much weekly need bounces around (standard deviation), last 8 weeks

target  = average x cover  +  1.65 x spread x sqrt(cover)
          \_____________/     \__________________________/
           expected use         safety cushion (~95% of weeks covered)

while enrollment is open: target is at least 2 (so a new patient can always get a kit)
target is rounded up to a whole kit
order   = target - position, if position < target; otherwise 0
```

**Example:** Asia-Pacific site (3-week shipping), one arm. Kits needed over the last 8 weeks:
1, 0, 0, 1, 1, 0, 0, 1.

| Step | Value |
|---|---|
| cover | 3 + 1 = 4 weeks |
| average | 4 kits / 8 weeks = 0.5 per week |
| spread | 0.5 |
| expected use | 0.5 x 4 = 2.0 |
| cushion | 1.65 x 0.5 x sqrt(4) = 1.65 |
| target | 2.0 + 1.65 = 3.65, rounded up to **4** |
| position | 1 on hand + 1 in transit = 2 |
| order | 4 - 2 = **2 kits** |

A quiet site (nothing needed for 8 weeks) gets target 0, raised to the floor of 2 while
enrollment is open. A busy site's target rises on its own as its use goes up.

**Strength:** each site gets stock matched to its own recent use, so busy sites get more and
quiet sites get little. Far less stock and waste.
**Weakness:** it reorders small amounts almost every week, so it sends many more boxes. It
also only reacts to the past: a sudden jump in need shows up in the average only after it
has happened.

### Rule 4: Schedule-based

**In words:** count the kits already booked: the visits due in the coming weeks for patients
on treatment now. Add spare kits for patients who might enroll. Order the difference.

**The formula:**

```
cover     = shipping weeks + 1                           (same as forecast)
scheduled = kits due in the next `cover` weeks for patients on treatment now
new       = site's new patients per week (last 8 weeks) x arm share (50%) x cover
spare     = new + 1.65 x sqrt(new), but at least 2 while enrolling; 0 once enrollment closes
target    = scheduled + spare, rounded up
order     = target - position, if position < target; otherwise 0
```

**Example:** Europe site (2-week shipping, so cover = 3 weeks), arm A. Patients on treatment
have visits due: 1 kit next week, 0 the week after, 2 the week after that. The site enrolled
2 patients in the last 8 weeks.

| Step | Value |
|---|---|
| scheduled | 1 + 0 + 2 = 3 |
| new | 2 / 8 = 0.25 per week x 50% x 3 weeks = 0.375 |
| spare | 0.375 + 1.65 x sqrt(0.375) = 1.39, raised to the floor of **2** |
| target | 3 + 2 = **5** |
| position | 2 on hand + 1 in transit = 3 |
| order | 5 - 3 = **2 kits** |

**A design lesson worth keeping:** the first version applied the floor of 2 to the *total*
target. A site whose existing patients already needed 3 kits then had no spare kit at all,
so new patients often arrived to an empty shelf (about 18 kits short per trial, twice the
forecast rule). Applying the floor to the *spare* kits fixed it (about 3 kits short). This was
found and fixed on the tuning trials, not the scoring trials.

**Strength:** most demand is known in advance, so it holds the least stock and stops sending
kits to patients who are about to finish (far fewer kits left at the end).
**Weakness:** it assumes every patient keeps going, so it slightly over-orders for patients
who will drop out. It needs patient-level data, which simple min/max does not.

### Rule 5: ML (LightGBM)

**In words:** a machine-learning model predicts how many kits this site and arm will need in
each of the next few weeks. The rule then orders exactly like the schedule rule, but using the
model's prediction instead of a plain count of booked visits.

**What LightGBM is:** "gradient-boosted trees". It builds hundreds of small decision trees
("if scheduled visits next week is 2 and the site enrolled someone in the last month, then...").
Each new tree corrects the mistakes of the ones before. It is the most widely proven ML method
for this kind of demand data: it won the M5 forecasting competition (Walmart retail, mostly
"lumpy" demand of 0s, 1s, and 2s) and is common in commercial demand forecasting.

**What it predicts:** kits needed at a site, for one arm, *h* weeks from now (h = 1 to 8).
One model covers every site, arm, and look-ahead week.

**What it can use** (only facts known at the current week; a test checks this):

| Input | Meaning |
|---|---|
| Scheduled kits in week h, and over the next 8 weeks | Known visits of patients on treatment now |
| Kits needed last week, average over last 4 / 8 / 16 weeks | Recent use at this site and arm |
| Patients enrolled per week, average over last 4 / 8 / 16 weeks; total so far | Recent and overall enrollment at this site |
| Patients on treatment at the site, and in this arm | Current load |
| Share of the trial's 500-patient target reached so far | How close enrollment is to closing |
| Weeks since the site opened; enrollment open or closed | Site and trial stage |
| Shipping time, region, arm, look-ahead week h | Context |

**How it was trained** (`python -m sim.train_ml`):
1. Make 40 training trials, separate from the scoring trials (0-199) and the min/max tuning
   trials (10000+). Base scenario only.
2. For every site, arm, week, and look-ahead week, record the inputs above and what actually
   happened h weeks later. About 6.5 million examples.
3. Train on 32 trials; keep 8 aside. Keep adding trees until the error on those 8 stops
   improving ("early stopping"), so the model learns patterns rather than memorising.
4. Save the model to `models/lgbm_need.txt` (not stored in git; re-create it with step 1).

The model is never retrained for the stress scenarios or dashboard knobs. Like tuned min/max,
it is tested on conditions it was not set up for.

**How it orders:**

```
cover     = shipping weeks + 1
expected  = model's predicted need over the next `cover` weeks
scheduled = kits due for patients on treatment now
booked    = the smaller of expected and scheduled   (lets the model allow for likely dropouts)
new       = expected - booked                       (the model's expected new-patient kits)
spare     = new + 1.65 x sqrt(new), at least 2 while enrolling; 0 once enrollment closes
target    = booked + spare, rounded up
order     = target - position, if position < target; otherwise 0
```

This mirrors the schedule rule on purpose: the only difference is where the forecast comes
from, so any difference in results is down to the model.

**Forecast accuracy** on the 8 held-out training trials (lower is better):

| Method | Poisson deviance |
|---|---|
| LightGBM | **0.29** |
| Scheduled visits only | 2.33 |
| Rolling 8-week average | 0.66 |

Poisson deviance is the standard error measure for count forecasts. LightGBM is far more
accurate as a forecast. Scheduled visits account for 87% of what the model learned (its
"gain": 53% the visits planned in the week itself, 35% the next 8 weeks combined, which lets it
spread a planned visit over the weeks it might land in). On top of that it learns
corrections: likely dropouts, new patients from enrollment trends, and the approach of
enrollment closing.

**But accuracy is not the goal; stockouts and waste are.** See section 7 for how that turns
into supply results.

**A design fix worth keeping:** the first version kept adding spare kits after enrollment had
closed (from the model's tiny leftover new-patient prediction), which left about 75 extra kits
per trial at sites at the end. The schedule rule adds no spare kits once enrollment closes;
the ML rule was changed to match. Found on tuning trials, not scoring trials.

### Rule 6: Schedule + Bayesian (Gamma-Poisson)

**In words:** exactly the schedule rule, but the spare kits for new patients come from a
proper statistical estimate of each site's own enrollment pace, instead of "average of the
last 8 weeks".

**What "Bayesian Gamma-Poisson" means here** (the published standard for enrollment
forecasting, e.g. Anisimov & Fedorov, 2007):
1. **Before a site has data**, assume its pace looks like a typical site's. This starting
   belief (the "prior") is a Gamma distribution fitted on the training trials: average 0.098
   patients per week, with a wide spread (many slow sites, a few fast).
2. **Each week, update the belief** with what the site has actually enrolled, allowing for
   its ramp-up. A site with 0 patients after 30 weeks is believed to be slow (about 0.025 per
   week); a site with 6 is believed to be fast (about 0.2 per week). New sites lean on the prior.
3. **Forecast new patients** over the coming weeks as a full probability distribution
   (negative binomial), and keep enough spare kits to cover **95%** of the likely outcomes.

```
cover     = shipping weeks + 1
scheduled = kits planned in the next `cover` weeks for patients on treatment now
pace      = Gamma(0.84 + site patients so far, 8.58 + site exposure weeks so far)
spare     = 95% cap on new patients for this arm in the next `cover` weeks,
            at least 2 while enrolling; 0 once enrollment closes
target    = scheduled + spare
```

**Where it should help:** new sites (little history, the prior fills the gap) and busy or
bursting sites (the 95% cap rises with the site's own record).
**Where it cannot help:** quiet and stumbling sites still keep the floor of 2 spare kits,
same as the schedule rule, so its estimate of "this site is slow" does not reduce their stock.

**Honest test:** the generator adds a country effect, pace drift, and bursts that this model
does not assume, so it is forecasting data it does not perfectly match.

The prior is fitted by `python -m sim.fit_prior` (on the ML training trials, never the
scoring trials).

### Ideas not built (kept for discussion)
- **Fewer, bigger forecast shipments:** only ship when at least N kits are needed.

## 6. Scoring and comparing (`sim/metrics.py`)

Per rule, per trial:

| Score | Meaning |
|---|---|
| Stockout events | Site-arm-weeks where at least one kit was short |
| Kits short | Total kits that should have been handed out but were not available |
| Kits expired | Kits removed because they would expire before the next visit |
| Kits left at end | Kits still at sites or in transit when the simulation ends (week 156) |
| Kits shipped | Total kits sent |
| Shipments | Number of boxes (one per site per week, both arms in one box) |
| Avg kits at sites | Average total stock sitting at all sites, per week |

**Comparing two rules:** for each of the 200 trials, take the difference (forecast minus
min/max). Report the average difference and a 95% range. If the range does not include
zero, the difference is real, not luck of the draw.

---

## 7. Results (200 trials, per trial averages)

These are the numbers behind the dashboard (normal knob settings, no shock). Every rule is
scored on the same 200 trials. About 6,150 kits are needed per trial.

| | Fixed refill | Fixed refill by region | Recent use | Expected visits | Expected visits + site pace | Expected visits + ML |
|---|---|---|---|---|---|---|
| Kits short | 293 | 11.3 | 9.8 | **7.2** | 8.2 | 8.1 |
| Kits expired | 532 | 1,096 | 219 | 187 | **187** | **187** |
| Kits left at close-out | 377 | 693 | 200 | **30** | **30** | **30** |
| Kits shipped | 6,770 | 7,931 | 6,563 | 6,363 | **6,362** | **6,362** |
| Shipments sent | **1,395** | 2,507 | 3,432 | 3,637 | 3,661 | 3,674 |
| Kits sitting at sites (avg per week) | 491 | 986 | 292 | 191 | **188** | **188** |

(Code names: minmax, minmax_tuned, forecast, schedule, schedule_bayes, ml.)

### What it says
- **Fixed refill** runs short a lot (about 5% of kits needed), mostly at busy sites far from
  the depot.
- **Fixed refill by region** fixes most of that by holding about twice the stock, and loses
  about 1 in 7 kits it ships to expiry (1,096 of 7,931).
- **Expected visits** runs short less than Fixed refill by region (7.2 vs 11.3 kits; 95% range
  of the difference -6.3 to -2.0), **with 81% less stock, 83% fewer expired kits, and almost
  nothing left at close-out** (30 vs 693). It sends about 45% more shipments.
- **Recent use** sits in between: little stock, but more shortfalls than Expected visits,
  because it only looks backwards.
- **The two "Expected visits +" rules** land almost exactly on Expected visits, slightly
  worse on shortfalls (see below).
- Which matters more, kits or shipments, depends on drug cost vs shipping cost, which this
  project does not model.

**How steady are these numbers?** Each rule's average comes from 200 random trials, so a new
set of 200 gives slightly different averages. Expected visits stays steady (7.1 and 7.2 kits
short in two different sets). Fixed refill by region moves more (8.2 and 11.3), because now and
then it has a trial with a big shortfall. The comparisons between rules are always made on the
same trials, so they are fair either way.

### Did ML or the Bayesian rule win?

**No.** Both are very slightly worse than plain Expected visits on shortfalls, with about 1.4%
less stock and the same waste:

| Difference vs Expected visits | Kits short per trial | 95% range | Kits at sites |
|---|---|---|---|
| + ML, no shock | +0.84 | +0.68 to +1.01 | -2.5 |
| + ML, surge | +2.02 | +1.71 to +2.33 | -3.2 |
| + site pace (Bayesian), no shock | +1.00 | +0.84 to +1.15 | -2.6 |
| + site pace (Bayesian), surge | +1.99 | +1.74 to +2.24 | -3.1 |

Why, in plain terms:
1. **Most demand is already known.** Most kits go to patients already on treatment, on planned
   visits. Expected visits uses that directly. ML and the Bayesian model only improve the small
   remaining part (new patients, dropouts).
2. **The floor of 2 spare kits makes most of the decisions.** At most sites all three rules
   keep the same 2 spare kits, so better estimates rarely change an order.
3. **Better average, thinner cushion.** ML expects some patients to drop out, and the Bayesian
   model often expects fewer new patients than the simpler rule allows for. Both hold slightly
   less stock, and occasionally that is one kit too few.
4. **Surges hurt them most.** ML never saw one in training; the Bayesian model assumes each
   site has a steady pace.

What this does and does not show:
- A rule that counts expected visits and keeps a sensible cushion is very hard to beat, and a
  more accurate forecast is not the same as fewer shortfalls.
- It does not show ML or Bayesian methods are useless. They hold slightly less stock, so the
  fair test compares rules at *equal* stock. The safety knob (section 8b) shows that.
- With real data the picture could change (see `docs/real_world_blueprint.md`, not in git).

### What changed when the model got more realistic
Before visit windows, enrollment realism, and running to the last visit, Expected visits had
about a third of Fixed refill by region's shortfalls (2.7 vs 8.2). With realistic visits the gap
is smaller, and it varies between sets of trials (section above). Its stock and waste advantage
held up, and grew once close-out was counted.

**Known caveat:** all rules are tested on data from our own generator, so results hold
"under these assumptions" (scope section 9).

---

## 8. Stress test and knobs

### 8a. Surges and stalls

| Scenario | What happens |
|---|---|
| No shock | The results in section 7. |
| Surge | 30% of sites suddenly enroll at 3x their pace for 12 weeks. |
| Stall | 30% of sites suddenly enroll nobody for 16 weeks, then carry on. |

The shock hits all chosen sites in the same week (between weeks 26 and 70). A shocked trial is
the no-shock trial with the same seed plus the shock. No rule is re-tuned or retrained.

| Kits short per trial | Fixed refill | Fixed refill by region | Recent use | Expected visits | + site pace | + ML |
|---|---|---|---|---|---|---|
| No shock | 293 | 11.3 | 9.8 | **7.2** | 8.2 | 8.1 |
| Surge | 329 | 16.5 | 14.4 | **8.8** | 10.8 | 10.9 |
| Stall | 299 | 10.3 | 10.1 | **7.2** | 8.3 | 8.1 |

- **In a surge, Expected visits holds up best:** 8.8 vs 16.5 kits short for Fixed refill by
  region (95% range of the difference -11.4 to -3.9).
- Stalls barely hurt anyone: a site that stops enrolling still has stock for its patients.
  Waste goes up slightly instead.
- Expired kits and stock follow the same pattern as section 7 in every scenario.

### 8b. Knobs: what if conditions change?

Each knob moves one setting while everything else stays normal. No rule is re-tuned and the ML
model is not retrained, so this shows how each rule copes when reality differs from what it was
set up for.

**Kits short per trial**

| Knob | Fixed refill | Fixed refill by region | Recent use | Expected visits | + site pace | + ML |
|---|---|---|---|---|---|---|
| Normal | 293 | 11.3 | 9.8 | **7.2** | 8.2 | 8.1 |
| Safety: low | 1,116 | 61.5 | 43.0 | **30.0** | 39.5 | 33.4 |
| Safety: high | 79 | 3.1 | **2.4** | 4.1 | 4.2 | 4.3 |
| Shipping time +1 week | 609 | 68.2 | **17.5** | 18.8 | 21.2 | 20.5 |
| Shelf life 12 months | 324 | 33.2 | 23.3 | **18.8** | 19.5 | 19.4 |
| Shelf life 36 months | 292 | 10.3 | 9.3 | **6.7** | 7.7 | 7.6 |
| Enrollment slower | 230 | 6.1 | 7.3 | **5.8** | 6.4 | 6.2 |
| Enrollment faster | 341 | 14.7 | 13.5 | **8.4** | 10.0 | 9.9 |

**Kits expired per trial**

| Knob | Fixed refill | Fixed refill by region | Recent use | Expected visits | + site pace | + ML |
|---|---|---|---|---|---|---|
| Normal | 532 | 1,096 | 219 | 187 | 187 | 187 |
| Safety: low | 299 | 814 | 138 | 106 | 105 | 105 |
| Safety: high | 789 | 1,399 | 319 | 274 | 274 | 274 |
| Shipping time +1 week | 539 | 1,110 | 244 | 200 | 199 | 199 |
| Shelf life 12 months | 2,282 | **5,232** | 808 | 592 | 589 | 589 |
| Shelf life 36 months | 249 | 492 | 101 | 104 | 104 | 104 |
| Enrollment slower | 706 | 1,438 | 298 | 260 | 259 | 259 |
| Enrollment faster | 418 | 861 | 172 | 144 | 143 | 143 |

**Kits sitting at sites (average per week)**

| Knob | Fixed refill | Fixed refill by region | Recent use | Expected visits | + site pace | + ML |
|---|---|---|---|---|---|---|
| Normal | 491 | 986 | 292 | 191 | 188 | 188 |
| Safety: low | 261 | 747 | 207 | 124 | 118 | 120 |
| Safety: high | 729 | 1,222 | 393 | 262 | 261 | 261 |

What the knobs show:
- **Slower shipping hurts the fixed rules badly** (Fixed refill by region: 11 to 68 kits short).
  Their levels were set for normal shipping. The forecast-type rules know the shipping time and
  adjust (about 18-21).
- **Short shelf life makes fixed rules waste enormously:** Fixed refill by region loses 5,232
  kits per trial at 12 months, against 592 for Expected visits.
- **Faster enrollment** hurts the fixed rules more (14.7 vs 8.4 kits short): their levels were
  set for the planned pace.
- **The safety knob shows the trade-off.** At high safety, Fixed refill by region (3.1) and
  Recent use (2.4) run short less than Expected visits (4.1), but hold far more stock (1,222 and
  393 kits vs 262). At low safety, Expected visits is clearly best. Put on one chart
  (shortfalls against stock held), Expected visits runs short less than the others wherever
  their stock levels overlap (about 120-260 kits). Even at high safety it holds less stock than
  the others do at normal safety, so how it would do at 400+ kits is not covered.

---

## 9. Checks that keep it honest (`tests/`)

- Same seed → identical results, every time.
- Stock never goes negative; each week's stock adds up (last week + received − handed out − expired).
- Kits handed out + kits short = kits needed, for every site, arm, and week.
- Shipments arrive exactly one shipping-time after they are sent.
- Every kit shipped ends up handed out, expired, or still on hand / in transit.
- **No peeking:** erase all visits from week 60 on; every decision before week 60 must be unchanged.
- Tuning trials never overlap scoring trials.
- Shocks only touch the chosen sites, only inside the shock window; stalled sites enroll nobody during the stall.
- A shocked trial has the same sites as the base trial with the same seed.
- Visits follow the cycle-based windows: planned one cycle after the previous actual visit,
  shifted at most one week, missed visits carry no kit; shift and miss rates match the settings.
- With no shifts and no misses, what the schedule-type rules know equals the real future visits exactly.
- Country effects are shared within a country; bursts make weeks lumpier; drift and bursts leave
  the average pace unchanged.
- Every trial runs to its last visit.
- When a box goes to a site, every arm in it ends at or above its target, and topping up never adds a box.
- The Bayesian maths matches a reference implementation, the prior fit recovers a known
  distribution, and the Bayesian and ML rules never peek ahead.
