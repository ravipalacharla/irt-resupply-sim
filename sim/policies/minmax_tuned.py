"""Min/max with its own MIN/MAX per region, picked by sim/tune_minmax.py on separate trials."""
from sim import config as c
from sim.policies import minmax

NAME = "minmax_tuned"


def order_qty(on_hand, in_transit, known):
    low, high = c.MINMAX_TUNED[known["region"]]
    return minmax.order_qty(on_hand, in_transit, known, low, high)
