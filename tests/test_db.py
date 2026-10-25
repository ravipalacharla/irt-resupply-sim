import pytest
from sqlalchemy import text

from sim.db import create_schema, get_engine, load_trial
from sim.run import run_trial

TEST_TRIAL_ID = -1  # negative so it never collides with real trials


@pytest.fixture(scope="module")
def engine():
    eng = get_engine()
    try:
        eng.connect().close()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e}")
    create_schema(eng)
    yield eng
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM trial WHERE trial_id = :t"), {"t": TEST_TRIAL_ID})


def test_load_and_query(engine):
    tables = run_trial(0)
    load_trial(engine, TEST_TRIAL_ID, tables)
    load_trial(engine, TEST_TRIAL_ID, tables)  # reload must replace, not duplicate
    with engine.connect() as conn:
        for name, df in tables.items():
            n = conn.execute(text(f"SELECT count(*) FROM {name} WHERE trial_id = :t"),
                             {"t": TEST_TRIAL_ID}).scalar()
            assert n == len(df), name
        kits = conn.execute(text(
            "SELECT sum(kits_needed) FROM site_week WHERE trial_id = :t"), {"t": TEST_TRIAL_ID}).scalar()
        assert kits == tables["visit"]["kits"].sum()
