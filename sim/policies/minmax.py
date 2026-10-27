"""Min/max reorder rule: when stock (on hand + in transit) falls to MIN or below, top up to MAX.

Same MIN/MAX at every site. See minmax_tuned.py for per-region settings.
"""
from sim import config as c

NAME = "minmax"


def order_qty(on_hand, in_transit, known, low=None, high=None):
    """Returns (kits to order, target stock). `known` is unused: min/max looks only at stock."""
    # Read the settings at call time (not as default values), so knob runs can change them.
    low = c.MINMAX_MIN if low is None else low
    high = c.MINMAX_MAX if high is None else high
    position = on_hand + in_transit
    return (high - position if position <= low else 0), high
