"""Create tables and load generated trials into Postgres."""
import io
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from sim import config as c

SCHEMA_FILE = Path(__file__).parent.parent / "sql" / "schema.sql"
# Parent -> child order, so foreign keys are satisfied while loading.
TABLES = ["trial", "site", "site_week", "patient", "visit",
          "lot", "shipment", "inventory_week", "policy_result"]


def get_engine():
    return create_engine(c.DB_URL)


def create_schema(engine, reset=False):
    with engine.begin() as conn:  # begin() = one transaction, commits on success
        if reset:
            conn.execute(text("DROP TABLE IF EXISTS " + ", ".join(reversed(TABLES))
                              + ", sim_run CASCADE"))  # sim_run: old phase 1 name
        conn.exec_driver_sql(SCHEMA_FILE.read_text())


def load_trial(engine, trial_id, tables, seed=None, scenario="base"):
    """Replace any existing data for trial_id with the given tables (any subset of TABLES)."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM trial WHERE trial_id = :t"), {"t": trial_id})
        conn.execute(
            text("INSERT INTO trial (trial_id, scenario, seed, master_seed, params) "
                 "VALUES (:t, :sc, :sd, :ms, :p)"),
            {"t": trial_id, "sc": scenario, "sd": trial_id if seed is None else seed,
             "ms": c.SEED, "p": json.dumps(c.params(), default=str)},
        )
        # Bulk load with Postgres COPY (much faster than INSERTs). Uses the raw psycopg2
        # connection underneath SQLAlchemy, so it stays inside the same transaction.
        cur = conn.connection.driver_connection.cursor()
        for name in TABLES[1:]:
            if name not in tables:
                continue
            df = tables[name].copy()
            df.insert(0, "trial_id", trial_id)
            buf = io.StringIO()
            df.to_csv(buf, index=False, header=False)
            buf.seek(0)
            cur.copy_expert(f"COPY {name} ({', '.join(df.columns)}) FROM STDIN WITH (FORMAT csv)", buf)
