"""Generate simulated trials, replay each under every reorder rule, load into Postgres.

    python -m sim.run --seeds 200                   # normal knobs, all scenarios (base, surge, stall)
    python -m sim.run --seeds 200 --plan dashboard  # the 10 runs behind the dashboard
    python -m sim.run --seeds 200 --knob shelf_12   # one knob position, base scenario
    python -m sim.run --seeds 5 --reset             # drop and recreate tables first

Storage: every trial keeps its scores (policy_result) and sites. Only the first
--detail-trials trials of each run keep their week-by-week rows (for the site chart).
Any other trial can be recreated exactly from its seed.
"""
import argparse
import time
from pathlib import Path

import pandas as pd

from sim import config as c
from sim.db import SUMMARY_TABLES, create_schema, get_engine, load_country_risk, load_trial
from sim.generator import generate_trial
from sim.metrics import compare, summarize
from sim.network import simulate_supply
from sim.policies import forecast, minmax, minmax_tuned, ml, schedule, schedule_bayes

POLICIES = [minmax, minmax_tuned, forecast, schedule, schedule_bayes, ml]
SCENARIO_NAMES = list(c.SCENARIOS)
KNOB_NAMES = list(c.KNOBS)


def trial_id_for(scenario, seed, knob="normal"):
    """Unique id per (knob, scenario, seed). Normal knobs: base 0..N-1, surge 100000.., stall 200000.."""
    return KNOB_NAMES.index(knob) * 1_000_000 + SCENARIO_NAMES.index(scenario) * 100_000 + seed


def run_trial(seed, scenario="base"):
    """All tables for one trial: the trial itself plus every policy's supply results."""
    shock_rng = c.make_rng(seed, stream=1)  # separate stream: the base trial's draws are untouched
    tables = generate_trial(c.make_rng(seed), scenario, shock_rng)
    supply = [simulate_supply(tables, p) for p in POLICIES]
    tables["lot"] = supply[0]["lot"]  # lots come from config, same for every policy
    for name in ["inventory_week", "shipment"]:
        tables[name] = pd.concat([s[name] for s in supply], ignore_index=True)
    tables["policy_result"] = pd.concat([summarize(s) for s in supply], ignore_index=True)
    return tables


def stockout_weeks(tables):
    """(policy, country, week) where at least one site in the country ran short. For Screen 2."""
    inv = tables["inventory_week"]
    short = inv[inv["kits_short"] > 0].merge(tables["site"][["site_id", "country"]], on="site_id")
    return short[["policy", "country", "week"]].drop_duplicates()


def scenario_table(results):
    """Means per policy, plus (rule - minmax_tuned) difference with 95% range for each forecast-type rule."""
    means = results.drop(columns="trial_id").groupby("policy").mean().T
    table = means[[p.NAME for p in POLICIES]]
    for other in [p.NAME for p in POLICIES if p.NAME not in ("minmax", "minmax_tuned")]:
        d = compare(results, base="minmax_tuned", other=other)
        table[f"{other}_diff"] = d["diff"]
        table[f"{other}_95%"] = d["ci_low"].round(1).astype(str) + " to " + d["ci_high"].round(1).astype(str)
    return table.round(1)


def run_one(engine, knob, scenario, seeds, detail_trials, start):
    """One dashboard run: all trials for one knob position and scenario."""
    old = c.set_knob(knob)
    try:
        results, flagged = [], []
        for seed in range(seeds):
            tid = trial_id_for(scenario, seed, knob)
            tables = run_trial(seed, scenario)
            flagged.append(stockout_weeks(tables))
            keep = tables if seed < detail_trials else {k: tables[k] for k in SUMMARY_TABLES}
            load_trial(engine, tid, keep, seed, scenario, knob)
            results.append(tables["policy_result"].assign(trial_id=tid))
            if seed % 50 == 0 or seed == seeds - 1:
                print(f"{knob}/{scenario} trial {seed:>4} loaded ({time.time() - start:.0f}s)", flush=True)

        risk = (pd.concat(flagged).groupby(["policy", "country", "week"]).size()
                .rename("trials_with_stockout").reset_index().assign(trials=seeds))
        load_country_risk(engine, knob, scenario, risk)

        table = scenario_table(pd.concat(results, ignore_index=True))
        print(f"\n[{knob} / {scenario}] average per trial over {seeds} trials "
              f"(diff = rule - minmax_tuned, 95% range):\n{table.to_string()}\n", flush=True)
    finally:
        c.restore_knob(old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200, help="number of simulated trials per run")
    ap.add_argument("--scenarios", nargs="+", default=SCENARIO_NAMES, choices=SCENARIO_NAMES)
    ap.add_argument("--knob", default="normal", choices=KNOB_NAMES, help="one knob position")
    ap.add_argument("--plan", choices=["dashboard"], help="run all 10 dashboard runs (overrides --knob/--scenarios)")
    ap.add_argument("--detail-trials", type=int, default=5, help="trials per run that keep week-by-week rows")
    ap.add_argument("--reset", action="store_true", help="drop and recreate tables")
    args = ap.parse_args()
    assert args.seeds <= c.TUNING_SEED_START, "scoring seeds would overlap the min/max tuning seeds"
    if not Path(c.ML_MODEL_PATH).exists():
        raise SystemExit(f"No ML model at {c.ML_MODEL_PATH}. Train it first:  python -m sim.train_ml")

    runs = c.DASHBOARD_RUNS if args.plan == "dashboard" else [(args.knob, s) for s in args.scenarios]
    engine = get_engine()
    create_schema(engine, reset=args.reset)
    start = time.time()
    for knob, scenario in runs:
        run_one(engine, knob, scenario, args.seeds, args.detail_trials, start)


if __name__ == "__main__":
    main()
