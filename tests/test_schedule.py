import numpy as np
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial
from sim.network import scheduled_kits, simulate_supply
from sim.policies import schedule


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


def known(scheduled, enroll_history, lead_time=2, enrolling=True, arm="A"):
    sched = np.zeros(c.SCHEDULE_LOOKAHEAD_WEEKS, dtype=int)
    sched[: len(scheduled)] = scheduled
    return {"scheduled": sched, "enroll_history": np.asarray(enroll_history),
            "lead_time": lead_time, "enrolling": enrolling, "arm": arm}


def test_scheduled_kits_match_actual_visits_when_nobody_stops_early(trial):
    # Keep only patients who never stop early: then the schedule must equal their real
    # future visits exactly, for every site, arm, week, and look-ahead step.
    p = trial["patient"][~trial["patient"]["discontinued"]]
    v = trial["visit"][trial["visit"]["patient_id"].isin(p["patient_id"])]
    v = v.merge(p[["patient_id", "site_id", "enroll_week"]], on="patient_id")
    sched = scheduled_kits(dict(trial, patient=p, visit=v))
    checked = 0
    for (site_id, arm), arr in sched.items():
        g = v[(v["site_id"] == site_id) & (v["arm"] == arm)]
        for w in range(0, c.TRIAL_WEEKS, 7):
            for i in range(c.SCHEDULE_LOOKAHEAD_WEEKS):
                real = g[(g["enroll_week"] <= w) & (g["week"] == w + 1 + i)]["kits"].sum()
                assert arr[w, i] == real
                checked += 1
    assert checked > 1000


def test_schedule_never_includes_stopped_or_future_patients(trial):
    sched = scheduled_kits(trial)
    p = trial["patient"]
    for (site_id, arm), arr in sched.items():
        g = p[(p["site_id"] == site_id) & (p["arm"] == arm)]
        for w in [0, 50, 100, 150]:
            on_now = ((g["enroll_week"] <= w) & (g["end_week"] > w)).sum()
            assert arr[w].sum() <= on_now * c.SCHEDULE_LOOKAHEAD_WEEKS  # nobody else contributes
            if on_now == 0:
                assert arr[w].sum() == 0


def test_target_is_scheduled_plus_spare():
    # lead 2 -> cover 3 weeks: kits due 1+1+1 = 3 (the 5 in week 4 is outside the window).
    # No recent enrollment -> spare is the floor.
    order, target = schedule.order_qty(0, 0, known([1, 1, 1, 5], [0] * 8))
    assert target == 3 + c.FORECAST_FLOOR and order == target
    # recent enrollment raises the spare above the floor
    _, busier = schedule.order_qty(0, 0, known([1, 1, 1], [2] * 8))
    assert busier > target


def test_floor_is_on_top_of_scheduled_kits():
    # A site whose existing patients already need many kits still keeps spare kits.
    _, target = schedule.order_qty(0, 0, known([2, 2, 2], [0] * 8))
    assert target == 6 + c.FORECAST_FLOOR


def test_no_spare_after_enrollment_closes():
    _, target = schedule.order_qty(0, 0, known([1, 0, 0], [1] * 8, enrolling=False))
    assert target == 1


def test_schedule_rule_never_sees_future(trial):
    # Remove everything after week 60 that a rule could not know at week 59: patients who
    # enroll later, and the remaining visits / end dates of patients still on treatment.
    cut = 60
    p = trial["patient"]
    p_cut = p[p["enroll_week"] < cut].copy()
    p_cut["end_week"] = np.where(p_cut["end_week"] > cut, cut + 1, p_cut["end_week"])
    v_cut = trial["visit"][trial["visit"]["patient_id"].isin(p_cut["patient_id"]) & (trial["visit"]["week"] < cut)]
    sw = trial["site_week"].copy()
    sw.loc[sw["week"] >= cut, ["enrolled", "kits_needed"]] = 0
    cut_trial = dict(trial, patient=p_cut, visit=v_cut, site_week=sw)
    # Enrollment-closed week is the one thing that differs (target not yet reached in the cut
    # trial), so compare only while the real trial is still enrolling.
    closed_from = p["enroll_week"].max() + 1
    assert closed_from > cut
    full = simulate_supply(trial, schedule)["inventory_week"]
    erased = simulate_supply(cut_trial, schedule)["inventory_week"]
    pd.testing.assert_frame_equal(full[full["week"] < cut].reset_index(drop=True),
                                  erased[erased["week"] < cut].reset_index(drop=True))


def test_schedule_invariants(trial):
    inv = simulate_supply(trial, schedule)["inventory_week"].sort_values(["site_id", "arm", "week"])
    assert (inv[["on_hand", "in_transit"]] >= 0).all().all()
    assert (inv["kits_dispensed"] + inv["kits_short"] == inv["kits_needed"]).all()
    prev = inv.groupby(["site_id", "arm"])["on_hand"].shift(fill_value=0)
    assert (inv["on_hand"] == prev + inv["kits_received"] - inv["kits_dispensed"] - inv["kits_expired"]).all()
    asked = inv["target"].notna()
    assert ((inv.loc[asked, "kits_ordered"] > 0) <= (inv.loc[asked, "on_hand"] + inv.loc[asked, "in_transit"] == inv.loc[asked, "target"])).all()
