"""Forecast reorder rule: rolling average of recent use, plus a safety cushion.

Target stock = average weekly use x (lead time + 1 week)
             + Z x spread of weekly use x sqrt(lead time + 1)
The +1 week covers the gap until the next weekly reorder check.
"""
import math

import numpy as np

from sim import config as c

NAME = "forecast"


def order_qty(on_hand, in_transit, known):
    """Returns (kits to order, target stock). Uses only known["history"] (kits needed so far)."""
    recent = known["history"][-c.FORECAST_WINDOW_WEEKS:]
    cover = known["lead_time"] + 1
    mean = float(np.mean(recent)) if len(recent) else 0.0
    spread = float(np.std(recent)) if len(recent) else 0.0
    target = mean * cover + c.FORECAST_Z * spread * math.sqrt(cover)
    if known["enrolling"]:
        target = max(target, c.FORECAST_FLOOR)
    target = math.ceil(target)
    position = on_hand + in_transit
    return (target - position if position < target else 0), target
