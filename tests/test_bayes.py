import numpy as np
import pandas as pd
import pytest
from scipy import stats

from sim import config as c
from sim.bayes import exposure, fit_prior, nb_quantile, new_patients_quantile, posterior, ramp
from sim.generator import generate_trial
from sim.network import simulate_supply
from sim.policies import schedule_bayes

from tests.test_ml import cut_future


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


def test_nb_quantile_matches_reference():
    # scipy (reference implementation) uses the same parameterisation: failures before r successes.
    for r, p in [(0.84, 0.9), (3.2, 0.5), (10.0, 0.7), (0.5, 0.99)]:
        for q in [0.5, 0.9, 0.95, 0.99]:
            assert nb_quantile(r, p, q) == stats.nbinom.ppf(q, r, p)


def test_exposure_counts_ramp_up():
    assert exposure(0, c.RAMP_UP_WEEKS - 1) == pytest.approx(sum((k + 1) / c.RAMP_UP_WEEKS for k in range(c.RAMP_UP_WEEKS)))
    assert exposure(-5, -1) == 0.0                     # before opening: no exposure
    assert exposure(50, 59) == pytest.approx(10.0)     # fully ramped: one per week
    assert ramp(0) == pytest.approx(1 / c.RAMP_UP_WEEKS)


def test_posterior_moves_toward_data():
    prior_mean = c.BAYES_PRIOR[0] / c.BAYES_PRIOR[1]
    busy = posterior(c.BAYES_PRIOR, 10, 40.0)
    quiet = posterior(c.BAYES_PRIOR, 0, 40.0)
    assert busy[0] / busy[1] > prior_mean > quiet[0] / quiet[1]


def test_fit_prior_recovers_known_gamma():
    rng = np.random.default_rng(1)
    alpha, beta = 2.0, 20.0                            # true mean 0.1/week
    e = rng.uniform(20, 80, 5000)
    n = rng.poisson(rng.gamma(alpha, 1 / beta, 5000) * e)
    a_hat, b_hat = fit_prior(n, e)
    assert a_hat / b_hat == pytest.approx(alpha / beta, rel=0.05)
    assert a_hat == pytest.approx(alpha, rel=0.2)


def test_more_patients_more_spare():
    post_quiet = posterior(c.BAYES_PRIOR, 0, 30.0)
    post_busy = posterior(c.BAYES_PRIOR, 15, 30.0)
    assert new_patients_quantile(post_busy, 4, 0.5, 0.95) > new_patients_quantile(post_quiet, 4, 0.5, 0.95)
    assert new_patients_quantile(post_busy, 0, 0.5, 0.95) == 0


def test_rule_floor_and_closed():
    known = {"lead_time": 2, "enrolling": True, "weeks_open": 20, "arm": "A",
             "enroll_history": np.zeros(30, dtype=int), "scheduled": np.array([1, 0, 1, 0, 0, 0, 0, 0])}
    _, target = schedule_bayes.order_qty(0, 0, known)
    assert target == 2 + c.FORECAST_FLOOR
    known["enrolling"] = False
    assert schedule_bayes.order_qty(0, 0, known)[1] == 2


def test_bayes_rule_never_sees_future(trial):
    cut = 60
    full = simulate_supply(trial, schedule_bayes)["inventory_week"]
    erased = simulate_supply(cut_future(trial, cut), schedule_bayes)["inventory_week"]
    pd.testing.assert_frame_equal(full[full["week"] < cut].reset_index(drop=True),
                                  erased[erased["week"] < cut].reset_index(drop=True))


def test_bayes_rule_inventory_invariants(trial):
    inv = simulate_supply(trial, schedule_bayes)["inventory_week"].sort_values(["site_id", "arm", "week"])
    assert (inv[["on_hand", "in_transit"]] >= 0).all().all()
    assert (inv["kits_dispensed"] + inv["kits_short"] == inv["kits_needed"]).all()
    prev = inv.groupby(["site_id", "arm"])["on_hand"].shift(fill_value=0)
    assert (inv["on_hand"] == prev + inv["kits_received"] - inv["kits_dispensed"] - inv["kits_expired"]).all()
