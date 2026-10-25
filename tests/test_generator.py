import numpy as np
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial


@pytest.fixture(scope="module")
def trial():
    return generate_trial(c.make_rng(0))


@pytest.fixture(scope="module")
def many_trials():
    return [generate_trial(c.make_rng(s)) for s in range(20)]


def test_reproducible():
    a, b = generate_trial(c.make_rng(3)), generate_trial(c.make_rng(3))
    for name in a:
        pd.testing.assert_frame_equal(a[name], b[name])


def test_different_seeds_differ():
    a, b = generate_trial(c.make_rng(1)), generate_trial(c.make_rng(2))
    assert not a["patient"].equals(b["patient"])


def test_site_counts_match_config(trial):
    s = trial["site"]
    expected = {(r, k): n for r, cs in c.REGIONS.items() for k, n in cs.items()}
    assert s.groupby(["region", "country"]).size().to_dict() == expected


def test_sites_open_after_country_approval(trial):
    s = trial["site"]
    assert (s["open_week"] >= s["country_approval_week"]).all()
    # all sites in a country share one approval week
    assert (s.groupby("country")["country_approval_week"].nunique() == 1).all()


def test_enrollment_hits_target_exactly(many_trials):
    for t in many_trials:
        assert len(t["patient"]) == c.ENROLL_TARGET
        assert t["site_week"]["enrolled"].sum() == c.ENROLL_TARGET


def test_no_enrollment_before_site_opens(trial):
    sw = trial["site_week"]
    assert sw.loc[~sw["is_open"], "enrolled"].sum() == 0
    assert sw.loc[~sw["is_open"], "kits_needed"].sum() == 0


def test_visits_within_treatment_window(trial):
    v = trial["visit"].merge(trial["patient"], on="patient_id")
    assert (v["week"] >= v["enroll_week"]).all()
    assert (v["week"] < v["end_week"]).all()
    assert (v["week"] < c.TRIAL_WEEKS).all()


def test_visit_spacing_and_first_visit(trial):
    v = trial["visit"].merge(trial["patient"], on="patient_id")
    first = v[v["visit_num"] == 1]
    assert (first["week"] == first["enroll_week"]).all()
    assert len(first) == len(trial["patient"])  # every patient gets a first dispense
    gaps = v.sort_values(["patient_id", "visit_num"]).groupby("patient_id")["week"].diff().dropna()
    assert (gaps == c.VISIT_INTERVAL_WEEKS).all()


def test_treatment_never_exceeds_max(trial):
    p = trial["patient"]
    assert ((p["end_week"] - p["enroll_week"]) <= c.MAX_WEEKS_ON_TREATMENT).all()


def test_site_week_kits_match_visits(trial):
    assert trial["site_week"]["kits_needed"].sum() == trial["visit"]["kits"].sum()


def test_arms_roughly_balanced(trial):
    share = trial["patient"]["arm"].value_counts(normalize=True)
    for arm, target in c.ARMS.items():
        assert abs(share[arm] - target) < 0.07


def test_s_shaped_cumulative_enrollment(many_trials):
    # Enrollment pace in the middle half of the enrollment period should beat
    # both the first and last eighths (slow start, steady middle, stop at target).
    for t in many_trials:
        w = t["patient"]["enroll_week"]
        start, end = w.min(), w.max()
        span = end - start + 1
        weekly = w.value_counts().reindex(range(start, end + 1), fill_value=0)
        first = weekly.iloc[: span // 8].mean()
        middle = weekly.iloc[span // 4: 3 * span // 4].mean()
        assert middle > 2 * first


def test_long_tail_sites(many_trials):
    # A few sites carry most patients; stumbling sites enroll far less.
    top_share, stumble_ratio = [], []
    for t in many_trials:
        s = t["site"]
        per_site = t["patient"].groupby("site_id").size().reindex(s["site_id"], fill_value=0)
        top = per_site.sort_values(ascending=False).iloc[: len(s) // 5]
        top_share.append(top.sum() / per_site.sum())
        by_stumble = per_site.groupby(s.set_index("site_id")["is_stumbling"]).mean()
        stumble_ratio.append(by_stumble[True] / by_stumble[False])
    assert np.mean(top_share) > 0.4
    assert np.mean(stumble_ratio) < 0.3
