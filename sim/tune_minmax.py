"""Pick the best fixed (MIN, MAX) per region, on tuning trials only.

    python -m sim.tune_minmax

For each region: keep settings that are short no more kits than the forecast rule
(same tuning trials), then take the fewest expired kits, then the fewest shipments.
If no setting matches the forecast rule's service, take the fewest kits short.
Paste the printed MINMAX_TUNED line into sim/config.py.
"""
from functools import partial
from types import SimpleNamespace

import pandas as pd

from sim import config as c
from sim.generator import generate_trial
from sim.network import simulate_supply
from sim.policies import forecast, minmax

MIN_RANGE = range(1, 11)   # MIN 1..10
GAP_RANGE = range(1, 9)    # MAX = MIN + 1..8


def region_metrics(trial, supply):
    """kits_short, kits_expired, shipments per region for one trial."""
    regions = trial["site"][["site_id", "region"]]
    inv = supply["inventory_week"].merge(regions, on="site_id")
    ship = supply["shipment"].merge(regions, on="site_id")
    out = inv.groupby("region")[["kits_short", "kits_expired"]].sum()
    out["shipments"] = ship.groupby("region")["shipment_id"].nunique()
    return out.fillna(0)


def mean_over_trials(trials, policy):
    return pd.concat([region_metrics(t, simulate_supply(t, policy)) for t in trials]).groupby(level=0).mean()


def pick(grid, reference_short):
    """grid: one row per (region, low, high) with mean metrics. reference_short: region -> kits_short."""
    best = {}
    for region, g in grid.groupby("region"):
        ok = g[g["kits_short"] <= reference_short[region]]
        if len(ok):
            row = ok.sort_values(["kits_expired", "shipments", "low", "high"]).iloc[0]
        else:
            row = g.sort_values(["kits_short", "kits_expired", "shipments"]).iloc[0]
        best[region] = (int(row["low"]), int(row["high"]))
    return best


def main():
    seeds = range(c.TUNING_SEED_START, c.TUNING_SEED_START + c.TUNING_TRIALS)
    trials = [generate_trial(c.make_rng(s)) for s in seeds]
    ref = mean_over_trials(trials, forecast)
    print("forecast rule on tuning trials (per trial):\n", ref.round(1), "\n")

    rows = []
    for low in MIN_RANGE:
        for gap in GAP_RANGE:
            policy = SimpleNamespace(NAME="minmax", order_qty=partial(minmax.order_qty, low=low, high=low + gap))
            m = mean_over_trials(trials, policy).reset_index()
            m["low"], m["high"] = low, low + gap
            rows.append(m)
        print(f"MIN={low} done", flush=True)
    grid = pd.concat(rows, ignore_index=True)

    best = pick(grid, ref["kits_short"])
    for region, (low, high) in best.items():
        r = grid[(grid["region"] == region) & (grid["low"] == low) & (grid["high"] == high)].iloc[0]
        print(f"{region:<14} MIN={low} MAX={high}  short={r.kits_short:.1f} (forecast {ref.loc[region, 'kits_short']:.1f})"
              f"  expired={r.kits_expired:.1f} (forecast {ref.loc[region, 'kits_expired']:.1f})"
              f"  shipments={r.shipments:.0f} (forecast {ref.loc[region, 'shipments']:.0f})")
    print(f"\nMINMAX_TUNED = {best}")


if __name__ == "__main__":
    main()
