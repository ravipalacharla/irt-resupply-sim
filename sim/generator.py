"""Builds one synthetic trial: sites, weekly enrollment, patients, visits.

Call generate_trial(rng) and get back a dict of DataFrames, one per table
in sql/schema.sql (without trial_id; the loader adds it).
"""

import numpy as np
import pandas as pd

from sim import config as c


def trial_end_week(trial):
    """First week after the last visit: the trial is simulated up to here (close-out included)."""
    return int(trial["visit"]["week"].max()) + 1


def week_to_date(weeks):
    # Works on a single int or a pandas Series of ints.
    return pd.Timestamp(c.STUDY_START) + pd.to_timedelta(weeks * 7, unit="D")


def make_sites(rng):
    rows = []
    for region, countries in c.REGIONS.items():
        for country, n_sites in countries.items():
            approval = int(rng.integers(c.COUNTRY_APPROVAL_WEEKS[0], c.COUNTRY_APPROVAL_WEEKS[1] + 1))
            # Log-normal with mean 1: exp(N(-sd^2/2, sd)).
            country_factor = rng.lognormal(-c.COUNTRY_EFFECT_SD ** 2 / 2, c.COUNTRY_EFFECT_SD)
            for _ in range(n_sites):
                rows.append({"region": region, "country": country, "country_approval_week": approval,
                             "country_factor": country_factor})
    sites = pd.DataFrame(rows)
    n = len(sites)

    lag = np.round(rng.exponential(c.SITE_OPEN_LAG_MEAN_WEEKS, n)).astype(int)
    sites["open_week"] = sites["country_approval_week"] + lag

    # Gamma(shape, scale) has mean shape*scale, so scale = mean/shape.
    pace = rng.gamma(c.SITE_PACE_SHAPE, c.SITE_PACE_MEAN / c.SITE_PACE_SHAPE, n)
    stumbling = rng.random(n) < c.STUMBLE_SHARE
    pace = pace * sites.pop("country_factor").to_numpy()
    sites["pace_per_week"] = np.where(stumbling, pace * c.STUMBLE_FACTOR, pace)
    sites["is_stumbling"] = stumbling

    sites.insert(0, "site_id", np.arange(1, n + 1))
    return sites


def shock_multiplier(shock_rng, n_sites, shock):
    """Pace multiplier [site, week] for a stress scenario, plus which sites were hit and when.

    Base scenario (shock=None): all ones, nobody hit.
    """
    mult = np.ones((n_sites, c.TRIAL_WEEKS))
    if shock is None:
        return mult, np.zeros(n_sites, dtype=bool), None
    hit = shock_rng.random(n_sites) < shock["share"]
    start = int(shock_rng.integers(c.SHOCK_START_WEEKS[0], c.SHOCK_START_WEEKS[1] + 1))
    mult[hit, start:start + shock["weeks"]] = shock["factor"]
    return mult, hit, start


def make_enrollment(rng, sites, mult):
    """Matrix [site, week] of patients enrolled, capped at ENROLL_TARGET."""
    weeks = np.arange(c.TRIAL_WEEKS)
    # weeks_open[i, w] = how many weeks site i has been open at week w (negative = not open yet).
    # [:, None] turns the column into shape (sites, 1) so it subtracts against every week.
    weeks_open = weeks[None, :] - sites["open_week"].to_numpy()[:, None]
    ramp = np.clip((weeks_open + 1) / c.RAMP_UP_WEEKS, 0, 1)
    # Pace drift: log random walk from opening week; -sd^2/2 per step keeps the average at 1.
    steps = rng.normal(-c.PACE_DRIFT_SD ** 2 / 2, c.PACE_DRIFT_SD, weeks_open.shape)
    drift = np.exp(np.cumsum(np.where(weeks_open >= 0, steps, 0.0), axis=1))
    # Bursts: some weeks at BURST_FACTOR x pace, the rest scaled so the average is unchanged.
    calm = (1 - c.BURST_PROB * c.BURST_FACTOR) / (1 - c.BURST_PROB)
    burst = np.where(rng.random(weeks_open.shape) < c.BURST_PROB, c.BURST_FACTOR, calm)
    rate = sites["pace_per_week"].to_numpy()[:, None] * ramp * mult * drift * burst
    counts = rng.poisson(rate)

    # Stop at target: find the week the running total crosses it, zero everything after,
    # and randomly drop the overshoot from that week's patients.
    running = counts.sum(axis=0).cumsum()
    if running[-1] > c.ENROLL_TARGET:
        stop = int(np.argmax(running >= c.ENROLL_TARGET))
        counts[:, stop + 1:] = 0
        before = running[stop - 1] if stop > 0 else 0
        keep = c.ENROLL_TARGET - before
        candidates = np.repeat(np.arange(len(sites)), counts[:, stop])  # one entry per patient
        kept = rng.choice(candidates, size=keep, replace=False)
        counts[:, stop] = np.bincount(kept, minlength=len(sites))
    return counts


def make_patients(rng, sites, counts):
    site_idx, enroll_week = np.nonzero(counts)
    n_per_cell = counts[site_idx, enroll_week]
    site_ids = np.repeat(sites["site_id"].to_numpy()[site_idx], n_per_cell)
    enroll = np.repeat(enroll_week, n_per_cell)
    n = len(enroll)

    order = np.lexsort((site_ids, enroll))  # sort by week, then site
    site_ids, enroll = site_ids[order], enroll[order]

    arms = rng.choice(list(c.ARMS), size=n, p=list(c.ARMS.values()))
    # Exponential time on treatment; median = scale * ln(2).
    weeks_on = np.ceil(rng.exponential(c.MEDIAN_WEEKS_ON_TREATMENT / np.log(2), n)).astype(int)
    weeks_on = np.maximum(weeks_on, 1)
    discontinued = weeks_on < c.MAX_WEEKS_ON_TREATMENT
    weeks_on = np.minimum(weeks_on, c.MAX_WEEKS_ON_TREATMENT)

    return pd.DataFrame({
        "patient_id": np.arange(1, n + 1),
        "site_id": site_ids,
        "arm": arms,
        "enroll_week": enroll,
        "end_week": np.minimum(enroll + weeks_on, c.TRIAL_WEEKS),  # first week off treatment
        "discontinued": discontinued,
    })


def make_visits(rng, patients):
    """Cycle-based visits with windows. One row per planned visit (missed ones have kits = 0).

    First visit is at enrollment. Each later visit is planned VISIT_INTERVAL_WEEKS after the
    previous actual visit (or after the planned week of a missed one), then shifted early/late
    by VISIT_SHIFT_PROBS. Visits stop at the patient's end of treatment or the protocol maximum.
    """
    shifts = np.array(list(c.VISIT_SHIFT_PROBS))
    cum = np.cumsum(list(c.VISIT_SHIFT_PROBS.values()))
    rows = []
    for p in patients.itertuples():
        stop = min(p.end_week, p.enroll_week + c.MAX_WEEKS_ON_TREATMENT)
        rows.append((p.patient_id, p.arm, 1, p.enroll_week, p.enroll_week, False))
        anchor, n = p.enroll_week, 1
        while True:
            planned = anchor + c.VISIT_INTERVAL_WEEKS
            actual = planned + int(shifts[np.searchsorted(cum, rng.random())])  # pick a shift
            if actual >= stop:
                break
            n += 1
            if rng.random() < c.MISSED_VISIT_PROB:
                rows.append((p.patient_id, p.arm, n, planned, planned, True))
                anchor = planned
            else:
                rows.append((p.patient_id, p.arm, n, actual, planned, False))
                anchor = actual
    visits = pd.DataFrame(rows, columns=["patient_id", "arm", "visit_num", "week", "planned_week", "missed"])
    visits["visit_date"] = week_to_date(visits["week"])
    visits["kits"] = np.where(visits["missed"], 0, c.KITS_PER_VISIT)
    if visits["week"].max() >= c.TRIAL_WEEKS:
        raise ValueError("TRIAL_WEEKS too short for this trial; raise it in config.py")
    return visits


def make_site_week(sites, counts, patients, visits):
    n_sites, n_weeks = counts.shape
    sw = pd.DataFrame({
        "site_id": np.repeat(sites["site_id"].to_numpy(), n_weeks),
        "week": np.tile(np.arange(n_weeks), n_sites),
        "enrolled": counts.ravel(),  # ravel = flatten row by row, matching repeat/tile above
    })
    sw["week_start"] = week_to_date(sw["week"])
    sw["is_open"] = sw["week"] >= sw["site_id"].map(sites.set_index("site_id")["open_week"])

    kits = (visits.merge(patients[["patient_id", "site_id"]], on="patient_id")
            .groupby(["site_id", "week"])["kits"].sum())
    sw = sw.merge(kits.rename("kits_needed"), on=["site_id", "week"], how="left")
    sw["kits_needed"] = sw["kits_needed"].fillna(0).astype(int)
    end = int(visits["week"].max()) + 1   # stop at the trial's last visit
    sw = sw[sw["week"] < end].reset_index(drop=True)
    return sw[["site_id", "week", "week_start", "is_open", "enrolled", "kits_needed"]]


def generate_trial(rng, scenario="base", shock_rng=None):
    """scenario: a key of config.SCENARIOS. shock_rng: separate generator for the shock draws."""
    sites = make_sites(rng)
    mult, hit, start = shock_multiplier(shock_rng, len(sites), c.SCENARIOS[scenario])
    sites["shocked"] = hit
    sites["shock_start_week"] = pd.array([start if h else None for h in hit], dtype="Int64")  # Int64 allows blanks (NULL)
    counts = make_enrollment(rng, sites, mult)
    patients = make_patients(rng, sites, counts)
    visits = make_visits(rng, patients)
    site_week = make_site_week(sites, counts, patients, visits)
    return {"site": sites, "site_week": site_week, "patient": patients, "visit": visits}
