"""Fit the Bayesian rule's prior on site pace from the ML training trials.

    python -m sim.fit_prior

Paste the printed BAYES_PRIOR line into sim/config.py. Uses only training trials
(seeds TRAINING_SEED_START..), never tuning or scoring trials.
"""
from sim import config as c
from sim.bayes import exposure, fit_prior
from sim.generator import generate_trial


def site_counts(trial):
    """Patients and ramp-adjusted exposure per site, while enrollment was open."""
    closed = trial["patient"]["enroll_week"].max() + 1
    n = trial["patient"].groupby("site_id").size()
    out_n, out_e = [], []
    for s in trial["site"].itertuples():
        out_n.append(int(n.get(s.site_id, 0)))
        out_e.append(exposure(0, closed - 1 - s.open_week))
    return out_n, out_e


def main():
    all_n, all_e = [], []
    for i in range(c.TRAINING_TRIALS):
        n, e = site_counts(generate_trial(c.make_rng(c.TRAINING_SEED_START + i)))
        all_n += n
        all_e += e
    alpha, beta = fit_prior(all_n, all_e)
    print(f"{len(all_n)} sites from {c.TRAINING_TRIALS} training trials")
    print(f"prior mean pace {alpha / beta:.3f} patients/week, shape {alpha:.2f}")
    print(f"\nBAYES_PRIOR = ({alpha:.4f}, {beta:.4f})")


if __name__ == "__main__":
    main()
