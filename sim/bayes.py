"""Bayesian Gamma-Poisson enrollment forecast for one site (the published standard method).

Belief about a site's steady pace (patients per week) starts as the prior Gamma(alpha, beta)
and is updated with what the site has actually enrolled:
    posterior = Gamma(alpha + patients so far, beta + exposure so far)
Exposure = weeks open, with ramp-up weeks counted partly (week k after opening counts
min(1, (k + 1) / RAMP_UP_WEEKS)), the same ramp-up profile a planner would assume.

New patients over the next weeks then follow a negative binomial distribution, which gives
both an expected value and a proper upper quantile (the cushion).
"""
import numpy as np

from sim import config as c


def ramp(weeks_open):
    """How much of a full week of enrolling this week counts as, by weeks since opening."""
    return np.clip((np.asarray(weeks_open) + 1) / c.RAMP_UP_WEEKS, 0, 1)


def exposure(weeks_open_from, weeks_open_to):
    """Ramp-adjusted weeks between two 'weeks since opening' values (inclusive)."""
    if weeks_open_to < max(weeks_open_from, 0):
        return 0.0
    return float(ramp(np.arange(max(weeks_open_from, 0), weeks_open_to + 1)).sum())


def posterior(prior, patients, exposure_so_far):
    alpha, beta = prior
    return alpha + patients, beta + exposure_so_far


def nb_quantile(r, p, q):
    """Smallest k with P(N <= k) >= q, for N ~ negative binomial(r, p) (number of arrivals).

    P(N = 0) = p^r; P(N = k + 1) = P(N = k) * (k + r) / (k + 1) * (1 - p).
    """
    k, pmf = 0, p ** r
    cum = pmf
    while cum < q and k < 1000:
        pmf *= (k + r) / (k + 1) * (1 - p)
        k += 1
        cum += pmf
    return k


def new_patients_quantile(post, future_exposure, share, q):
    """Upper quantile of new patients for one arm over `future_exposure` ramp-adjusted weeks.

    Arm share thins the arrivals: still negative binomial, with p = beta / (beta + share x E).
    """
    alpha, beta = post
    if future_exposure <= 0:
        return 0
    return nb_quantile(alpha, beta / (beta + share * future_exposure), q)


def fit_prior(rates_n, rates_e):
    """Method-of-moments Gamma fit to site paces, removing the Poisson noise of short exposure.

    rates_n: patients per site; rates_e: ramp-adjusted exposure weeks per site.
    """
    n, e = np.asarray(rates_n, float), np.asarray(rates_e, float)
    keep = e > 0
    n, e = n[keep], e[keep]
    mean = n.sum() / e.sum()
    raw_var = np.var(n / e)
    noise = np.mean(mean / e)                 # Poisson part of the spread
    true_var = max(raw_var - noise, mean ** 2 / 50)  # floor keeps the prior from collapsing
    return mean ** 2 / true_var, mean / true_var    # alpha, beta
