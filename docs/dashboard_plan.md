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

## Decisions (2026-10-27)

### Words used on screen
- **Shipment**: what is sent to a site. (**Lot** keeps its clinical supply meaning: a
  manufacturing batch with one expiry date.)
- **Reorder rule**: the way the system decides when to send a shipment to a site, and how many kits.

### Rule names on screen
| Code name | Name on screen | One line under the name |
|---|---|---|
| minmax | Fixed refill | When a site has 2 kits or fewer, refill it to 5. |
| minmax_tuned | Fixed refill by region | Same idea, but each region has its own numbers. |
| forecast | Recent use | Look at the last 8 weeks of use. Keep enough until the next shipment arrives, plus a cushion. |
| schedule | Expected visits | Count the kits needed for the visits expected for current patients, plus 2 spare kits for new patients. |
| schedule_bayes | Expected visits + site pace | Same, but estimate new patients from how fast this site has enrolled so far. |
| ml | Expected visits + machine learning | A model trained on past trials predicts how many kits the site will need. |

Each rule gets an info card: Looks at / Decides / Example / Good at / Weak at, plus a small
picture of what the shelf looks like over time under that rule.

### Screens
1. **Which rule works best?** All 6 rules. (Side by side or a drop-down: UI decision later.)
2. **Where and when do sites run out?** Country x week color grid.
3. **One site** (animated step chart): single site only. No country totals, because adding
   sites together hides stockouts (one empty site + one full site looks fine).
   Data kept to the bare minimum needed for the chart.

### Defaults
- Picked rule: **Expected visits** (as few stockouts as any rule, far less waste).
- Comparison line on screen 3: **Fixed refill by region** (closest to what most teams use today).

## Decisions (2026-10-27, later)
- **Site chart data:** one example trial per run (trial 0) instead of 5, and only 6 "story"
  sites from it instead of 78 (busy, often runs short, far away, slow, opens late, steady;
  one country each). Dashboard files went from 67 MB to about 2.5 MB (about 0.3 MB
  compressed). Small enough to keep in git and host as a plain static folder (`web/`).
  Screens 1-2 still use all 200 trials.
- **Layout:** settings in a panel on the left that can be hidden; chart on the right.
  Title color #00A1DF.
- **Safety dial:** 3 positions (Less / Normal / More), the safety knob runs. A headline above
  the chart shows each rule's first stockout (or "No stockout") and what it cost
  (kits short, expired, average kits on the shelf, shipments).
- **Other knobs:** small switch buttons (shipping time, shelf life, enrollment speed,
  enrollment shock). One at a time: moving one puts the others back to Normal.
- **Player:** Play/Pause, Replay, speed 1x/2x, click the chart to jump to a week. No slider.
- Opens on the "Often runs short" site, where the dial makes the most difference.
- **Step chart:** written fresh in D3 v7 (`web/js/stepChart.js`). Ideas taken from my earlier
  personal step chart: line drawing itself week by week, totals counting up as it plays,
  shortages and expiries drawn below zero, hover line with a tooltip. Added: stockout dots and
  a "First stockout: week X" flag, the rule's target line, a compare rule in grey, a week slider.
