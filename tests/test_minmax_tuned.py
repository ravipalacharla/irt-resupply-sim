import pandas as pd

from sim import config as c
from sim.generator import generate_trial
from sim.network import simulate_supply
from sim.policies import minmax_tuned
from sim.tune_minmax import pick


def test_tuning_seeds_do_not_overlap_scoring_seeds():
    assert c.TUNING_SEED_START >= 200
    assert set(c.MINMAX_TUNED) == set(c.REGIONS)


def test_uses_each_regions_levels():
    trial = generate_trial(c.make_rng(0))
    inv = simulate_supply(trial, minmax_tuned)["inventory_week"]
    inv = inv.merge(trial["site"][["site_id", "region"]], on="site_id")
    for region, (low, high) in c.MINMAX_TUNED.items():
        r = inv[inv["region"] == region]
        ordered = r[r["kits_ordered"] > 0]
        assert (ordered["on_hand"] + ordered["in_transit"] == high).all()
        assert (r["on_hand"] + r["in_transit"] <= high).all()


def test_pick_matches_service_then_least_waste():
    grid = pd.DataFrame([
        # region, low, high, short, expired, shipments
        ("X", 1, 3, 9.0, 1.0, 10),   # too many short
        ("X", 2, 5, 2.0, 8.0, 12),   # meets service, more waste
        ("X", 3, 6, 1.0, 6.0, 20),   # meets service, least waste  <- pick
        ("Y", 1, 2, 7.0, 1.0, 10),   # nothing meets service: fewest short wins
        ("Y", 2, 4, 5.0, 3.0, 10),   # <- pick
    ], columns=["region", "low", "high", "kits_short", "kits_expired", "shipments"])
    assert pick(grid, pd.Series({"X": 2.0, "Y": 1.0})) == {"X": (3, 6), "Y": (2, 4)}
