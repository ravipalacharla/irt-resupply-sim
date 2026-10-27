-- Every table is keyed by trial_id (one simulated trial).
-- Supply tables add policy: the same trial replayed under each reorder rule.
-- Deleting a trial row removes everything for that trial (cascades down).

-- ---------- Phase 1: the trial (same for every policy) ----------

CREATE TABLE IF NOT EXISTS trial (
    trial_id     integer     PRIMARY KEY,               -- knob no. x 1000000 + scenario no. x 100000 + seed
    knob         text        NOT NULL,                  -- dashboard knob position (config.KNOBS)
    scenario     text        NOT NULL,                  -- base / surge / stall (config.SCENARIOS)
    seed         integer     NOT NULL,                  -- same seed = same base trial in every scenario
    master_seed  bigint      NOT NULL,
    params       jsonb       NOT NULL,          -- config.py values used for this trial
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS site (
    trial_id               integer          NOT NULL REFERENCES trial ON DELETE CASCADE,
    site_id                integer          NOT NULL,
    region                 text             NOT NULL,
    country                text             NOT NULL,
    country_approval_week  integer          NOT NULL,
    open_week              integer          NOT NULL,
    pace_per_week          double precision NOT NULL,  -- steady-state patients/week
    is_stumbling           boolean          NOT NULL,
    shocked                boolean          NOT NULL,  -- hit by the scenario's surge/stall
    shock_start_week       integer,                    -- NULL if not shocked
    PRIMARY KEY (trial_id, site_id)
);

CREATE TABLE IF NOT EXISTS site_week (
    trial_id     integer NOT NULL,
    site_id      integer NOT NULL,
    week         integer NOT NULL,
    week_start   date    NOT NULL,
    is_open      boolean NOT NULL,
    enrolled     integer NOT NULL,
    kits_needed  integer NOT NULL,                     -- all arms; per arm: GROUP BY on visit
    PRIMARY KEY (trial_id, site_id, week),
    FOREIGN KEY (trial_id, site_id) REFERENCES site ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS patient (
    trial_id      integer NOT NULL,
    patient_id    integer NOT NULL,
    site_id       integer NOT NULL,
    arm           text    NOT NULL,
    enroll_week   integer NOT NULL,
    end_week      integer NOT NULL,                    -- first week off treatment
    discontinued  boolean NOT NULL,                    -- stopped before protocol maximum
    PRIMARY KEY (trial_id, patient_id),
    FOREIGN KEY (trial_id, site_id) REFERENCES site ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS visit (
    trial_id    integer NOT NULL,
    patient_id  integer NOT NULL,
    arm         text    NOT NULL,                      -- copy of patient.arm, for easy per-arm demand
    visit_num     integer NOT NULL,
    week          integer NOT NULL,                    -- actual week (planned week if missed)
    planned_week  integer NOT NULL,                    -- previous actual visit + cycle length
    missed        boolean NOT NULL,                    -- skipped: no kit dispensed
    visit_date    date    NOT NULL,
    kits          integer NOT NULL,
    PRIMARY KEY (trial_id, patient_id, visit_num),
    FOREIGN KEY (trial_id, patient_id) REFERENCES patient ON DELETE CASCADE
);

-- ---------- Phase 2: supply ----------

CREATE TABLE IF NOT EXISTS lot (
    trial_id      integer NOT NULL REFERENCES trial ON DELETE CASCADE,
    lot_id        integer NOT NULL,
    arm           text    NOT NULL,
    mfg_date      date    NOT NULL,
    expiry_date   date    NOT NULL,
    release_date  date    NOT NULL,                    -- first day the depot can ship it
    release_week  integer NOT NULL,
    expiry_week   integer NOT NULL,
    PRIMARY KEY (trial_id, lot_id)
);

CREATE TABLE IF NOT EXISTS shipment (
    trial_id     integer NOT NULL,
    policy       text    NOT NULL,
    shipment_id  integer NOT NULL,                     -- one box per site per ship week
    site_id      integer NOT NULL,
    arm          text    NOT NULL,
    lot_id       integer NOT NULL,
    ship_week    integer NOT NULL,
    arrive_week  integer NOT NULL,
    kits         integer NOT NULL,
    PRIMARY KEY (trial_id, policy, shipment_id, arm),
    FOREIGN KEY (trial_id, site_id) REFERENCES site ON DELETE CASCADE,
    FOREIGN KEY (trial_id, lot_id) REFERENCES lot ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS inventory_week (
    trial_id        integer NOT NULL,
    policy          text    NOT NULL,
    site_id         integer NOT NULL,
    arm             text    NOT NULL,
    week            integer NOT NULL,
    kits_received   integer NOT NULL,
    kits_needed     integer NOT NULL,
    kits_dispensed  integer NOT NULL,
    kits_short      integer NOT NULL,                  -- > 0 means a stockout that week
    kits_expired    integer NOT NULL,                  -- removed: would expire before next visit
    kits_ordered    integer NOT NULL,
    on_hand         integer NOT NULL,                  -- end of week
    in_transit      integer NOT NULL,                  -- end of week
    target          integer,                           -- stock the rule aimed for; NULL if not asked
    PRIMARY KEY (trial_id, policy, site_id, arm, week),
    FOREIGN KEY (trial_id, site_id) REFERENCES site ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS policy_result (
    trial_id           integer          NOT NULL REFERENCES trial ON DELETE CASCADE,
    policy             text             NOT NULL,
    stockout_events    integer          NOT NULL,      -- site-arm-weeks with any shortfall
    kits_short         integer          NOT NULL,
    kits_expired       integer          NOT NULL,
    kits_left_at_end   integer          NOT NULL,      -- on hand + in transit at last week
    kits_shipped       integer          NOT NULL,
    shipments          integer          NOT NULL,
    avg_kits_at_sites  double precision NOT NULL,      -- all sites combined, average per week
    PRIMARY KEY (trial_id, policy)
);

-- ---------- Dashboard: Screen 2 (where and when do sites run out) ----------
-- Built from every trial of a run, so week-by-week rows need not be kept for all trials.

CREATE TABLE IF NOT EXISTS country_week_risk (
    knob                  text    NOT NULL,
    scenario              text    NOT NULL,
    policy                text    NOT NULL,
    country               text    NOT NULL,
    week                  integer NOT NULL,
    trials_with_stockout  integer NOT NULL,   -- trials where at least one site in the country ran short
    trials                integer NOT NULL,   -- trials in the run
    PRIMARY KEY (knob, scenario, policy, country, week)
);
