# IRT Resupply Simulator: Scope, Boundaries & Toolset

Public portfolio project. Compares rules-based vs. forecast-driven clinical supply resupply on **fully synthetic** trial data.

---

## 1. Feasibility review (corrections to the earlier outline)

| Earlier claim | Verdict |
|---|---|
| Generator in ~1 week | **Optimistic.** Budget 2 weeks for generator + validation. |
| Gamma-Poisson site enrollment | **Sound.** Standard model in enrollment-forecasting literature. |
| LightGBM beats rules-based | **Not guaranteed, and partly circular.** The model learns the generator's own process, so a win on synthetic data proves little. Frame ML as "does a forecast reduce waste/stockouts under these assumptions", not "ML is better". Report a null result honestly. |
| Evaluate on stockouts/waste, not MAE | **Correct.** Keep as the primary acceptance criterion. |
| Seed parameters from AACT | **Doable but limited.** AACT gives planned enrollment, site counts, countries, and durations by phase. It gives no site-level rates, supply, or visit data. Calibrate trial-level shape only. |
| Reuse D3 skills | **Doable.** Ship precomputed JSON, no live backend needed in v1. |

Overall: **doable as a part-time project in ~6-8 weeks** if the ML layer stays last and optional.

---

## 2. In scope

- Synthetic multi-site trial generator: staggered site activation, per-site enrollment rates, randomization to arms, visit schedule, dropouts.
- Simplified supply network: one central depot (optionally 2-3 regional), sites, shipment lead times, kit lots with expiry.
- Policy A: min/max (buffer) resupply with generic parameters.
- Policy B: forecast-driven resupply (rolling average + safety stock first; LightGBM later).
- Monte Carlo comparison across many seeds on identical simulated trials.
- Metrics: stockout events, expired/wasted kits, shipment count, average inventory on hand.
- D3 dashboard: site inventory timeline, stockout heatmap, policy comparison, scenario slider.
- Optional: trial-level parameter calibration from AACT (myeloma subset is fine).

## 3. Out of scope (v1)

- Real IRT/RTSM logic, specs, rule names, or terminology from any employer or client.
- Any real trial, site, depot, or patient data.
- Multi-drug/multi-kit-type blinding logic, titration, dose modification, returns/reconciliation, customs, temperature excursions.
- Cost modeling, optimization solvers, reinforcement learning.
- Live hosted backend, auth, or databases in the cloud (static hosting only).
- Claims of real-world accuracy or applicability.

## 4. IP and publishing boundaries

- Parameters are invented or derived from public sources (AACT, published literature). Document each assumption in `docs/assumptions.md`.
- Generic names only: "min/max policy", "forecast policy". No vendor, product, or client names in code, data, comments, or commit history.
- Do not reuse stored-procedure logic, table designs, or naming from work systems, even from memory.
- Check your employer's IP / outside-activity policy before the first public push. Get written confirmation if unclear.
- Develop on a personal machine and personal GitHub account.
- README states: "Synthetic data. Illustrative only."

---

## 5. Toolset

| Layer | Tool | Notes |
|---|---|---|
| Editor | **VS Code** | Extensions: Python, Pylance, SQLTools + PostgreSQL driver, Jupyter |
| Language | **Python 3.11+** | venv per project (`python -m venv .venv`) |
| Simulation | **numpy + pandas**, plain weekly-step loop | Skip SimPy in v1; a time-stepped loop is easier to debug while learning Python |
| Database | **PostgreSQL 16** (your existing local install) | Separate database `irt_sim`, not inside `aact` |
| DB access | **SQLAlchemy + psycopg2** | Bulk load with `DataFrame.to_sql` / `COPY` |
| ML (phase 3 only) | **scikit-learn + LightGBM** | Time-based train/test split only |
| Testing | **pytest** | Seeded RNG; invariants (inventory never negative, shipments arrive after lead time) |
| Export | Python script writes **JSON** per scenario | Contract between sim and dashboard |
| Frontend | **D3 v7 + vanilla HTML/JS** | Static files, reuse your myeloma project patterns |
| Hosting | **GitHub Pages** | Precomputed JSON, no server |
| Version control | **Git + GitHub** | Small commits per phase |
| Optional | FastAPI | Only if you later want live scenario runs; not v1 |

Not needed: Azure, pgvector, Claude API, Databricks.

---

## 6. Suggested repo layout

```
irt-resupply-sim/
  README.md
  docs/assumptions.md
  docs/scope.md              # this file
  sim/
    config.py                # all parameters, seeded
    generator.py             # sites, enrollment, visits
    network.py               # depot, lead times, lots, expiry
    policies/minmax.py
    policies/forecast.py
    run.py                   # Monte Carlo runner
    metrics.py
  sql/schema.sql
  tests/
  notebooks/                 # validation, forecast experiments
  web/                       # D3 dashboard + data/*.json
```

## 7. Core tables (Postgres, `irt_sim`)

`sim_run`, `site`, `site_week` (activation, enrolled, demand), `patient`, `visit`, `shipment`, `inventory_week` (site_id, week, on_hand, expired, stockout_flag), `policy_result` (run, policy, metrics).

---

## 8. Phases and acceptance criteria

1. **Generator + schema (weeks 1-2).** Enrollment curves look plausible (S-shaped cumulative, long-tail sites). Tests pass. Loaded into Postgres and queryable.
2. **Network + min/max baseline (weeks 3-4).** Inventory invariants hold. Baseline produces non-trivial stockouts and waste.
3. **Forecast policy (weeks 5-6).** Rolling-average policy first. LightGBM only after that, using only data available up to the current simulated week (no leakage). Compare over 200+ seeds with confidence intervals.
4. **Dashboard + write-up (weeks 7-8).** Four D3 views, README with assumptions, and an honest limitations section.

Definition of done: reproducible run from a fresh clone (`python -m sim.run --seeds 200`), dashboard live on GitHub Pages, assumptions documented.

## 9. Key risks

- **Circular validation:** the forecast sees the generator's own structure. Mitigate by adding noise and regime shifts (enrollment surge/stall) the model was not trained on.
- **Scope creep:** every added IRT feature is tempting. Anything not in section 2 goes to a v2 backlog.
- **Unrealistic parameters:** document every assumption and cite AACT or literature where possible.
