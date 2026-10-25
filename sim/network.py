"""Supply side: kit lots, shipping, and the weekly site inventory loop.

simulate_supply(trial, policy) replays one generated trial under one reorder rule.
The trial (patients, visits) is never changed, so every rule faces the same demand.

Order of events at each site, for each arm, every week:
  1. receive shipments due this week
  2. remove kits that would expire before the next visit (counted as expired)
  3. hand out kits to this week's visits, earliest expiry first; any gap is a shortfall
  4. ask the reorder rule how many to ship; the box arrives after the region's lead time
"""
import numpy as np
import pandas as pd

from sim import config as c


def to_week(dates):
    # Week index from study start; dates before the start give negative weeks.
    return (pd.Series(dates) - pd.Timestamp(c.STUDY_START)).dt.days // 7


def make_lots():
    """One lot per arm every LOT_INTERVAL_MONTHS, from study start to end of the horizon."""
    start = pd.Timestamp(c.STUDY_START)
    releases = []
    while not releases or to_week([releases[-1]]).iloc[0] < c.TRIAL_WEEKS:
        releases.append(start + pd.DateOffset(months=len(releases) * c.LOT_INTERVAL_MONTHS))
    releases = releases[:-1]

    rows = []
    for release in releases:
        mfg = release - pd.DateOffset(months=c.LOT_AGE_AT_RELEASE_MONTHS)
        for arm in c.ARMS:
            rows.append({"lot_id": len(rows) + 1, "arm": arm, "mfg_date": mfg,
                         "expiry_date": mfg + pd.DateOffset(months=c.SHELF_LIFE_MONTHS),
                         "release_date": release})
    lots = pd.DataFrame(rows)
    lots["release_week"] = to_week(lots["release_date"])
    lots["expiry_week"] = to_week(lots["expiry_date"])
    return lots


def demand_by_site_arm(trial):
    """{(site_id, arm): array of kits needed per week}."""
    v = trial["visit"].merge(trial["patient"][["patient_id", "site_id"]], on="patient_id")
    out = {}
    for (site_id, arm), g in v.groupby(["site_id", "arm"]):
        weekly = np.zeros(c.TRIAL_WEEKS, dtype=int)
        np.add.at(weekly, g["week"].to_numpy(), g["kits"].to_numpy())  # add.at handles repeated weeks
        out[(site_id, arm)] = weekly
    return out


def patients_on_treatment(trial):
    """{site_id: array, patients on treatment per week}."""
    out = {}
    for site_id, g in trial["patient"].groupby("site_id"):
        delta = np.zeros(c.TRIAL_WEEKS + 1, dtype=int)
        np.add.at(delta, g["enroll_week"].to_numpy(), 1)
        np.add.at(delta, g["end_week"].to_numpy(), -1)
        out[site_id] = delta.cumsum()[: c.TRIAL_WEEKS]
    return out


def scheduled_kits(trial):
    """{(site_id, arm): array [week, i] = kits due at week + 1 + i for patients on treatment at week}.

    Uses only what is known at that week: who has enrolled, who has not yet stopped, and the
    visit schedule (every VISIT_INTERVAL_WEEKS from enrollment, up to the protocol maximum).
    It assumes every patient on treatment keeps going; it does not know who will stop later.
    """
    weeks = np.arange(c.TRIAL_WEEKS)[None, :, None]          # shape (1, W, 1)
    ahead = weeks + 1 + np.arange(c.SCHEDULE_LOOKAHEAD_WEEKS)[None, None, :]  # visit week, (1, W, L)
    out = {}
    for (site_id, arm), g in trial["patient"].groupby(["site_id", "arm"]):
        e = g["enroll_week"].to_numpy()[:, None, None]       # (P, 1, 1)
        n = g["end_week"].to_numpy()[:, None, None]
        on_now = (e <= weeks) & (weeks < n)                   # on treatment at this week
        since = ahead - e                                     # weeks since enrollment at visit week
        due = (since % c.VISIT_INTERVAL_WEEKS == 0) & (since < c.MAX_WEEKS_ON_TREATMENT) & (ahead < c.TRIAL_WEEKS)
        out[(site_id, arm)] = (on_now & due).sum(axis=0) * c.KITS_PER_VISIT  # sum over patients -> (W, L)
    return out


def simulate_supply(trial, policy):
    """Run one reorder rule over one trial. Returns inventory_week, shipment, lot DataFrames."""
    lots = make_lots()
    expiry_week = lots.set_index("lot_id")["expiry_week"].to_dict()
    demand = demand_by_site_arm(trial)
    on_treatment = patients_on_treatment(trial)
    schedule = scheduled_kits(trial)
    enrolled = trial["site_week"].pivot(index="site_id", columns="week", values="enrolled")
    no_demand = np.zeros(c.TRIAL_WEEKS, dtype=int)
    no_patients = np.zeros(c.TRIAL_WEEKS, dtype=int)
    no_schedule = np.zeros((c.TRIAL_WEEKS, c.SCHEDULE_LOOKAHEAD_WEEKS), dtype=int)

    # Enrollment counts as closed (known to the rule) the week after the target is hit.
    p = trial["patient"]
    closed_from = p["enroll_week"].max() + 1 if len(p) >= c.ENROLL_TARGET else c.TRIAL_WEEKS

    inv_rows, ship_rows = [], []
    for s in trial["site"].itertuples():
        lead = c.LEAD_TIME_WEEKS[s.region]
        supply_from = max(0, s.open_week - lead)  # first box lands on opening day
        active = on_treatment.get(s.site_id, no_patients)
        site_enrolled = enrolled.loc[s.site_id].to_numpy()
        for arm in c.ARMS:
            arm_lots = lots[lots["arm"] == arm]
            need_by_week = demand.get((s.site_id, arm), no_demand)
            sched = schedule.get((s.site_id, arm), no_schedule)
            on_hand = {}   # lot_id -> kits
            transit = []   # (arrive_week, lot_id, kits)
            for w in range(c.TRIAL_WEEKS):
                # 1. receive
                received = 0
                for arrive, lot, kits in [t for t in transit if t[0] == w]:
                    on_hand[lot] = on_hand.get(lot, 0) + kits
                    received += kits
                transit = [t for t in transit if t[0] != w]

                # 2. expire
                expired = 0
                for lot in [l for l in on_hand if expiry_week[l] <= w + c.DISPENSE_BUFFER_WEEKS]:
                    expired += on_hand.pop(lot)

                # 3. dispense, earliest expiry first (lot_id order = release order within an arm)
                need = int(need_by_week[w])
                dispensed = 0
                for lot in sorted(on_hand):
                    take = min(on_hand[lot], need - dispensed)
                    on_hand[lot] -= take
                    dispensed += take
                    if on_hand[lot] == 0:
                        del on_hand[lot]
                    if dispensed == need:
                        break

                # 4. reorder
                ordered, target = 0, None
                site_done = w >= closed_from and active[w] == 0
                if w >= supply_from and not site_done:
                    # Everything the rule may use. History arrays stop at this week ([: w + 1]).
                    known = {
                        "week": w, "arm": arm, "region": s.region, "lead_time": lead,
                        "enrolling": w < closed_from,
                        "weeks_open": w - s.open_week,           # negative before opening
                        "history": need_by_week[: w + 1],        # kits needed per week so far
                        "enroll_history": site_enrolled[: w + 1],  # site patients enrolled per week so far
                        "scheduled": sched[w],                   # kits due in each of the next weeks
                        "on_treatment": int(active[w]),          # site patients on treatment now
                    }
                    ordered, target = policy.order_qty(sum(on_hand.values()), sum(t[2] for t in transit), known)
                    if ordered > 0:
                        lot = int(arm_lots.loc[arm_lots["release_week"] <= w, "lot_id"].max())
                        transit.append((w + lead, lot, ordered))
                        ship_rows.append((s.site_id, arm, lot, w, w + lead, ordered))

                inv_rows.append((s.site_id, arm, w, received, need, dispensed, need - dispensed,
                                 expired, ordered, sum(on_hand.values()), sum(t[2] for t in transit), target))

    inv = pd.DataFrame(inv_rows, columns=[
        "site_id", "arm", "week", "kits_received", "kits_needed", "kits_dispensed",
        "kits_short", "kits_expired", "kits_ordered", "on_hand", "in_transit", "target"])
    inv["target"] = inv["target"].astype("Int64")  # blank (NULL) in weeks the rule was not asked
    ship = pd.DataFrame(ship_rows, columns=[
        "site_id", "arm", "lot_id", "ship_week", "arrive_week", "kits"])
    # One box per site per ship week, holding both arms if both were ordered.
    ship.insert(0, "shipment_id", ship.groupby(["site_id", "ship_week"]).ngroup() + 1)
    inv.insert(0, "policy", policy.NAME)
    ship.insert(0, "policy", policy.NAME)
    return {"inventory_week": inv, "shipment": ship, "lot": lots}
