"""Shared test setup: make sure the ML rule has a model to load, even on a fresh clone."""
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import pytest

from sim import config as c
from sim.generator import generate_trial
from sim.ml import FEATURES, build_features
from sim.policies import ml


@pytest.fixture(autouse=True, scope="session")
def ml_model_available(tmp_path_factory):
    if Path(c.ML_MODEL_PATH).exists():
        yield
        return
    # No trained model yet: use a tiny one so tests that run every rule still work.
    data = build_features(generate_trial(c.make_rng(c.TRAINING_SEED_START)))
    model = lgb.train(c.ML_PARAMS, lgb.Dataset(data[FEATURES], data["label"]), num_boost_round=10)
    path = tmp_path_factory.mktemp("model") / "tiny.txt"
    model.save_model(str(path))
    original = c.ML_MODEL_PATH
    c.ML_MODEL_PATH = str(path)
    ml._model = None
    yield
    c.ML_MODEL_PATH = original
    ml._model = None
