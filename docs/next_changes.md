# Realism pass (agreed and built 2026-10-25)

**Status: all items 1-6 built, run, and documented** (results in `docs/how_it_works.md` sections 7-8).

All of these change the trial generator or the supply simulation, so every result must be
re-run, min/max re-tuned, and the ML model retrained afterwards. They are done together in
one pass to avoid re-running everything several times.

## Order

1. **B. Visit windows** (biggest weakness today)
2. **Generator realism** (so the Bayesian rule is an honest test)
3. **A. Run to the end of the trial** (close-out)
4. **F. Top up both arms in one box**
5. **New rule: schedule + Bayesian Gamma-Poisson**
6. Re-tune min/max, retrain ML, re-run 3 scenarios, then the dashboard knob runs

---

## 1. Visit windows (B)

| Decision | Choice |
|---|---|
| Visit shift | 70% in the planned week, 15% one week early, 15% one week late (about a +/-7 day window) |
| Anchor | **Cycle-based**: each cycle is counted from the previous *actual* visit, so delays add up (typical of oncology 28-day cycles) |
| Missed visits | ~2% of visits are missed: no kit that week; the next visit is planned 4 weeks after the missed planned date |
| Unscheduled kits | Not included |
| What rules know | The planned week of each patient's next visit, **not** whether it will shift. Rules must cover the window. |
| Treatment length | Still capped at 104 weeks from enrollment |

Effect expected: the schedule and ML rules lose their perfect knowledge of visit timing, so
their results become more realistic (likely somewhat worse).

## 2. Generator realism

The generator stays Gamma-Poisson at heart, plus three changes it was not built with, so a
Bayesian Gamma-Poisson forecaster is tested on data it does not perfectly match.

| Change | Real-life meaning |
|---|---|
| **Pace drift** | Each site's pace slowly wanders over time (fatigue, staff turnover, competing trials) |
| **Country effect** | Sites in the same country enroll alike (standard of care, referral networks) |
| **Bursty weeks** | Patients sometimes arrive in clusters (tumor boards, referral batches) |

Values to be chosen so overall enrollment speed and the S-curve stay roughly as today
(about 92 weeks to 500 patients), and documented in `docs/assumptions.md`.

## 3. Run to the end of the trial (A)

Simulate until the last patient's last possible visit (about week 200+) instead of stopping at
week 156, so site close-out and the kits left over at the very end are counted properly.

## 4. Top up both arms in one box (F)

When one arm at a site triggers an order, also top up the other arm in the same box if it is
below its target. Matches how real resupply works and gives fairer box counts.

## 5. New rule: schedule + Bayesian

Same as the schedule rule, but the new-patient forecast comes from a Bayesian Gamma-Poisson
model instead of "average of the last 8 weeks":

- **Prior:** what a typical site's pace looks like, learned from the training trials.
- **Update:** each week, combine the prior with what this site has actually enrolled
  (allowing for ramp-up), giving the site's own pace estimate.
- **Forecast:** a full probability distribution of new patients in the coming weeks
  (negative binomial). Spare kits = enough to cover 95% of outcomes, at least 2 while enrolling.

Expected strength: new sites (little history) and stumbling sites (recognised quickly).

## Open items for later
- Quantile ML (LightGBM predicting the 95th percentile directly) as a second chance for ML.
- Extra safety positions (5 instead of 3) and a trade-off chart in the dashboard.
- Cost-ratio slider (needs a scope decision; cost modeling is out of scope in v1).
