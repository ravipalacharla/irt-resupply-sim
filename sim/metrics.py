"""Score reorder rules on trials, and compare two rules across many trials."""
import numpy as np
import pandas as pd

from sim import config as c


def summarize(supply):
    inv, ship = supply["inventory_week"], supply["shipment"]
    last = inv[inv["week"] == inv["week"].max()]   # trial end (after the last visit)
    return pd.DataFrame([{
        "policy": inv["policy"].iloc[0],
        "stockout_events": int((inv["kits_short"] > 0).sum()),  # site-arm-weeks with any shortfall
        "kits_short": int(inv["kits_short"].sum()),
        "kits_expired": int(inv["kits_expired"].sum()),
        "kits_left_at_end": int(last["on_hand"].sum() + last["in_transit"].sum()),
        "kits_shipped": int(ship["kits"].sum()),
        "shipments": int(ship["shipment_id"].nunique()),
        "avg_kits_at_sites": float(inv.groupby("week")["on_hand"].sum().mean()),
    }])


def compare(results, base="minmax", other="forecast"):
    """Paired comparison: other minus base on the same trial, averaged over trials.

    results: policy_result rows with a trial_id column, both policies for every trial.
    The 95% interval is mean difference +/- 1.96 x standard error. If it does not
    include 0, the difference is unlikely to be luck of the draw.
    """
    wide = results.pivot(index="trial_id", columns="policy")  # one row per trial, a column per (metric, policy)
    rows = []
    for metric in results.columns.drop(["trial_id", "policy"]):
        diff = wide[(metric, other)] - wide[(metric, base)]
        half = 1.96 * diff.std(ddof=1) / np.sqrt(len(diff))  # ddof=1: sample std
        rows.append({"metric": metric,
                     base: wide[(metric, base)].mean(), other: wide[(metric, other)].mean(),
                     "diff": diff.mean(), "ci_low": diff.mean() - half, "ci_high": diff.mean() + half})
    return pd.DataFrame(rows).set_index("metric")
