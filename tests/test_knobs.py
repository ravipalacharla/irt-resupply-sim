import pandas as pd
import pytest
from sqlalchemy import text

from sim import config as c
from sim.db import create_schema, get_engine
from sim.run import stockout_weeks, trial_id_for, run_trial


def test_knob_sets_and_restores():
    before = (dict(c.LEAD_TIME_WEEKS), c.SHELF_LIFE_MONTHS, c.FORECAST_Z, dict(c.MINMAX_TUNED))
    for name in c.KNOBS:
        old = c.set_knob(name)
        for k, v in c.KNOBS[name].items():
            assert getattr(c, k) == v
        c.restore_knob(old)
    assert (c.LEAD_TIME_WEEKS, c.SHELF_LIFE_MONTHS, c.FORECAST_Z, c.MINMAX_TUNED) == before


def test_knobs_change_results():
    base = run_trial(1)["policy_result"].set_index("policy")
    old = c.set_knob("shipping_plus1")
    slower = run_trial(1)["policy_result"].set_index("policy")
    c.restore_knob(old)
    assert (slower["kits_short"] >= base["kits_short"]).sum() >= 4   # slower shipping hurts most rules


def test_safety_levels_keep_min_below_max():
    for name in ["safety_low", "safety_high"]:
        for lo, hi in c.KNOBS[name]["MINMAX_TUNED"].values():
            assert 0 <= lo < hi
        assert c.KNOBS[name]["MINMAX_MIN"] < c.KNOBS[name]["MINMAX_MAX"]


def test_dashboard_plan_is_ten_unique_runs():
    assert len(c.DASHBOARD_RUNS) == 10 == len(set(c.DASHBOARD_RUNS))
    ids = {trial_id_for(s, seed, k) for k, s in c.DASHBOARD_RUNS for seed in range(200)}
    assert len(ids) == 10 * 200


def test_stockout_weeks_are_real_shortfalls():
    t = run_trial(2)
    flagged = stockout_weeks(t)
    inv = t["inventory_week"].merge(t["site"][["site_id", "country"]], on="site_id")
    for r in flagged.head(50).itertuples():
        rows = inv[(inv["policy"] == r.policy) & (inv["country"] == r.country) & (inv["week"] == r.week)]
        assert rows["kits_short"].sum() > 0


def test_small_run_stores_detail_only_for_first_trials(monkeypatch):
    eng = get_engine()
    try:
        eng.connect().close()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e}")
    create_schema(eng)
    # A throwaway knob position that exists only during this test, so its trial ids and
    # Screen 2 rows can never clash with (or delete) real dashboard results.
    import sim.run as run
    knob = "test_only"
    monkeypatch.setitem(c.KNOBS, knob, {})
    monkeypatch.setattr(run, "KNOB_NAMES", run.KNOB_NAMES + [knob])
    ids = [run.trial_id_for("base", s, knob) for s in range(3)]
    assert min(ids) >= len(c.KNOBS) * 1_000_000 - 1_000_000  # beyond every real knob's ids
    try:
        run.run_one(eng, knob, "base", seeds=3, detail_trials=1, start=0)
        with eng.connect() as conn:
            detail = [conn.execute(text("SELECT count(*) FROM inventory_week WHERE trial_id = :t"), {"t": i}).scalar()
                      for i in ids]
            scores = conn.execute(text("SELECT count(*) FROM policy_result WHERE trial_id = ANY(:t)"), {"t": ids}).scalar()
            risk = conn.execute(text("SELECT max(trials) FROM country_week_risk WHERE knob = :k"), {"k": knob}).scalar()
        assert detail[0] > 0 and detail[1] == 0 and detail[2] == 0
        assert scores == 3 * 6
        assert risk == 3
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM trial WHERE trial_id = ANY(:t)"), {"t": ids})
            conn.execute(text("DELETE FROM country_week_risk WHERE knob = :k"), {"k": knob})
