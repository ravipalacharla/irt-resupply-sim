"""ML reorder rule: LightGBM predicts kit need; same order logic as the schedule rule.

  cover     = lead time + 1 week
  expected  = model's predicted kits needed over the next `cover` weeks
  scheduled = kits due for patients on treatment now (as in the schedule rule)
  booked    = min(expected, scheduled)  -> lets the model discount likely dropouts
  new       = expected - booked         -> the model's expected new-patient kits
  spare     = new + Z x sqrt(new), at least FORECAST_FLOOR while enrolling; 0 once closed
  target    = booked + spare, rounded up

So the only difference from the schedule rule is where `expected` comes from.
Predictions are made in one batch per trial by prepare() before the weekly loop; each week's
prediction uses only facts known that week (see sim/ml.py and tests/test_ml.py).
"""
import math

import lightgbm as lgb

from sim import config as c
from sim.ml import predict_need

NAME = "ml"
_model = None


def load_model(path=None):
    global _model
    if path is not None or _model is None:
        _model = lgb.Booster(model_file=path or c.ML_MODEL_PATH)
    return _model


def prepare(trial):
    """{(site_id, arm): array [week, h]} of predicted need, handed to order_qty via known["prepared"]."""
    return predict_need(trial, load_model())


def order_qty(on_hand, in_transit, known):
    """Returns (kits to order, target stock)."""
    cover = known["lead_time"] + 1
    expected = float(known["prepared"][:cover].sum())
    scheduled = int(known["scheduled"][:cover].sum())
    booked = min(expected, scheduled)
    new = expected - booked
    # Like the schedule rule: no new patients once enrollment is closed, so no spare kits.
    spare = 0.0
    if known["enrolling"]:
        spare = max(new + c.FORECAST_Z * math.sqrt(new), c.FORECAST_FLOOR)
    target = math.ceil(booked + spare)
    position = on_hand + in_transit
    return (target - position if position < target else 0), target
