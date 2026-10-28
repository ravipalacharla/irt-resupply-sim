# Backlog (v2+)

Out of v1 scope. Move here instead of building.

- Customs, import permits, country-specific labeling
- Stockouts that delay visits or cause dropouts (v1: stockout recorded, visit proceeds)
- Blinding / multiple kit types per arm, titration, dose changes
- Returns and reconciliation
- Temperature excursions
- Cost modeling
- Live scenario runs (FastAPI backend)
- Depot stock limits, depot-level expiry, and production planning
- Shipping delays / variable lead times
- Topping up the other arm when one arm triggers a shipment
- Returns/destruction of leftover kits at site close
- Live configuration knobs (any value, not just a precomputed grid):
  - in the browser via Pyodide (static hosting, no server; a few trials per click), or
  - local app (Streamlit / FastAPI) on the Mac (needs a running server, out of v1 scope)
- Cloud hosting on Azure (or similar): static dashboard on Azure Static Web Apps fits v1; live
  knobs that re-run the simulation need cloud compute (Azure Functions / Container Apps) = v2
- Forward planning mode: take one trial's history up to "today" and Monte Carlo its future to
  predict stockout dates per real site (a planning tool, not a rule comparison)
- Dashboard deep-dive screens (built or planned, then left out on 2026-10-28 to keep the demo
  simple; the data is already exported in `web/data/<run>/summary.json` and `heatmap.json`):
  - "All 200 trials" tab: one bar per rule for kits short / expired / at sites / shipments,
    with 95% ranges (only the kits-short sentence was kept, under the site headline)
  - Country x week grid: % of trials where a site in the country ran short
