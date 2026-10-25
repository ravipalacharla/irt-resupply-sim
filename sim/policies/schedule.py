"""Schedule-based reorder rule: known visits of current patients + spare kits for new patients.

A real system knows when each enrolled patient's next visit is due. That covers most demand.
The only real uncertainty is new patients, estimated from the site's recent enrollment.

  cover     = lead time + 1 week (same as the rolling forecast)
  scheduled = kits due in the next `cover` weeks for patients on treatment now
              (assumes they all keep going; it cannot know who will stop)
  new       = site's average new patients/week over the last 8 weeks
              x this arm's share x cover weeks   (1 kit each at enrollment)
  spare     = new + Z x sqrt(new)   (sqrt(new): random spread of patient arrivals),
              but at least FORECAST_FLOOR while enrolling, so a new patient can always get a kit
  target    = scheduled + spare  (spare is 0 once enrollment is closed)

The floor applies to the spare kits, not the total: a site whose existing patients already
need 3 kits still keeps 2 extra for a new arrival.
"""
import math

import numpy as np

from sim import config as c

NAME = "schedule"


def order_qty(on_hand, in_transit, known):
    """Returns (kits to order, target stock)."""
    cover = known["lead_time"] + 1
    scheduled = int(known["scheduled"][:cover].sum())
    spare = 0.0
    if known["enrolling"]:
        recent = known["enroll_history"][-c.SCHEDULE_ENROLL_WINDOW_WEEKS:]
        rate = float(np.mean(recent)) if len(recent) else 0.0
        new = rate * c.ARMS[known["arm"]] * cover * c.KITS_PER_VISIT
        spare = max(new + c.FORECAST_Z * math.sqrt(new), c.FORECAST_FLOOR)
    target = math.ceil(scheduled + spare)
    position = on_hand + in_transit
    return (target - position if position < target else 0), target
