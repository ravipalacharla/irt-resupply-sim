"""Min/max reorder rule: when stock (on hand + in transit) falls to MIN or below, top up to MAX.

Same MIN/MAX at every site. See minmax_tuned.py for per-region settings.
"""
from sim import config as c

NAME = "minmax"


def order_qty(on_hand, in_transit, known, low=c.MINMAX_MIN, high=c.MINMAX_MAX):
    """Returns (kits to order, target stock). `known` is unused: min/max looks only at stock."""
    position = on_hand + in_transit
    return (high - position if position <= low else 0), high
