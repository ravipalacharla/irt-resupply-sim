"""Train the LightGBM kit-need model on its own training trials and save it.

    python -m sim.train_ml

Training trials: seeds TRAINING_SEED_START .. +TRAINING_TRIALS (base scenario). The last 8
are held out: training stops when the error on those has not improved for a while
(early stopping), so the model does not just memorise the training trials.
Prints held-out accuracy next to two simple baselines, and which inputs mattered most.
"""
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from sim import config as c
from sim.generator import generate_trial
from sim.ml import FEATURES, build_features

HOLDOUT_TRIALS = 8


def poisson_deviance(y, mu):
    """Standard error measure for count predictions; lower is better."""
    mu = np.maximum(mu, 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(y > 0, y * np.log(y / mu), 0.0)
    return float(2 * np.mean(term - (y - mu)))


def training_data():
    frames = []
    for i in range(c.TRAINING_TRIALS):
        seed = c.TRAINING_SEED_START + i
        f = build_features(generate_trial(c.make_rng(seed)))
        f["trial"] = i
        frames.append(f)
    return pd.concat(frames, ignore_index=True)


def train(data):
    is_valid = data["trial"] >= c.TRAINING_TRIALS - HOLDOUT_TRIALS
    tr, va = data[~is_valid], data[is_valid]
    dtrain = lgb.Dataset(tr[FEATURES], tr["label"], categorical_feature=["region", "arm"])
    dvalid = lgb.Dataset(va[FEATURES], va["label"], reference=dtrain)
    model = lgb.train(
        c.ML_PARAMS, dtrain, num_boost_round=c.ML_MAX_ROUNDS, valid_sets=[dvalid],
        callbacks=[lgb.early_stopping(c.ML_EARLY_STOP_ROUNDS, verbose=False)],
    )
    return model, va


def report(model, va):
    y = va["label"].to_numpy()
    preds = {
        "LightGBM": model.predict(va[FEATURES], num_iteration=model.best_iteration),
        "scheduled visits only": va["sched_h"].to_numpy(),
        "rolling 8-week average": va["need_mean8"].to_numpy(),
    }
    print(f"held-out rows: {len(va):,}   rounds used: {model.best_iteration}")
    print(f"{'method':<24}{'avg error (kits)':>18}{'Poisson deviance':>18}")
    for name, mu in preds.items():
        print(f"{name:<24}{np.mean(np.abs(y - mu)):>18.4f}{poisson_deviance(y, mu):>18.4f}")
    gain = pd.Series(model.feature_importance("gain"), index=FEATURES)
    print("\nInputs that mattered most (share of total gain):")
    print((gain / gain.sum()).sort_values(ascending=False).head(10).round(3).to_string())


def main():
    data = training_data()
    print(f"training rows: {len(data):,} from {c.TRAINING_TRIALS} trials")
    model, va = train(data)
    report(model, va)
    Path(c.ML_MODEL_PATH).parent.mkdir(exist_ok=True)
    model.save_model(c.ML_MODEL_PATH, num_iteration=model.best_iteration)
    print(f"\nsaved {c.ML_MODEL_PATH}")


if __name__ == "__main__":
    main()
