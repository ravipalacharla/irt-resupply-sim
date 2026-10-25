import pytest
from sqlalchemy import create_engine, text

from sim.config import DB_URL, make_rng


def test_rng_is_reproducible():
    assert (make_rng(7).random(5) == make_rng(7).random(5)).all()


def test_rng_differs_by_seed():
    assert (make_rng(1).random(5) != make_rng(2).random(5)).any()


def test_database_reachable():
    try:
        with create_engine(DB_URL).connect() as conn:
            assert conn.execute(text("select current_database()")).scalar() == "irt_sim"
    except Exception as e:  # fresh clone without Postgres: skip, don't fail
        pytest.skip(f"Postgres not reachable: {e}")
