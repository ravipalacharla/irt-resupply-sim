"""LightGBM forecast of weekly kit need, per site, arm, and look-ahead week.

One row = (site, arm, week w, look-ahead h). The model predicts kits needed at week w + h
using only facts known at week w. The ML reorder rule (sim/policies/ml.py) sums the
predictions over the weeks it must cover.

    python -m sim.train_ml      # build training data, train, save model (see sim/train_ml.py)
"""
import numpy as np
import pandas as pd

from sim import config as c
from sim.network import demand_by_site_arm, scheduled_kits

L = c.SCHEDULE_LOOKAHEAD_WEEKS
REGION_CODE = {r: i for i, r in enumerate(c.REGIONS)}
ARM_CODE = {a: i for i, a in enumerate(c.ARMS)}

FEATURES = [
    "h", "sched_h", "sched_total",
    "need_last", "need_mean4", "need_mean8", "need_mean16",
    "enroll_mean4", "enroll_mean8", "enroll_mean16", "enroll_cum",
    "on_treatment_site", "on_treatment_arm", "trial_enrolled_frac",
    "weeks_open", "enrolling", "lead_time", "region", "arm",
] + [f"sched_{i + 1}" for i in range(L)]


def trailing_mean(x, k):
    """Mean of the last k weeks up to and including each week (weeks before 0 count as 0).

    x: array [rows, weeks]. Uses a running total, so week w only sees weeks <= w.
    """
    cs = np.concatenate([np.zeros((x.shape[0], 1)), np.cumsum(x, axis=1)], axis=1)
    w = np.arange(x.shape[1])
    return (cs[:, w + 1] - cs[:, np.maximum(w + 1 - k, 0)]) / k


def on_treatment_matrix(patients, by, keys):
    """[len(keys), W]: patients on treatment per week. by = "site_id" or ["site_id", "arm"]."""
    index = {k: i for i, k in enumerate(keys)}
    out = np.zeros((len(keys), c.TRIAL_WEEKS))
    for k, g in patients.groupby(by):
        delta = np.zeros(c.TRIAL_WEEKS + 1)
        np.add.at(delta, g["enroll_week"].to_numpy(), 1)   # +1 the week they start
        np.add.at(delta, g["end_week"].to_numpy(), -1)     # -1 the week they stop
        out[index[k]] = delta.cumsum()[: c.TRIAL_WEEKS]
    return out


def build_features(trial, with_label=True):
    """DataFrame with one row per (site, arm, week, h). Only uses facts known at `week`."""
    sites = trial["site"]
    W = c.TRIAL_WEEKS
    keys = [(s, a) for s in sites["site_id"] for a in c.ARMS]   # every site-arm
    site_of = np.array([k[0] for k in keys])
    site_row = {s: i for i, s in enumerate(sites["site_id"])}
    srow = np.array([site_row[s] for s in site_of])            # site index for each site-arm

    demand = demand_by_site_arm(trial)
    need = np.array([demand.get(k, np.zeros(W)) for k in keys], dtype=float)   # [SA, W]
    sched = scheduled_kits(trial)
    sch = np.array([sched.get(k, np.zeros((W, L))) for k in keys], dtype=float)  # [SA, W, L]

    enrolled = trial["site_week"].pivot(index="site_id", columns="week", values="enrolled")
    enrolled = enrolled.loc[sites["site_id"]].to_numpy(dtype=float)[srow]       # [SA, W]
    p = trial["patient"]
    on_site = on_treatment_matrix(p, "site_id", list(sites["site_id"]))[srow]
    on_arm = on_treatment_matrix(p, ["site_id", "arm"], keys)
    trial_cum = trial["site_week"].groupby("week")["enrolled"].sum().cumsum().to_numpy()
    closed_from = p["enroll_week"].max() + 1 if len(p) >= c.ENROLL_TARGET else W

    weeks = np.arange(W)
    meta = sites.set_index("site_id")
    open_week = meta.loc[site_of, "open_week"].to_numpy()
    region = meta.loc[site_of, "region"].to_numpy()

    base = pd.DataFrame({
        "site_id": np.repeat(site_of, W),
        "arm_name": np.repeat([k[1] for k in keys], W),
        "week": np.tile(weeks, len(keys)),
        "need_last": need.ravel(),
        "need_mean4": trailing_mean(need, 4).ravel(),
        "need_mean8": trailing_mean(need, 8).ravel(),
        "need_mean16": trailing_mean(need, 16).ravel(),
        "enroll_mean4": trailing_mean(enrolled, 4).ravel(),
        "enroll_mean8": trailing_mean(enrolled, 8).ravel(),
        "enroll_mean16": trailing_mean(enrolled, 16).ravel(),
        "enroll_cum": np.cumsum(enrolled, axis=1).ravel(),
        "on_treatment_site": on_site.ravel(),
        "on_treatment_arm": on_arm.ravel(),
        "trial_enrolled_frac": np.tile(trial_cum / c.ENROLL_TARGET, len(keys)),
        "weeks_open": (weeks[None, :] - open_week[:, None]).ravel(),
        "enrolling": np.tile(weeks < closed_from, len(keys)).astype(int),
        "lead_time": np.repeat([c.LEAD_TIME_WEEKS[r] for r in region], W),
        "region": np.repeat([REGION_CODE[r] for r in region], W),
        "arm": np.repeat([ARM_CODE[k[1]] for k in keys], W),
        "sched_total": sch.sum(axis=2).ravel(),
    })
    for i in range(L):
        base[f"sched_{i + 1}"] = sch[:, :, i].ravel()

    # Expand to one row per look-ahead week h = 1..L.
    rows = []
    for h in range(1, L + 1):
        f = base.copy()
        f["h"] = h
        f["sched_h"] = base[f"sched_{h}"]
        if with_label:
            later = np.full(need.shape, np.nan)
            later[:, : W - h] = need[:, h:]               # need at week w + h
            f["label"] = later.ravel()
        rows.append(f)
    out = pd.concat(rows, ignore_index=True)
    # Only weeks where the rule can be asked: from one shipping time before opening.
    out = out[out["weeks_open"] >= -out["lead_time"]]
    if with_label:
        out = out[out["label"].notna()]
    return out.reset_index(drop=True)


def predict_need(trial, model):
    """{(site_id, arm): array [W, L]} of predicted kits needed at week + 1 .. week + L."""
    f = build_features(trial, with_label=False)
    f["pred"] = model.predict(f[FEATURES])
    out = {}
    for (site_id, arm), g in f.groupby(["site_id", "arm_name"]):
        arr = np.zeros((c.TRIAL_WEEKS, L))
        arr[g["week"].to_numpy(), g["h"].to_numpy() - 1] = g["pred"].to_numpy()
        out[(site_id, arm)] = arr
    return out
