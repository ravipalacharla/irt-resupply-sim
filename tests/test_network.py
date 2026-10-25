import numpy as np
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial
from sim.metrics import summarize
from sim.network import make_lots, simulate_supply
from sim.policies import minmax


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


@pytest.fixture(scope="module")
def supply(trial):
    return simulate_supply(trial, minmax)


def test_lots_expire_shelf_life_after_manufacture():
    lots = make_lots()
    months = ((lots["expiry_date"].dt.year - lots["mfg_date"].dt.year) * 12
              + lots["expiry_date"].dt.month - lots["mfg_date"].dt.month)
    assert (months == c.SHELF_LIFE_MONTHS).all()
    assert set(lots["arm"]) == set(c.ARMS)
    assert lots["release_week"].min() == 0


def test_reproducible(trial):
    a, b = simulate_supply(trial, minmax), simulate_supply(trial, minmax)
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_supply_does_not_change_trial(trial):
    before = {k: v.copy() for k, v in trial.items()}
    simulate_supply(trial, minmax)
    for k in trial:
        pd.testing.assert_frame_equal(trial[k], before[k])


def test_inventory_never_negative(supply):
    inv = supply["inventory_week"]
    assert (inv[["on_hand", "in_transit", "kits_short", "kits_dispensed"]] >= 0).all().all()


def test_weekly_balance(supply):
    # end on hand = previous end on hand + received - dispensed - expired
    inv = supply["inventory_week"].sort_values(["site_id", "arm", "week"])
    prev = inv.groupby(["site_id", "arm"])["on_hand"].shift(fill_value=0)  # shift = previous week's row
    assert (inv["on_hand"] == prev + inv["kits_received"] - inv["kits_dispensed"] - inv["kits_expired"]).all()


def test_dispensed_plus_short_equals_demand(trial, supply):
    inv = supply["inventory_week"]
    assert (inv["kits_dispensed"] + inv["kits_short"] == inv["kits_needed"]).all()
    assert inv["kits_needed"].sum() == trial["visit"]["kits"].sum()


def test_shipments_arrive_after_lead_time(trial, supply):
    ship = supply["shipment"].merge(trial["site"][["site_id", "region"]], on="site_id")
    assert (ship["arrive_week"] - ship["ship_week"] == ship["region"].map(c.LEAD_TIME_WEEKS)).all()


def test_shipped_lot_was_released(supply):
    ship = supply["shipment"].merge(supply["lot"], on=["lot_id", "arm"])
    assert (ship["release_week"] <= ship["ship_week"]).all()


def test_shipments_arrive_with_usable_shelf_life(supply):
    # No box should land already past the dispense cutoff (that would be instant waste).
    ship = supply["shipment"].merge(supply["lot"], on=["lot_id", "arm"])
    assert (ship["expiry_week"] > ship["arrive_week"] + c.DISPENSE_BUFFER_WEEKS).all()


def test_kits_conserved(supply):
    # Everything shipped is dispensed, expired, or still on hand / in transit at the end.
    inv, ship = supply["inventory_week"], supply["shipment"]
    s = summarize(supply).iloc[0]
    assert ship["kits"].sum() == inv["kits_dispensed"].sum() + inv["kits_expired"].sum() + s["kits_left_at_end"]
    assert inv["kits_received"].sum() + inv["in_transit"][inv["week"] == c.TRIAL_WEEKS - 1].sum() == ship["kits"].sum()


def test_minmax_orders_up_to_max(supply):
    inv = supply["inventory_week"]
    ordered = inv[inv["kits_ordered"] > 0]
    assert (ordered["on_hand"] + ordered["in_transit"] == c.MINMAX_MAX).all()
    assert (inv["on_hand"] + inv["in_transit"] <= c.MINMAX_MAX).all()


def test_first_box_arrives_on_opening_day(trial, supply):
    first = supply["shipment"].groupby("site_id")["arrive_week"].min()
    opens = trial["site"].set_index("site_id")["open_week"]
    assert (first == opens.loc[first.index]).all()


def test_no_shipments_to_finished_sites(trial, supply):
    # After enrollment closes, a site with nobody on treatment gets nothing new.
    p = trial["patient"]
    closed_from = p["enroll_week"].max() + 1
    ship = supply["shipment"][supply["shipment"]["ship_week"] >= closed_from]
    for r in ship.itertuples():
        on = p[(p["site_id"] == r.site_id) & (p["enroll_week"] <= r.ship_week) & (p["end_week"] > r.ship_week)]
        assert len(on) > 0


def test_baseline_has_real_stockouts_and_waste():
    res = pd.concat([summarize(simulate_supply(generate_trial(c.make_rng(s)), minmax)) for s in range(10)])
    assert (res["stockout_events"] > 0).all()
    assert (res["kits_expired"] > 0).all()
    assert np.mean(res["kits_short"]) > 50
    assert np.mean(res["kits_expired"]) > 50
