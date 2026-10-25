import numpy as np
import pandas as pd

from sim import config as c
from sim.generator import generate_trial, shock_multiplier
from sim.run import run_trial, trial_id_for


def make(seed, scenario):
    return generate_trial(c.make_rng(seed), scenario, c.make_rng(seed, stream=1))


def test_base_has_no_shock():
    mult, hit, start = shock_multiplier(c.make_rng(0, stream=1), 78, None)
    assert (mult == 1).all() and not hit.any() and start is None


def test_shock_only_hits_chosen_sites_in_window():
    shock = c.SCENARIOS["surge"]
    mult, hit, start = shock_multiplier(c.make_rng(0, stream=1), 78, shock)
    assert c.SHOCK_START_WEEKS[0] <= start <= c.SHOCK_START_WEEKS[1]
    window = slice(start, start + shock["weeks"])
    assert (mult[hit, window] == shock["factor"]).all()
    assert (mult[~hit] == 1).all()
    outside = np.ones(c.TRIAL_WEEKS, dtype=bool)
    outside[window] = False
    assert (mult[:, outside] == 1).all()
    assert 0.1 < hit.mean() < 0.5  # roughly the configured share


def test_stall_sites_enroll_nobody_during_stall():
    t = make(0, "stall")
    s = t["site"]
    start = int(s["shock_start_week"].dropna().iloc[0])
    weeks = c.SCENARIOS["stall"]["weeks"]
    sw = t["site_week"].merge(s[["site_id", "shocked"]], on="site_id")
    in_window = sw["week"].between(start, start + weeks - 1)
    assert sw.loc[sw["shocked"] & in_window, "enrolled"].sum() == 0


def test_shocked_trial_shares_sites_with_base():
    # The shock uses its own random stream, so sites (opening, pace) are identical to base.
    base, surge = make(5, "base"), make(5, "surge")
    cols = ["site_id", "region", "country", "open_week", "pace_per_week", "is_stumbling"]
    pd.testing.assert_frame_equal(base["site"][cols], surge["site"][cols])


def test_surge_fills_faster_than_base():
    faster = [make(s, "surge")["patient"]["enroll_week"].max() <= make(s, "base")["patient"]["enroll_week"].max()
              for s in range(10)]
    assert np.mean(faster) >= 0.8


def test_every_scenario_still_hits_target():
    for scenario in c.SCENARIOS:
        assert len(make(1, scenario)["patient"]) == c.ENROLL_TARGET


def test_trial_ids_unique_across_scenarios():
    ids = {trial_id_for(sc, s) for sc in c.SCENARIOS for s in range(c.TUNING_SEED_START)}
    assert len(ids) == len(c.SCENARIOS) * c.TUNING_SEED_START


def test_run_trial_reproducible_per_scenario():
    a, b = run_trial(3, "stall"), run_trial(3, "stall")
    pd.testing.assert_frame_equal(a["policy_result"], b["policy_result"])
