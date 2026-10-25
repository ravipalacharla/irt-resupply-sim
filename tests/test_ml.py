import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial
from sim.ml import FEATURES, build_features, predict_need
from sim.network import demand_by_site_arm, simulate_supply
from sim.policies import ml


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


@pytest.fixture(scope="module")
def tiny_model(tmp_path_factory):
    # Small model on 2 training trials: enough to exercise the code, fast to train.
    data = pd.concat([build_features(generate_trial(c.make_rng(c.TRAINING_SEED_START + i))) for i in range(2)])
    model = lgb.train(c.ML_PARAMS, lgb.Dataset(data[FEATURES], data["label"]), num_boost_round=20)
    path = tmp_path_factory.mktemp("model") / "tiny.txt"
    model.save_model(str(path))
    ml.load_model(str(path))  # the ML rule uses this model during these tests
    yield model
    ml._model = None          # afterwards, go back to the real model (loaded on next use)


def cut_future(trial, cut):
    """Copy of the trial with everything unknowable at week cut-1 removed."""
    p = trial["patient"]
    p_cut = p[p["enroll_week"] < cut].copy()
    p_cut["end_week"] = np.where(p_cut["end_week"] > cut, cut + 1, p_cut["end_week"])
    v = trial["visit"]
    v_cut = v[v["patient_id"].isin(p_cut["patient_id"]) & (v["week"] < cut)]
    sw = trial["site_week"].copy()
    sw.loc[sw["week"] >= cut, ["enrolled", "kits_needed"]] = 0
    return dict(trial, patient=p_cut, visit=v_cut, site_week=sw)


def test_features_never_use_the_future(trial):
    cut = 60
    assert trial["patient"]["enroll_week"].max() + 1 > cut   # still enrolling at the cut
    full = build_features(trial, with_label=False)
    erased = build_features(cut_future(trial, cut), with_label=False)
    cols = ["site_id", "arm_name", "week"] + FEATURES
    a = full[full["week"] < cut][cols].sort_values(cols[:3] + ["h"]).reset_index(drop=True)
    b = erased[erased["week"] < cut][cols].sort_values(cols[:3] + ["h"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_label_is_need_h_weeks_later(trial):
    f = build_features(trial)
    demand = demand_by_site_arm(trial)
    sample = f.sample(2000, random_state=0)  # random_state: fixed sample, reproducible
    for r in sample.itertuples():
        need = demand.get((r.site_id, r.arm_name), np.zeros(c.TRIAL_WEEKS))
        assert r.label == need[r.week + r.h]


def test_rows_only_where_rule_can_be_asked(trial):
    f = build_features(trial)
    assert (f["weeks_open"] >= -f["lead_time"]).all()
    assert (f["week"] + f["h"] < c.TRIAL_WEEKS).all()


def test_predictions_non_negative_and_reproducible(trial, tiny_model):
    a, b = predict_need(trial, tiny_model), predict_need(trial, tiny_model)
    for k in a:
        assert (a[k] >= 0).all()
        assert (a[k] == b[k]).all()


def test_ml_rule_never_sees_future(trial, tiny_model):
    cut = 60
    full = simulate_supply(trial, ml)["inventory_week"]
    erased = simulate_supply(cut_future(trial, cut), ml)["inventory_week"]
    pd.testing.assert_frame_equal(full[full["week"] < cut].reset_index(drop=True),
                                  erased[erased["week"] < cut].reset_index(drop=True))


def test_ml_rule_inventory_invariants(trial, tiny_model):
    inv = simulate_supply(trial, ml)["inventory_week"].sort_values(["site_id", "arm", "week"])
    assert (inv[["on_hand", "in_transit"]] >= 0).all().all()
    assert (inv["kits_dispensed"] + inv["kits_short"] == inv["kits_needed"]).all()
    prev = inv.groupby(["site_id", "arm"])["on_hand"].shift(fill_value=0)
    assert (inv["on_hand"] == prev + inv["kits_received"] - inv["kits_dispensed"] - inv["kits_expired"]).all()


def test_ml_rule_order_logic():
    known = {"lead_time": 2, "enrolling": True,
             "prepared": np.array([1.0, 0.2, 1.1, 9, 9, 9, 9, 9]),   # expected 2.3 over cover=3
             "scheduled": np.array([1, 0, 1, 9, 9, 9, 9, 9])}         # booked 2
    order, target = ml.order_qty(1, 0, known)
    # new = 0.3 -> spare = max(0.3 + 1.65*sqrt(0.3), floor 2) = 2 -> target = ceil(2 + 2) = 4
    assert target == 4 and order == 3
    known["enrolling"] = False
    assert ml.order_qty(0, 0, known)[1] == 2   # no spare once enrollment is closed


def test_training_seeds_separate_from_tuning_and_scoring():
    assert c.TRAINING_SEED_START >= c.TUNING_SEED_START + c.TUNING_TRIALS
    assert c.TRAINING_SEED_START > 200
