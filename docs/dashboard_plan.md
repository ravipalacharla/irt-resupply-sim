# Dashboard plan (Phase 4)

Agreed 2026-10-25. Built after the ML rule is done.

## How the knobs work
- Every knob position points to a Monte Carlo run computed ahead of time (200 trials,
  every reorder rule included). Moving a knob switches which stored run is shown; nothing
  re-runs in the browser.
- **One knob at a time:** moving one knob resets the others to "normal". The page says so.
- Nothing is re-tuned when a knob moves (tuned min/max keeps its settings, the ML model is not
  retrained). The knobs show how each rule copes when reality differs from what it was set up for.
- Static files only, so it can be hosted on GitHub Pages or Azure Static Web Apps.

## The 6 knobs

| # | Knob | Positions | Real-life meaning | Extra runs |
|---|---|---|---|---|
| 1 | Reorder rule | min/max, tuned min/max, rolling forecast, schedule-based, ML | Which resupply method is used | 0 (every run has all rules) |
| 2 | Scenario | base / surge / stall | Enrollment shocks | 2 (done) |
| 3 | Safety level | low / normal / high | Forecast-type rules: cushion covers ~84 / 95 / 99% of weeks. Min/max: tuned levels -2 / tuned / +2 | 2 |
| 4 | Shipping time | normal / +1 week everywhere | Slower couriers or a more distant depot | 1 |
| 5 | Shelf life | 12 / 24 / 36 months | Short-dated vs stable product | 2 |
| 6 | Enrollment speed | slower / normal / faster (pace x0.7 / x1.0 / x1.3) | Trial enrolls slower or faster than planned | 2 |

Total: 1 base + 9 = 10 runs (~2-2.5 hours one-off compute once ML is in).

## What every knob position shows
1. **Scorecard per rule:** kits short, kits expired, shipments, stock at sites, with 95% ranges.
2. **Stockout risk heatmap:** country x week, % of trials with a stockout.
3. **Trial drill-down:** pick a trial, see each site's need, stock, and the rule's forecast
   target over time, with stockout dates marked.

## Notes
- Country-level risk is meaningful across trials (countries are the same in every trial).
  Site-level dates only make sense inside one chosen trial (sites differ per trial).
- Knob runs store summaries plus full detail for a few trials only, to keep the database small.
- Needs a per-week "target stock" saved for forecast-type rules (for the drill-down).
