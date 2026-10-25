import numpy as np
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial
from sim.metrics import compare, summarize
from sim.network import simulate_supply
from sim.policies import forecast, minmax


def known(history, lead_time, enrolling):
    return {"history": np.asarray(history), "lead_time": lead_time, "enrolling": enrolling}


def qty(*args):
    return forecast.order_qty(0, 0, known(*args))[0]


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


@pytest.fixture(scope="module")
def supply(trial):
    return simulate_supply(trial, forecast)


def test_rule_never_sees_future_demand(trial):
    # Erase every visit from week 60 on. If the rule never peeks ahead, every row
    # before week 60 (orders, stock, shortfalls) must be identical to the full run.
    cut = 60
    future_erased = dict(trial, visit=trial["visit"][trial["visit"]["week"] < cut])
    full = simulate_supply(trial, forecast)["inventory_week"]
    erased = simulate_supply(future_erased, forecast)["inventory_week"]
    pd.testing.assert_frame_equal(full[full["week"] < cut].reset_index(drop=True),
                                  erased[erased["week"] < cut].reset_index(drop=True))
    assert not full.equals(erased)  # sanity: the erase did change later weeks


def test_forecast_inventory_invariants(trial, supply):
    inv = supply["inventory_week"].sort_values(["site_id", "arm", "week"])
    assert (inv[["on_hand", "in_transit"]] >= 0).all().all()
    assert (inv["kits_dispensed"] + inv["kits_short"] == inv["kits_needed"]).all()
    prev = inv.groupby(["site_id", "arm"])["on_hand"].shift(fill_value=0)
    assert (inv["on_hand"] == prev + inv["kits_received"] - inv["kits_dispensed"] - inv["kits_expired"]).all()


def test_floor_while_enrolling(trial):
    # With no use at all, the rule still keeps the floor while enrolling, and nothing after.
    assert qty(np.zeros(10, dtype=int), 2, True) == c.FORECAST_FLOOR
    assert qty(np.zeros(10, dtype=int), 2, False) == 0


def test_target_grows_with_use_and_lead_time():
    busy = np.array([2, 1, 2, 2, 1, 2, 2, 1])
    assert qty(busy, 3, True) > qty(busy, 1, True)
    assert qty(busy, 2, True) > qty(busy // 2, 2, True)


def test_compare_is_paired_difference():
    res = pd.DataFrame({
        "trial_id": [0, 0, 1, 1], "policy": ["minmax", "forecast"] * 2,
        "kits_short": [10, 4, 20, 14],
    })
    out = compare(res).loc["kits_short"]
    assert out["diff"] == -6
    assert out["ci_low"] == out["ci_high"] == -6  # identical differences -> zero-width interval


def test_both_rules_face_same_demand(trial):
    a = simulate_supply(trial, minmax)["inventory_week"]
    b = simulate_supply(trial, forecast)["inventory_week"]
    assert (a["kits_needed"].to_numpy() == b["kits_needed"].to_numpy()).all()
