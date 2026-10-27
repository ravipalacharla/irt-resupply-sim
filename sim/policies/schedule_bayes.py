"""Schedule + Bayesian rule: known visits, plus a Bayesian Gamma-Poisson forecast of new patients.

Same as the schedule rule, except the spare kits for new patients come from each site's
own updated pace estimate (sim/bayes.py) instead of "average of the last 8 weeks":

  cover     = lead time + 1 week
  scheduled = kits planned in the next `cover` weeks for patients on treatment now
  pace      = posterior Gamma(alpha + site patients so far, beta + site exposure so far)
  spare     = 95% quantile of new patients for this arm over the next `cover` weeks
              (negative binomial), at least FORECAST_FLOOR while enrolling; 0 once closed
  target    = scheduled + spare
"""
from sim import config as c
from sim.bayes import exposure, new_patients_quantile, posterior

NAME = "schedule_bayes"


def order_qty(on_hand, in_transit, known):
    """Returns (kits to order, target stock)."""
    cover = known["lead_time"] + 1
    scheduled = int(known["scheduled"][:cover].sum())
    spare = 0
    if known["enrolling"]:
        wo = known["weeks_open"]
        post = posterior(c.BAYES_PRIOR, int(known["enroll_history"].sum()), exposure(0, wo))
        future = exposure(wo + 1, wo + cover)
        new = new_patients_quantile(post, future, c.ARMS[known["arm"]], c.BAYES_QUANTILE)
        spare = max(new * c.KITS_PER_VISIT, c.FORECAST_FLOOR)
    target = scheduled + spare
    position = on_hand + in_transit
    return (target - position if position < target else 0), target
