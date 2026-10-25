# Workflow

Step-by-step: how to set up, run, check, and change the simulator on macOS.
For what the simulator does, see `docs/how_it_works.md`.

---

## 1. Every session

Open a terminal in VS Code (**Ctrl+`**) in the project folder, then:

```zsh
source .venv/bin/activate     # turn on the project's Python (like activate.bat on Windows)
pytest -q                     # all tests should pass
```

The prompt shows `(.venv)` when the environment is on. Postgres runs in the background by
itself; check with `brew services list`.

---

## 2. First time only: train the ML model

```zsh
caffeinate -i python -m sim.train_ml
```

Takes about 30 seconds. Builds 40 training trials, trains LightGBM, prints its accuracy next
to two simple baselines, and saves `models/lgbm_need.txt`. The model file is not in git, so do
this once after cloning, and again whenever you change anything that affects demand
(enrollment, visits, dropouts, shipping time). The main run stops with a message if the model
is missing.

## 2b. Main run

```zsh
caffeinate -i python -m sim.run --seeds 200 --reset
```

| Part | Meaning |
|---|---|
| `caffeinate -i` | Keeps the Mac awake until the run finishes. Without it, a Mac on battery can sleep mid-run and a 6-minute run turns into an hour. |
| `--seeds 200` | Number of simulated trials **per scenario**. Use 5–20 for quick checks. |
| `--scenarios base surge stall` | Which scenarios to run (default: all three). E.g. `--scenarios base` for just the normal case. |
| `--reset` | Drops and recreates all tables first. **Use it whenever the table layout (`sql/schema.sql`) changed.** Without it, existing trials with the same ids are replaced and others are kept. |

What it does, for each scenario and each trial:
1. Builds the trial (sites, patients, visits), adding the scenario's surge or stall if any.
2. Replays it under each rule (`minmax`, `minmax_tuned`, `forecast`, `schedule`, `ml`).
3. Scores each rule.
4. Loads everything into Postgres (`irt_sim`).

After each scenario it prints a table: average scores for each rule, and the forecast minus
tuned min/max difference with its 95% range.

Run time: about 3 seconds per trial (5 rules), so ≈ 10 minutes per scenario, ≈ 30 minutes
for all three. Database size for all three scenarios: ≈ 14 GB.

---

## 3. Re-tuning min/max and retraining ML

The tuned min/max numbers live in `sim/config.py` as `MINMAX_TUNED`. They were picked for
the current settings. **Re-tune whenever you change anything about enrollment, visits,
shipping time, shelf life, or the forecast rule**, otherwise the tuned baseline is stale.

```zsh
caffeinate -i python -m sim.tune_minmax
```

It takes ~8 minutes, then prints a line like:

```
MINMAX_TUNED = {'Asia-Pacific': (10, 15), 'Europe': (6, 8), 'North America': (4, 5)}
```

Paste that into `sim/config.py`, run `pytest -q`, then do the main run (section 2b).

Retrain the ML model the same way: `caffeinate -i python -m sim.train_ml`.

---

## 4. Looking at the data

Connection details are in the README ("Accessing the database"). Quick start:

```zsh
psql irt_sim
```

### Tables

| Table | One row per | What's in it |
|---|---|---|
| `trial` | trial | Scenario, seed, and all settings used |
| `site` | trial, site | Region, country, opening week, pace, stumbling flag, shocked flag + shock week |
| `site_week` | trial, site, week | Open?, patients enrolled, kits needed (all arms) |
| `patient` | trial, patient | Site, arm, enrollment week, end week |
| `visit` | trial, patient, visit | Week, date, arm, kits |
| `lot` | trial, lot | Arm, made / expiry / release dates |
| `shipment` | trial, rule, box, arm | Site, lot, ship week, arrival week, kits |
| `inventory_week` | trial, rule, site, arm, week | Received, needed, handed out, short, expired, ordered, on hand, in transit |
| `policy_result` | trial, rule | The scores (see `how_it_works.md` section 6) |

`policy` in the tables = the reorder rule: `minmax`, `minmax_tuned`, `forecast`, `schedule`, `ml`.

**Trial ids:** `trial_id` = scenario number × 100000 + seed. Base trials are 0–199, surge
100000–100199, stall 200000–200199. Seed 7 is the same underlying trial in all three
scenarios (`trial.seed` = 7), so you can compare them directly. To filter by scenario,
join to `trial`.

### Useful queries

```sql
-- Average scores per scenario and rule
SELECT t.scenario, r.policy,
       round(avg(r.kits_short),1) AS short, round(avg(r.kits_expired),1) AS expired,
       round(avg(r.shipments)) AS boxes, round(avg(r.avg_kits_at_sites)) AS stock
FROM policy_result r JOIN trial t USING (trial_id)
GROUP BY 1, 2 ORDER BY 1, 2;

-- Where waste and stockouts happen, by region and rule (base scenario)
SELECT s.region, i.policy,
       round(sum(i.kits_short)   / 200.0, 1) AS short_per_trial,
       round(sum(i.kits_expired) / 200.0, 1) AS expired_per_trial
FROM inventory_week i JOIN site s USING (trial_id, site_id)
WHERE i.trial_id < 100000
GROUP BY 1, 2 ORDER BY 1, 2;

-- Shocked vs not-shocked sites in the surge scenario
SELECT s.shocked, i.policy,
       round(sum(i.kits_short)   / 200.0, 1) AS short_per_trial,
       round(sum(i.kits_expired) / 200.0, 1) AS expired_per_trial
FROM inventory_week i JOIN site s USING (trial_id, site_id)
JOIN trial t USING (trial_id)
WHERE t.scenario = 'surge'
GROUP BY 1, 2 ORDER BY 1, 2;

-- Cumulative enrollment curve for one trial
SELECT week, sum(sum(enrolled)) OVER (ORDER BY week) AS cum_enrolled
FROM site_week WHERE trial_id = 0 GROUP BY week ORDER BY week;

-- One site's stock over time under each rule
SELECT policy, week, arm, on_hand, in_transit, kits_needed, kits_short, kits_expired
FROM inventory_week WHERE trial_id = 0 AND site_id = 1 ORDER BY policy, arm, week;
```

---

## 5. Changing a setting

1. Edit the value in `sim/config.py` (every setting is there, with a comment).
2. Add or update the matching line in `docs/assumptions.md`.
3. `pytest -q`.
4. If it affects demand, shipping, or the forecast rule: re-tune min/max and retrain ML (section 3).
5. Main run (section 2b). Use `--reset` if `sql/schema.sql` changed.

---

## 6. Where things live

| Path | What |
|---|---|
| `sim/config.py` | Every setting and the master seed |
| `sim/generator.py` | Makes a trial |
| `sim/network.py` | Lots, shipping, weekly stock loop |
| `sim/policies/` | The reorder rules |
| `sim/metrics.py` | Scores and rule-vs-rule comparison |
| `sim/tune_minmax.py` | Picks tuned min/max settings |
| `sim/ml.py` | Builds ML inputs (features) and predictions |
| `sim/train_ml.py` | Trains and saves the LightGBM model |
| `models/` | Saved ML model (not in git) |
| `sim/run.py` | Main run: generate, replay, score, load |
| `sim/db.py` | Creates tables, bulk-loads data |
| `sql/schema.sql` | Table definitions |
| `tests/` | Automated checks |
| `docs/scope.md` | What is in and out of scope, phases |
| `docs/assumptions.md` | Every made-up number and simplification |
| `docs/backlog.md` | Ideas parked for later |

---

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `psql: command not found` | `source ~/.zshrc` (or open a new terminal tab) |
| `ModuleNotFoundError` | Environment not on: `source .venv/bin/activate` |
| Can't connect to database | `brew services restart postgresql@16` |
| `No ML model at models/lgbm_need.txt` | `python -m sim.train_ml` (section 2) |
| LightGBM import error about `libomp` | `brew install libomp` |
| Run is very slow | Mac went to sleep: use `caffeinate -i` (section 2) |
| Errors about missing columns after a code update | Table layout changed: add `--reset` |
| pgAdmin asks for user `postgres` | There is none; use your Mac login name (see README) |
