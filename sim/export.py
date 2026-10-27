"""Write the dashboard's data files (static JSON) from the database.

    python -m sim.export

Output in web/data/:
  runs.json                  what the knobs can pick, rule names and descriptions, defaults
  <run>/summary.json         Screen 1: each rule's scores, average + 95% range + every trial's value
  <run>/heatmap.json         Screen 2: % of trials where a site in each country ran short, per week
  <run>/trial_<seed>.json    Screen 3: week-by-week shelf numbers for each site (a few trials only)
A <run> is one knob position + scenario, e.g. "normal__surge" or "shelf_12__base".
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from sim import config as c
from sim.db import get_engine

OUT = Path("web/data")

# Names and one-line descriptions shown on screen (agreed in docs/dashboard_plan.md).
RULES = [
    {"code": "minmax", "name": "Fixed refill",
     "line": "When a site has 2 kits or fewer, refill it to 5."},
    {"code": "minmax_tuned", "name": "Fixed refill by region",
     "line": "Same idea, but each region has its own numbers."},
    {"code": "forecast", "name": "Recent use",
     "line": "Look at the last 8 weeks of use. Keep enough until the next shipment arrives, plus a cushion."},
    {"code": "schedule", "name": "Expected visits",
     "line": "Count the kits needed for the visits expected for current patients, plus 2 spare kits for new patients."},
    {"code": "schedule_bayes", "name": "Expected visits + site pace",
     "line": "Same, but estimate new patients from how fast this site has enrolled so far."},
    {"code": "ml", "name": "Expected visits + machine learning",
     "line": "A model trained on past trials predicts how many kits the site will need."},
]
METRICS = [
    {"key": "kits_short", "label": "Kits short (patient came, no kit)"},
    {"key": "stockout_events", "label": "Stockouts (site-weeks with a shortage)"},
    {"key": "kits_expired", "label": "Kits expired"},
    {"key": "kits_left_at_end", "label": "Kits left at close-out"},
    {"key": "kits_shipped", "label": "Kits shipped"},
    {"key": "shipments", "label": "Shipments sent"},
    {"key": "avg_kits_at_sites", "label": "Kits sitting at sites (average per week)"},
]
KNOB_LABELS = {
    "normal": "Normal", "safety_low": "Safety: low", "safety_high": "Safety: high",
    "shipping_plus1": "Shipping time: +1 week", "shelf_12": "Shelf life: 12 months",
    "shelf_36": "Shelf life: 36 months", "enroll_slower": "Enrollment: slower",
    "enroll_faster": "Enrollment: faster",
}
SCENARIO_LABELS = {"base": "No shock", "surge": "Surge", "stall": "Stall"}


def run_id(knob, scenario):
    return f"{knob}__{scenario}"


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    # separators without spaces keeps files small
    path.write_text(json.dumps(obj, separators=(",", ":")))


def sparse(weeks, values):
    """[[week, value], ...] for non-zero values only (most weeks are 0)."""
    return [[int(w), int(v)] for w, v in zip(weeks, values) if v]


def summary(conn, knob, scenario):
    r = pd.read_sql(text("""
        SELECT p.* FROM policy_result p JOIN trial t USING (trial_id)
        WHERE t.knob = :k AND t.scenario = :s ORDER BY p.trial_id"""), conn, params={"k": knob, "s": scenario})
    out = {"trials": int(r["trial_id"].nunique()), "rules": {}}
    for code, g in r.groupby("policy"):
        out["rules"][code] = {}
        for m in METRICS:
            v = g[m["key"]].to_numpy(dtype=float)
            half = 1.96 * v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else 0.0  # 95% range of the average
            out["rules"][code][m["key"]] = {
                "mean": round(float(v.mean()), 1), "low": round(float(v.mean() - half), 1),
                "high": round(float(v.mean() + half), 1), "per_trial": [round(float(x), 1) for x in v]}
    return out


def heatmap(conn, knob, scenario, countries):
    r = pd.read_sql(text("""
        SELECT policy, country, week, trials_with_stockout, trials FROM country_week_risk
        WHERE knob = :k AND scenario = :s"""), conn, params={"k": knob, "s": scenario})
    weeks = int(r["week"].max()) + 1 if len(r) else 0
    out = {"weeks": weeks, "rules": {}}
    for code in [x["code"] for x in RULES]:
        out["rules"][code] = {}
        for country in countries:
            row = np.zeros(weeks)
            g = r[(r["policy"] == code) & (r["country"] == country)]
            row[g["week"].to_numpy()] = 100.0 * g["trials_with_stockout"].to_numpy() / g["trials"].to_numpy()
            out["rules"][code][country] = [round(float(x), 1) for x in row]
    return out


def trial_timeline(conn, knob, scenario, seed):
    t = conn.execute(text("SELECT trial_id FROM trial WHERE knob = :k AND scenario = :s AND seed = :d"),
                     {"k": knob, "s": scenario, "d": seed}).scalar()
    inv = pd.read_sql(text("SELECT * FROM inventory_week WHERE trial_id = :t ORDER BY site_id, arm, policy, week"),
                      conn, params={"t": t})
    if inv.empty:
        return None  # this trial's week-by-week rows were not kept
    sites = pd.read_sql(text("SELECT * FROM site WHERE trial_id = :t ORDER BY site_id"), conn, params={"t": t})
    out = {"trial": seed, "end_week": int(inv["week"].max()), "sites": []}
    for s in sites.itertuples():
        site = {"site_id": int(s.site_id), "country": s.country, "region": s.region,
                "open_week": int(s.open_week), "stumbling": bool(s.is_stumbling), "arms": {}}
        for arm, ga in inv[inv["site_id"] == s.site_id].groupby("arm"):
            site["arms"][arm] = {}
            for code, g in ga.groupby("policy"):
                active = g[(g["on_hand"] > 0) | (g["in_transit"] > 0) | (g["kits_needed"] > 0) | g["target"].notna()]
                start = int(active["week"].min()) if len(active) else int(g["week"].max())
                g = g[g["week"] >= start]
                w = g["week"].to_numpy()
                site["arms"][arm][code] = {
                    "from": start,                                         # first week shown
                    "on_hand": g["on_hand"].astype(int).tolist(),          # kits on the shelf, end of week
                    "target": [None if pd.isna(x) else int(x) for x in g["target"]],
                    "needed": sparse(w, g["kits_needed"]),                 # [[week, kits], ...]
                    "short": sparse(w, g["kits_short"]),
                    "expired": sparse(w, g["kits_expired"]),
                    "arrived": sparse(w, g["kits_received"]),              # shipments arriving
                }
        out["sites"].append(site)
    return out


def main():
    engine = get_engine()
    with engine.connect() as conn:
        runs = pd.read_sql(text("SELECT DISTINCT knob, scenario FROM trial"), conn)
        done = [(k, s) for k, s in c.DASHBOARD_RUNS if ((runs["knob"] == k) & (runs["scenario"] == s)).any()]
        countries = [{"code": k, "region": r} for r, cs in c.REGIONS.items() for k in cs]
        index = {
            "study_start": str(c.STUDY_START), "rules": RULES, "metrics": METRICS,
            "default_rule": "schedule", "compare_rule": "minmax_tuned",
            "countries": countries, "runs": [], "detail_trials": [],
        }
        for knob, scenario in done:
            rid = run_id(knob, scenario)
            write(OUT / rid / "summary.json", summary(conn, knob, scenario))
            write(OUT / rid / "heatmap.json", heatmap(conn, knob, scenario, [x["code"] for x in countries]))
            seeds = pd.read_sql(text("""
                SELECT DISTINCT t.seed FROM trial t JOIN inventory_week i USING (trial_id)
                WHERE t.knob = :k AND t.scenario = :s ORDER BY t.seed"""), conn, params={"k": knob, "s": scenario})
            for seed in seeds["seed"]:
                write(OUT / rid / f"trial_{seed}.json", trial_timeline(conn, knob, scenario, int(seed)))
            index["runs"].append({"id": rid, "knob": knob, "knob_label": KNOB_LABELS[knob],
                                  "scenario": scenario, "scenario_label": SCENARIO_LABELS[scenario]})
            index["detail_trials"] = [int(x) for x in seeds["seed"]]
            print(f"exported {rid}: {len(seeds)} trial files")
        write(OUT / "runs.json", index)
    total = sum(f.stat().st_size for f in OUT.rglob("*.json"))
    print(f"\n{len(done)} runs, {total / 1e6:.1f} MB in {OUT}/")


if __name__ == "__main__":
    main()
