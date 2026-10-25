"""Generate N simulated trials per scenario, replay each under every reorder rule, load into Postgres.

    python -m sim.run --seeds 200                     # all scenarios (base, surge, stall)
    python -m sim.run --seeds 200 --scenarios base    # just one
    python -m sim.run --seeds 5 --reset               # drop and recreate tables first
"""
import argparse
import time

import pandas as pd

from sim import config as c
from sim.db import create_schema, get_engine, load_trial
from sim.generator import generate_trial
from sim.metrics import compare, summarize
from sim.network import simulate_supply
from sim.policies import forecast, minmax, minmax_tuned, schedule

POLICIES = [minmax, minmax_tuned, forecast, schedule]
SCENARIO_NAMES = list(c.SCENARIOS)


def trial_id_for(scenario, seed):
    """Unique id per (scenario, seed): base 0..N-1, surge 100000.., stall 200000.."""
    return SCENARIO_NAMES.index(scenario) * 100_000 + seed


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


def scenario_table(results):
    """Means per policy, plus (rule - minmax_tuned) difference with 95% range for each forecast-type rule."""
    means = results.drop(columns="trial_id").groupby("policy").mean().T
    table = means[[p.NAME for p in POLICIES]]
    for other in [p.NAME for p in POLICIES if p.NAME not in ("minmax", "minmax_tuned")]:
        d = compare(results, base="minmax_tuned", other=other)
        table[f"{other}_diff"] = d["diff"]
        table[f"{other}_95%"] = d["ci_low"].round(1).astype(str) + " to " + d["ci_high"].round(1).astype(str)
    return table.round(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200, help="number of simulated trials per scenario")
    ap.add_argument("--scenarios", nargs="+", default=SCENARIO_NAMES, choices=SCENARIO_NAMES)
    ap.add_argument("--reset", action="store_true", help="drop and recreate tables")
    args = ap.parse_args()
    assert args.seeds <= c.TUNING_SEED_START, "scoring seeds would overlap the min/max tuning seeds"

    engine = get_engine()
    create_schema(engine, reset=args.reset)

    start = time.time()
    for scenario in args.scenarios:
        results = []
        for seed in range(args.seeds):
            tid = trial_id_for(scenario, seed)
            tables = run_trial(seed, scenario)
            load_trial(engine, tid, tables, seed, scenario)
            results.append(tables["policy_result"].assign(trial_id=tid))
            if seed % 50 == 0 or seed == args.seeds - 1:
                print(f"{scenario} trial {seed:>4} loaded ({time.time() - start:.0f}s)", flush=True)

        table = scenario_table(pd.concat(results, ignore_index=True))
        print(f"\n[{scenario}] average per trial over {args.seeds} trials "
              f"(diff = rule - minmax_tuned, 95% range):\n{table.to_string()}\n", flush=True)


if __name__ == "__main__":
    main()
