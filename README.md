# IRT Resupply Simulator

**Synthetic data. Illustrative only.**

Compares two reorder rules for shipping clinical trial kits to sites, on fully made-up trials:

- **min/max**: when a site drops below X kits, top it up to Y.
- **forecast**: estimate the site's upcoming use and ship enough to cover it plus a cushion.

Both rules run against the exact same simulated trials, across many random trials, and are scored on stockouts, expired kits, shipment count, and stock on hand.

## Setup (macOS)

```zsh
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
createdb irt_sim

python3 -m venv .venv
source .venv/bin/activate
brew install libomp                # needed by LightGBM on macOS
pip install -r requirements.txt
pytest -q
python -m sim.train_ml             # train the ML model once (~30 s)
caffeinate -s python -m sim.run --seeds 200 --plan dashboard --reset   # plug in, lid open (~5 h)
python -m sim.export               # dashboard files -> web/data/
cd web && python3 -m http.server 8000   # then open http://localhost:8000
```

## Accessing the database

Homebrew Postgres creates one superuser named after your macOS login (`whoami`), with no
password for local connections. There is **no `postgres` user** by default.

| Setting | Value |
|---|---|
| Host | `localhost` |
| Port | `5432` |
| Database | `irt_sim` |
| Username | your macOS login (`whoami`) |
| Password | empty (local "trust" login) |

- **Terminal:** `psql irt_sim` (`\dt` list tables, `\d name` describe, `\q` quit)
- **pgAdmin:** Register → Server, Connection tab with the values above. Query Tool: Tools → Query Tool, F5 to run.
- **VS Code:** SQLTools + SQLTools PostgreSQL driver, same values.
- Want a `postgres` login like Windows installs? `createuser -s postgres` (no password).

Postgres runs as a background service: `brew services list` to check, `brew services restart postgresql@16` to restart.

## Docs

- `docs/how_it_works.md`: what the simulator does and how, in plain English, plus results so far
- `docs/workflow.md`: how to run, re-tune, query, and change things
- `docs/scope.md`: scope and phases
- `docs/assumptions.md`: every modeling assumption
- `docs/backlog.md`: ideas deferred past v1
