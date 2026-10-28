// Screen 3: one site, week by week. Loads the static files written by `python -m sim.export`.

// The dial and the switches. Each non-normal position points to one precomputed run (folder in data/).
// Only one setting can be off Normal at a time, because only those runs were computed.
const SETTINGS = {
  safety: { normal: "normal", options: [
    { value: "low", label: "Less", color: "#e8743b", run: "safety_low__base" },
    { value: "normal", label: "Normal", color: "#00A1DF", run: null },
    { value: "high", label: "More", color: "#3a9d5d", run: "safety_high__base" }] },
  shipping: { normal: "normal", options: [
    { value: "normal", label: "Normal", run: null },
    { value: "plus1", label: "+1 week", run: "shipping_plus1__base" }] },
  shelf: { normal: "24", options: [
    { value: "12", label: "12 mo", run: "shelf_12__base" },
    { value: "24", label: "24 mo", run: null },
    { value: "36", label: "36 mo", run: "shelf_36__base" }] },
  enroll: { normal: "normal", options: [
    { value: "slower", label: "Slower", run: "enroll_slower__base" },
    { value: "normal", label: "Normal", run: null },
    { value: "faster", label: "Faster", run: "enroll_faster__base" }] },
  shock: { normal: "none", options: [
    { value: "none", label: "None", run: null },
    { value: "surge", label: "Surge", run: "normal__surge" },
    { value: "stall", label: "Stall", run: "normal__stall" }] },
};
const DIAL_NOTES = {
  low: "Less cushion: fewer kits sitting at sites, more risk of running out.",
  normal: "Normal cushion: each rule's standard setting.",
  high: "More cushion: fewer stockouts, more kits sitting at sites (and expiring).",
};
const SPEEDS = [{ value: 1, label: "1×" }, { value: 2, label: "2×" }];
const PLAY_SECONDS = 10;   // how long Play takes at 1× to go through the whole trial

const state = {
  index: null, trial: null, runId: null, siteId: null, arm: null, rule: null, compare: null,
  week: Infinity,          // start on the full trial; Play replays it from week 0
  speed: 1,
  view: "site",            // "site" (one site, week by week) or "about" (how it works)
  summary: null,           // scores for all 200 trials of the current run
  settings: Object.fromEntries(Object.entries(SETTINGS).map(([k, s]) => [k, s.normal])),
};
const cache = {};          // trial files already downloaded, by run id
const summaries = {};      // summary files already downloaded, by run id
const $ = id => document.getElementById(id);
// "no-cache" = always ask the server if the file changed (after a re-export the browser would
// otherwise keep showing its old copy). Unchanged files come back as a tiny "not modified" reply.
const getJSON = async url => (await fetch(url, { cache: "no-cache" })).json();
const chart = makeStepChart($("chart"), w => { stop(); showWeek(w); });
const dial = makeDial($("dial"), SETTINGS.safety.options, v => changeSetting("safety", v));
let timer = null;

function ruleName(code) { return state.index.rules.find(r => r.code === code).name; }

function fill(select, options, value) {
  select.innerHTML = options.map(o => `<option value="${o.value}">${o.label}</option>`).join("");
  select.value = value;
}

// Segmented buttons (the small switches).
function seg(el, options, value, onPick) {
  el.innerHTML = options.map(o =>
    `<button type="button" data-v="${o.value}" class="${String(o.value) === String(value) ? "on" : ""}">${o.label}</button>`).join("");
  el.querySelectorAll("button").forEach(b => { b.onclick = () => onPick(b.dataset.v); });
}

// Week numbers to dates (week 0 = study start).
function dateOf(w) {
  const d = new Date(state.index.study_start + "T00:00:00");
  d.setDate(d.getDate() + 7 * w);
  return d3.timeFormat("%d %b %Y")(d);
}

// One rule's numbers for one site + arm, as one row per week 0..end_week.
function series(r, endWeek) {
  const lookup = pairs => new Map(pairs);  // [[week, kits], ...] -> week => kits
  const needed = lookup(r.needed), short = lookup(r.short), expired = lookup(r.expired), arrived = lookup(r.arrived);
  return d3.range(endWeek + 1).map(w => {
    const i = w - r.from;  // the file starts at week `from`; before that the shelf is empty
    return {
      week: w,
      onHand: i >= 0 ? r.on_hand[i] : 0,
      target: i >= 0 ? r.target[i] : null,
      needed: needed.get(w) || 0, short: short.get(w) || 0,
      expired: expired.get(w) || 0, arrived: arrived.get(w) || 0,
    };
  });
}

function site() { return state.trial.sites.find(s => s.site_id === state.siteId); }

function siteData() {
  const arm = site().arms[state.arm];
  const end = state.trial.end_week;
  return {
    endWeek: end, openWeek: site().open_week, dateOf,
    main: { code: state.rule, name: ruleName(state.rule), series: series(arm[state.rule], end) },
    compare: state.compare === "none" ? null
      : { code: state.compare, name: ruleName(state.compare), series: series(arm[state.compare], end) },
  };
}

// Run folder for the current settings (all normal -> normal__base).
function currentRun() {
  for (const [key, s] of Object.entries(SETTINGS)) {
    const opt = s.options.find(o => o.value === state.settings[key]);
    if (opt.run) return opt.run;
  }
  return "normal__base";
}

function changeSetting(key, value) {
  const othersMoved = Object.entries(state.settings).some(([k, v]) => k !== key && v !== SETTINGS[k].normal);
  for (const k of Object.keys(state.settings)) state.settings[k] = SETTINGS[k].normal;  // one at a time
  state.settings[key] = value;
  $("oneAtATime").classList.toggle("flash", othersMoved && value !== SETTINGS[key].normal);
  drawSettings();
  loadRun(currentRun());
}

function drawSettings() {
  dial.set(state.settings.safety);
  $("dialNote").textContent = DIAL_NOTES[state.settings.safety];
  for (const key of ["shipping", "shelf", "enroll", "shock"]) {
    seg($(`seg-${key}`), SETTINGS[key].options, state.settings[key], v => changeSetting(key, v));
  }
}

// The answer at a glance: first stockout for each rule, plus what it cost.
function headline() {
  const d = siteData();
  const open = d.openWeek;
  const card = (r, isMain) => {
    const s = r.series;
    const first = s.find(x => x.short);
    const avg = d3.mean(s.filter(x => x.week >= open), x => x.onHand) || 0;
    return `<div class="card ${isMain ? "mainCard" : "compareCard"}">
      <div class="cardRule">${r.name}</div>
      <div class="cardBig ${first ? "bad" : "good"}">${first
        ? `First stockout: week ${first.week} <span class="date">(${dateOf(first.week)})</span>`
        : "No stockout"}</div>
      <div class="cardSmall">Kits short <b>${d3.sum(s, x => x.short)}</b> ·
        Kits expired <b>${d3.sum(s, x => x.expired)}</b> ·
        Kits on the shelf (average) <b>${avg.toFixed(1)}</b> ·
        Shipments <b>${s.filter(x => x.arrived).length}</b></div></div>`;
  };
  $("headline").innerHTML = card(d.main, true) + (d.compare ? card(d.compare, false) : "");
}

function counters() {
  const d = siteData();
  const rows = [d.main, d.compare].filter(Boolean).map((r, i) => {
    const sofar = r.series.slice(0, state.week + 1);
    const short = d3.sum(sofar, x => x.short);
    return `<tr class="${i === 0 ? "mainRow" : "compareRow"}">
      <td>${r.name}</td>
      <td>${sofar[sofar.length - 1].onHand}</td>
      <td class="${short ? "bad" : ""}">${short}</td>
      <td>${d3.sum(sofar, x => x.expired)}</td>
      <td>${sofar.filter(x => x.arrived).length}</td></tr>`;
  });
  $("counters").innerHTML = `<table><thead><tr><th>Up to week ${state.week}</th><th>On the shelf now</th>
    <th>Kits short so far</th><th>Expired so far</th><th>Shipments arrived so far</th></tr></thead>
    <tbody>${rows.join("")}</tbody></table>`;
}

function showWeek(w) {
  state.week = w;
  $("weekLabel").textContent = `Week ${w} · ${dateOf(w)}`;
  chart.setWeek(w);
  counters();
}

// Settings in words, for the notes under the charts.
function settingsText() {
  const run = state.index.runs.find(r => r.id === state.runId);
  return run.knob === "normal" ? `normal, ${run.scenario_label.toLowerCase()}` : run.knob_label;
}

// One line under the headline: the picked rule against the compare rule over all 200 trials
// (not just this site). Trial-by-trial difference, since both rules play the same trials.
function trialsSentence() {
  const fmt = d3.format(".1f");
  const main = state.summary.rules[state.rule].kits_short;
  const n = state.summary.trials;
  const a = `<b>${ruleName(state.rule)}</b>`;
  if (state.compare === "none") {
    return `Across all ${n} trials (not just this site): ${a} averaged ${fmt(main.mean)} kits short per trial.`;
  }
  const other = state.summary.rules[state.compare].kits_short;
  const diffs = main.per_trial.map((v, i) => v - other.per_trial[i]);
  const mean = d3.mean(diffs), half = 1.96 * d3.deviation(diffs) / Math.sqrt(diffs.length);
  const lo = mean - half, hi = mean + half;
  const b = `<b>${ruleName(state.compare)}</b>`;
  const start = `Across all ${n} trials (not just this site): ${a} had`;
  if (lo > 0) return `${start} <b class="bad">${fmt(mean)} more</b> kits short per trial than ${b} (95% range ${fmt(lo)} to ${fmt(hi)} more).`;
  if (hi < 0) return `${start} <b class="good">${fmt(-mean)} fewer</b> kits short per trial than ${b} (95% range ${fmt(-hi)} to ${fmt(-lo)} fewer).`;
  return `Across all ${n} trials (not just this site): no clear difference in kits short between ${a} and ${b} ` +
    `(${fmt(main.mean)} vs ${fmt(other.mean)} per trial).`;
}

function redraw() {
  $("ruleLine").textContent = state.index.rules.find(r => r.code === state.rule).line;
  if (state.view === "about") return;
  $("runNote").textContent = `Showing example trial ${state.trial.trial}, one of the 200 simulated trials. ` +
    `Settings: ${settingsText()}.`;
  const s = site();
  $("siteTitle").textContent = `${s.story} · ${s.country_name}`;
  $("siteSub").textContent = `${s.region} · opens week ${s.open_week} (${dateOf(s.open_week)}) · Arm ${state.arm}`;
  seg($("armSeg"), Object.keys(s.arms).map(a => ({ value: a, label: `Arm ${a}` })), state.arm,
    v => { stop(); state.arm = v; redraw(); });
  headline();
  $("trialsLine").innerHTML = trialsSentence();
  chart.draw(siteData());
  showWeek(state.week);
}

function stop() {
  if (timer) timer.stop();
  timer = null;
  $("playBtn").textContent = "▶ Play";
}

function play(fromStart) {
  stop();
  const end = state.trial.end_week;
  const from = fromStart || state.week >= end ? 0 : state.week;  // at the end, start over
  const msPerWeek = PLAY_SECONDS * 1000 / state.speed / end;
  $("playBtn").textContent = "❚❚ Pause";
  showWeek(from);
  timer = d3.timer(elapsed => {
    const w = Math.min(end, from + Math.floor(elapsed / msPerWeek));
    if (w !== state.week) showWeek(w);
    if (w >= end) stop();
  });
}

async function loadRun(runId) {
  stop();
  state.runId = runId;
  if (!cache[runId]) {
    const seed = state.index.detail_trials[0];
    [cache[runId], summaries[runId]] = await Promise.all([
      getJSON(`data/${runId}/trial_${seed}.json`), getJSON(`data/${runId}/summary.json`)]);
  }
  state.trial = cache[runId];
  state.summary = summaries[runId];
  if (!state.trial.sites.some(s => s.site_id === state.siteId)) state.siteId = state.trial.sites[0].site_id;
  if (!state.arm) state.arm = site().default_arm;
  state.week = Math.min(state.week, state.trial.end_week);
  redraw();
}

async function main() {
  state.index = await getJSON("data/runs.json");
  state.rule = state.index.default_rule;
  state.compare = state.index.compare_rule;
  const [first, firstSummary] = await Promise.all([
    getJSON(`data/normal__base/trial_${state.index.detail_trials[0]}.json`), getJSON("data/normal__base/summary.json")]);
  cache.normal__base = first;
  summaries.normal__base = firstSummary;

  // Open on the site where the dial makes the most difference.
  state.siteId = (first.sites.find(s => s.story === "Often runs short") || first.sites[0]).site_id;
  fill($("siteSelect"), first.sites.map(s => ({ value: s.site_id, label: `${s.story} · ${s.country_name}` })),
    state.siteId);
  const ruleOpts = state.index.rules.map(r => ({ value: r.code, label: r.name }));
  fill($("ruleSelect"), ruleOpts, state.rule);
  fill($("compareSelect"), ruleOpts.concat([{ value: "none", label: "(nothing)" }]), state.compare);
  const setSpeed = v => {
    state.speed = +v;
    seg($("speedSeg"), SPEEDS, state.speed, setSpeed);
    if (timer) play(false);  // keep playing from this week at the new speed
  };
  seg($("speedSeg"), SPEEDS, state.speed, setSpeed);

  $("legend").innerHTML = `
    <span><i class="sw main"></i>On the shelf (picked rule)</span>
    <span><i class="sw target"></i>Target (picked rule)</span>
    <span><i class="sw compare"></i>On the shelf (compare rule)</span>
    <span><i class="sw short"></i>Kits short</span>
    <span><i class="sw expired"></i>Kits expired</span>
    <span><i class="sw arrived"></i>Shipment arrived</span>`;

  $("siteSelect").onchange = e => {
    stop(); state.siteId = +e.target.value; state.arm = site().default_arm; redraw();
  };
  $("ruleSelect").onchange = e => { stop(); state.rule = e.target.value; redraw(); };
  $("compareSelect").onchange = e => { stop(); state.compare = e.target.value; redraw(); };
  $("playBtn").onclick = () => (timer ? stop() : play(false));
  $("replayBtn").onclick = () => play(true);
  const togglePanel = show => {
    $("layout").classList.toggle("collapsed", !show);
    $("showPanel").hidden = show;
    redraw();  // the chart gets wider or narrower
  };
  document.querySelectorAll("#tabs button").forEach(b => {
    b.onclick = () => {
      stop();
      state.view = b.dataset.view;
      document.querySelectorAll("#tabs button").forEach(x => x.classList.toggle("on", x === b));
      $("aboutView").hidden = state.view !== "about";
      $("siteView").hidden = state.view !== "site";
      $("runNote").hidden = state.view !== "site";
      $("layout").classList.toggle("about", state.view === "about");  // settings do not apply here
      redraw();
    };
  });
  $("rulesTable").innerHTML = state.index.rules.map(r => `<tr><td>${r.name}</td><td>${r.line}</td></tr>`).join("");
  $("hidePanel").onclick = () => togglePanel(false);
  $("showPanel").onclick = () => togglePanel(true);

  drawSettings();
  await loadRun("normal__base");
}

main();
