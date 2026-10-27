"""All simulation parameters and the single source of randomness.

Every number here is invented. See docs/assumptions.md for the reasoning.
"""
import os
from datetime import date

import numpy as np

# Master seed. Every random draw in the project must come from make_rng().
SEED = 20261024

# Local Postgres via Unix socket, current macOS user, database irt_sim.
# Override with:  export IRT_SIM_DB_URL="postgresql+psycopg2://user:pw@host/irt_sim"
DB_URL = os.environ.get("IRT_SIM_DB_URL", "postgresql+psycopg2:///irt_sim")

# --- Trial ---
STUDY_START = date(2027, 1, 4)   # week 0 (a Monday)
TRIAL_WEEKS = 260                # max horizon (5 years). Each trial is simulated until its
                                 # last patient's last visit; the generator checks it fits.
ENROLL_TARGET = 500              # enrollment stops once this many patients are in
ARMS = {"A": 0.5, "B": 0.5}      # arm -> share of patients (1:1)

# region -> country -> number of sites (78 sites total)
REGIONS = {
    "North America": {"US": 20, "CA": 5},
    "Europe": {"DE": 8, "FR": 7, "ES": 6, "PL": 6, "GB": 6},
    "Asia-Pacific": {"JP": 8, "AU": 6, "KR": 6},
}

# --- Site opening ---
COUNTRY_APPROVAL_WEEKS = (4, 30)  # each country approved at a random week in this range
SITE_OPEN_LAG_MEAN_WEEKS = 6      # average wait from country approval to site opening

# --- Site enrollment pace ---
SITE_PACE_MEAN = 0.12     # patients/week at a typical site once on auto pilot (~0.5/month)
SITE_PACE_SHAPE = 1.5     # lower = more spread between slow and fast sites
RAMP_UP_WEEKS = 12        # weeks from opening to full pace (straight-line ramp)
STUMBLE_SHARE = 0.18      # share of sites that never really get going
STUMBLE_FACTOR = 0.1      # their pace is cut to this fraction

# --- Enrollment realism (things a Gamma-Poisson forecaster does not assume) ---
COUNTRY_EFFECT_SD = 0.3   # sites in a country share a pace multiplier (log-normal, average 1)
PACE_DRIFT_SD = 0.03      # each site's pace wanders week to week (log random walk, no upward bias)
BURST_PROB = 0.05         # share of site-weeks with a burst of referrals...
BURST_FACTOR = 4.0        # ...enrolling at this multiple of the usual pace; other weeks are
                          # scaled down slightly so the long-run average pace is unchanged

# --- Patients and visits ---
VISIT_INTERVAL_WEEKS = 4          # one treatment cycle; a kit is dispensed at each cycle start
KITS_PER_VISIT = 1
# Cycle-based visit windows: each cycle is counted from the previous ACTUAL visit, so delays
# add up. Shift of each visit vs its planned week: one week early / on time / one week late.
VISIT_SHIFT_PROBS = {-1: 0.15, 0: 0.70, 1: 0.15}
MISSED_VISIT_PROB = 0.02          # visit skipped: no kit; next cycle counted from the planned week
MEDIAN_WEEKS_ON_TREATMENT = 40    # half of patients stop (any reason) before this
MAX_WEEKS_ON_TREATMENT = 104      # protocol maximum

# --- Supply network ---
LEAD_TIME_WEEKS = {"North America": 1, "Europe": 2, "Asia-Pacific": 3}  # depot -> site
SHELF_LIFE_MONTHS = 24            # manufacture -> expiry
LOT_INTERVAL_MONTHS = 6           # a new lot of each arm's kit is released every 6 months
LOT_AGE_AT_RELEASE_MONTHS = 3     # lot is already this old when the depot can ship it
DISPENSE_BUFFER_WEEKS = VISIT_INTERVAL_WEEKS  # kit must not expire before the next visit

# --- Min/max reorder rule (per site, per arm) ---
MINMAX_MIN = 2    # reorder when on hand + in transit falls to this or below
MINMAX_MAX = 5    # ...and top back up to this

# --- Tuned min/max: one (MIN, MAX) per region ---
# Picked by `python -m sim.tune_minmax` on the tuning trials below, which never overlap
# the scoring trials (seeds 0..N-1 in sim.run). Re-run the tuner if other settings change.
TUNING_SEED_START = 10_000
TUNING_TRIALS = 30
MINMAX_TUNED = {"North America": (4, 5), "Europe": (8, 10), "Asia-Pacific": (9, 12)}

# --- Forecast reorder rule (per site, per arm) ---
FORECAST_WINDOW_WEEKS = 8   # average use over the last 8 weeks
FORECAST_Z = 1.65           # cushion = 1.65 x spread of weekly use (~95% coverage)
FORECAST_FLOOR = 2          # keep at least this many while enrollment is open (same as MINMAX_MIN)

# --- Schedule-based reorder rule (per site, per arm) ---
# Uses known visit dates of patients already on treatment + expected new patients.
# Cushion uses FORECAST_Z and floor uses FORECAST_FLOOR, so it differs from the rolling
# forecast only in what it knows, not in how cautious it is.
SCHEDULE_LOOKAHEAD_WEEKS = 8      # how far ahead the simulator lists scheduled visits
SCHEDULE_ENROLL_WINDOW_WEEKS = 8  # recent weeks used to estimate the site's new-patient rate

# --- ML (LightGBM) reorder rule ---
# Trained by `python -m sim.train_ml` on its own trials (base scenario only), never on the
# tuning (10000+) or scoring (0..N-1) trials. Not retrained for scenarios or knobs.
TRAINING_SEED_START = 20_000
TRAINING_TRIALS = 40              # last 8 of these are held out to decide when to stop training
ML_MODEL_PATH = "models/lgbm_need.txt"
ML_PARAMS = {
    "objective": "poisson",       # predicts counts (kits per week); never negative
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.9,
    "seed": SEED,
    "deterministic": True,        # same data + seed -> same model
    "force_row_wise": True,
    "verbose": -1,
}
ML_MAX_ROUNDS = 2000
ML_EARLY_STOP_ROUNDS = 50         # stop when held-out error has not improved for this many rounds

# --- Bayesian Gamma-Poisson reorder rule (schedule + Bayesian new-patient forecast) ---
# Prior on a site's steady pace (patients/week) ~ Gamma(alpha, beta), mean alpha/beta.
# Fitted by `python -m sim.fit_prior` on the ML training trials; paste its output here.
BAYES_PRIOR = (0.8394, 8.5784)    # fitted: mean 0.098 patients/week, shape 0.84
BAYES_QUANTILE = 0.95             # spare kits cover 95% of likely new-patient counts


# --- Stress-test scenarios: enrollment shocks the rules were not set up for ---
# share = fraction of sites hit; factor = pace multiplier while hit; weeks = how long.
# All hit sites are hit in the same week, drawn from SHOCK_START_WEEKS (mid-enrollment).
SCENARIOS = {
    "base": None,
    "surge": {"share": 0.3, "factor": 3.0, "weeks": 12},
    "stall": {"share": 0.3, "factor": 0.0, "weeks": 16},
}
SHOCK_START_WEEKS = (26, 70)


def make_rng(run_seed=0, stream=0):
    """Random generator for one simulated trial.

    Same run_seed -> same numbers every time. Different run_seed values give
    independent streams (numpy mixes SEED and run_seed into one seed).
    stream > 0 gives a separate generator for the same trial (used for shocks), so
    adding a shock does not change the base trial's own draws.
    """
    return np.random.default_rng([SEED, run_seed] if stream == 0 else [SEED, run_seed, stream])


def params():
    """All UPPERCASE settings above, for storing with each run."""
    return {k: v for k, v in globals().items() if k.isupper() and k != "DB_URL"}
