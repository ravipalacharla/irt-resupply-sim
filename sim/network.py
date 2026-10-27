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
from sim.generator import trial_end_week


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
    """{(site_id, arm): array [week, i] = kits planned at week + 1 + i, as known at that week}.

    What a real system knows at week w, per patient on treatment at w:
    - the week of their last actual visit (known once it happens), or of a missed visit
      (known one week after its planned week, once its window has passed);
    - so their next visit is planned one cycle later. If that planned week has already come
      and gone without a visit, it is expected next week (still inside its window).
    Later cycles follow every VISIT_INTERVAL_WEEKS, up to the protocol maximum.
    It does not know the exact shift of future visits, future misses, or who will stop early.
    """
    W, L, I = c.TRIAL_WEEKS, c.SCHEDULE_LOOKAHEAD_WEEKS, c.VISIT_INTERVAL_WEEKS
    v = trial["visit"].sort_values(["patient_id", "visit_num"])
    known_at = np.where(v["missed"], v["planned_week"] + 1, v["week"])
    anchor = np.where(v["missed"], v["planned_week"], v["week"])
    events = {}
    for pid, k, a in zip(v["patient_id"].to_numpy(), known_at, anchor):
        events.setdefault(pid, ([], []))
        events[pid][0].append(k)
        events[pid][1].append(a)

    out = {}
    for (site_id, arm), g in trial["patient"].groupby(["site_id", "arm"]):
        arr = np.zeros((W, L), dtype=int)
        for p in g.itertuples():
            if p.patient_id not in events:   # no visit on record yet: nothing to project
                continue
            ev_known, ev_anchor = events[p.patient_id]
            cap = min(p.enroll_week + c.MAX_WEEKS_ON_TREATMENT, W)  # no visits at or after this
            j, last = 0, None
            for w in range(p.enroll_week, min(p.end_week, W)):      # weeks on treatment
                while j < len(ev_known) and ev_known[j] <= w:
                    last = ev_anchor[j]
                    j += 1
                nxt = max(last + I, w + 1)                           # overdue -> next week
                for vw in range(nxt, min(w + L + 1, cap), I):
                    arr[w, vw - w - 1] += c.KITS_PER_VISIT
        out[(site_id, arm)] = arr
    return out


def simulate_supply(trial, policy):
    """Run one reorder rule over one trial. Returns inventory_week, shipment, lot DataFrames."""
    lots = make_lots()
    expiry_week = lots.set_index("lot_id")["expiry_week"].to_dict()
    demand = demand_by_site_arm(trial)
    on_treatment = patients_on_treatment(trial)
    schedule = scheduled_kits(trial)
    # Rules may precompute per-trial inputs in one batch (the ML rule's predictions).
    prepared = policy.prepare(trial) if hasattr(policy, "prepare") else {}
    end = trial_end_week(trial)
    enrolled = trial["site_week"].pivot(index="site_id", columns="week", values="enrolled")
    enrolled = enrolled.reindex(columns=range(c.TRIAL_WEEKS), fill_value=0)
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
        # Per-arm state. Both arms are stepped through the same week together, so that when
        # one arm orders, the other can be topped up in the same box.
        arms = {arm: {
            "lots": lots[lots["arm"] == arm],
            "need": demand.get((s.site_id, arm), no_demand),
            "sched": schedule.get((s.site_id, arm), no_schedule),
            "prep": prepared.get((s.site_id, arm), no_schedule),
            "on_hand": {},   # lot_id -> kits
            "transit": [],   # (arrive_week, lot_id, kits)
        } for arm in c.ARMS}
        for w in range(end):
            site_done = w >= closed_from and active[w] == 0
            week = {}
            for arm, a in arms.items():
                # 1. receive
                received = 0
                for arrive, lot, kits in [t for t in a["transit"] if t[0] == w]:
                    a["on_hand"][lot] = a["on_hand"].get(lot, 0) + kits
                    received += kits
                a["transit"] = [t for t in a["transit"] if t[0] != w]

                # 2. expire
                expired = 0
                for lot in [l for l in a["on_hand"] if expiry_week[l] <= w + c.DISPENSE_BUFFER_WEEKS]:
                    expired += a["on_hand"].pop(lot)

                # 3. dispense, earliest expiry first (lot_id order = release order within an arm)
                need = int(a["need"][w])
                dispensed = 0
                for lot in sorted(a["on_hand"]):
                    take = min(a["on_hand"][lot], need - dispensed)
                    a["on_hand"][lot] -= take
                    dispensed += take
                    if a["on_hand"][lot] == 0:
                        del a["on_hand"][lot]
                    if dispensed == need:
                        break

                # 4a. ask the rule
                ordered, target = 0, None
                position = sum(a["on_hand"].values()) + sum(t[2] for t in a["transit"])
                if w >= supply_from and not site_done:
                    # Everything the rule may use. History arrays stop at this week ([: w + 1]).
                    known = {
                        "week": w, "arm": arm, "region": s.region, "lead_time": lead,
                        "enrolling": w < closed_from,
                        "weeks_open": w - s.open_week,           # negative before opening
                        "history": a["need"][: w + 1],           # kits needed per week so far
                        "enroll_history": site_enrolled[: w + 1],  # site patients enrolled per week so far
                        "scheduled": a["sched"][w],              # kits planned in each of the next weeks
                        "on_treatment": int(active[w]),          # site patients on treatment now
                        "prepared": a["prep"][w],                # rule's own precomputed input (ML)
                    }
                    ordered, target = policy.order_qty(sum(a["on_hand"].values()),
                                                       sum(t[2] for t in a["transit"]), known)
                week[arm] = [received, need, dispensed, expired, ordered, target, position]

            # 4b. one box per site per week: if any arm orders, top up every other arm to its
            # target too (no extra box, so it never costs a shipment).
            if any(v[4] > 0 for v in week.values()):
                for arm, v in week.items():
                    if v[4] == 0 and v[5] is not None and v[6] < v[5]:
                        v[4] = v[5] - v[6]

            for arm, v in week.items():
                a = arms[arm]
                received, need, dispensed, expired, ordered, target, _ = v
                if ordered > 0:
                    lot = int(a["lots"].loc[a["lots"]["release_week"] <= w, "lot_id"].max())
                    a["transit"].append((w + lead, lot, ordered))
                    ship_rows.append((s.site_id, arm, lot, w, w + lead, ordered))
                inv_rows.append((s.site_id, arm, w, received, need, dispensed, need - dispensed,
                                 expired, ordered, sum(a["on_hand"].values()),
                                 sum(t[2] for t in a["transit"]), target))

    inv = pd.DataFrame(inv_rows, columns=[
        "site_id", "arm", "week", "kits_received", "kits_needed", "kits_dispensed",
        "kits_short", "kits_expired", "kits_ordered", "on_hand", "in_transit", "target"])
    inv["target"] = inv["target"].astype("Int64")  # blank (NULL) in weeks the rule was not asked
    ship = pd.DataFrame(ship_rows, columns=[
        "site_id", "arm", "lot_id", "ship_week", "arrive_week", "kits"])
    # One box per site per ship week, holding both arms if both are in it.
    ship.insert(0, "shipment_id", ship.groupby(["site_id", "ship_week"]).ngroup() + 1)
    inv.insert(0, "policy", policy.NAME)
    ship.insert(0, "policy", policy.NAME)
    return {"inventory_week": inv, "shipment": ship, "lot": lots}
