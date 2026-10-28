// Animated step chart for one site and one arm (D3 v7).
//
//   const chart = makeStepChart(document.getElementById("chart"), week => ...);  // called on click
//   chart.draw(data);      // data: see app.js siteData()
//   chart.setWeek(40);     // show weeks 0..40 (the rest stays hidden)
//
// Above zero: kits on the shelf (step line) and the rule's target (dashed).
// Below zero: kits short (red) and kits expired (orange), as bars.
// The compare rule is drawn in grey on the same chart.

const COLORS = {
  main: "#1f6fd1",
  compare: "#8c8c8c",
  short: "#d62728",
  expired: "#f39c12",
  arrived: "#2ca02c",
};

function makeStepChart(container, onPick) {
  const margin = { top: 28, right: 20, bottom: 44, left: 48 };
  const height = 400;
  let data = null;
  let week = 0;
  let parts = null;  // the d3 selections that setWeek() updates

  function draw(newData) {
    data = newData;
    container.innerHTML = "";
    const width = Math.max(320, container.clientWidth) - margin.left - margin.right;
    const innerH = height - margin.top - margin.bottom;
    const end = data.endWeek + 1;  // a step for week w runs from w to w+1

    const rules = [data.main, data.compare].filter(Boolean);
    const top = d3.max(rules, r => d3.max(r.series, d => Math.max(d.onHand, d.target || 0)));
    const bottom = d3.max(rules, r => d3.max(r.series, d => d.short + d.expired));

    const x = d3.scaleLinear().domain([0, end]).range([0, width]);
    const y = d3.scaleLinear()
      .domain([-Math.max(2, bottom) * 1.15, Math.max(4, top) * 1.15])
      .range([innerH, 0])
      .nice();

    const svg = d3.select(container).append("svg")
      .attr("viewBox", `0 0 ${width + margin.left + margin.right} ${height}`)
      .attr("width", "100%");
    const g = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);

    // Axes. Negative y values are shown without the minus sign (they are counts below zero).
    g.append("g").attr("class", "axis").attr("transform", `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(Math.min(12, width / 70)).tickFormat(w => `wk ${w}`));
    g.append("g").attr("class", "axis")
      .call(d3.axisLeft(y).ticks(8).tickFormat(v => Math.abs(v)));
    g.append("text").attr("class", "axisLabel").attr("x", 0).attr("y", -12)
      .text("▲ kits on the shelf      ▼ kits short / expired");

    g.append("line").attr("class", "zero")
      .attr("x1", 0).attr("x2", width).attr("y1", y(0)).attr("y2", y(0));

    // Site opening week, always visible.
    if (data.openWeek > 0) {
      g.append("line").attr("class", "openLine")
        .attr("x1", x(data.openWeek)).attr("x2", x(data.openWeek)).attr("y1", 0).attr("y2", innerH);
      g.append("text").attr("class", "openText").attr("x", x(data.openWeek) + 4).attr("y", 10)
        .text("site opens");
    }

    // Everything inside `revealed` is cut off at the current week (that is the animation).
    const clipId = "clip-" + Math.random().toString(36).slice(2);
    const clipRect = svg.append("defs").append("clipPath").attr("id", clipId)
      .append("rect").attr("x", 0).attr("y", -margin.top).attr("height", height).attr("width", 0);
    const revealed = g.append("g").attr("clip-path", `url(#${clipId})`);

    const step = (yValue) => d3.line()
      .defined(d => yValue(d) != null)
      .x(d => x(d.week))
      .y(d => y(yValue(d)))
      .curve(d3.curveStepAfter);
    const withEnd = s => s.concat([{ ...s[s.length - 1], week: end }]);  // close the last step

    // Bars below zero: main rule on the left half of each week, compare rule on the right half.
    const barW = Math.max(1, (x(1) - x(0)) / 2);
    rules.forEach((r, i) => {
      const isMain = i === 0;
      const bars = revealed.append("g").attr("opacity", isMain ? 1 : 0.45);
      const rows = r.series.filter(d => d.short || d.expired);
      bars.selectAll(".short").data(rows.filter(d => d.short)).join("rect")
        .attr("x", d => x(d.week) + (isMain ? 0 : barW)).attr("width", barW)
        .attr("y", y(0)).attr("height", d => y(-d.short) - y(0))
        .attr("fill", COLORS.short);
      bars.selectAll(".expired").data(rows.filter(d => d.expired)).join("rect")
        .attr("x", d => x(d.week) + (isMain ? 0 : barW)).attr("width", barW)
        .attr("y", d => y(-d.short)).attr("height", d => y(-d.short - d.expired) - y(-d.short))
        .attr("fill", COLORS.expired);
    });

    if (data.compare) {
      revealed.append("path").attr("class", "line compare")
        .attr("d", step(d => d.onHand)(withEnd(data.compare.series)));
    }
    revealed.append("path").attr("class", "line target")
      .attr("d", step(d => d.target)(withEnd(data.main.series)));
    revealed.append("path").attr("class", "line main")
      .attr("d", step(d => d.onHand)(withEnd(data.main.series)));

    // Shipment arrivals (main rule): small green ticks along the bottom of the chart.
    revealed.selectAll(".arrival").data(data.main.series.filter(d => d.arrived)).join("path")
      .attr("class", "arrival")
      .attr("d", d3.symbol(d3.symbolTriangle, 18))
      .attr("transform", d => `translate(${x(d.week + 0.5)},${innerH - 5})`);

    // Stockout markers (main rule): red dots on the zero line, plus a flag at the first one.
    const shortWeeks = data.main.series.filter(d => d.short);
    revealed.selectAll(".stockDot").data(shortWeeks).join("circle")
      .attr("class", "stockDot").attr("r", 4.5)
      .attr("cx", d => x(d.week + 0.5)).attr("cy", y(0));
    let firstFlag = null;
    if (shortWeeks.length) {
      const fw = shortWeeks[0].week;
      firstFlag = g.append("g").attr("class", "firstFlag").style("display", "none");
      firstFlag.append("line").attr("x1", x(fw + 0.5)).attr("x2", x(fw + 0.5))
        .attr("y1", 0).attr("y2", innerH);
      const left = x(fw) > width * 0.7;  // keep the label inside the chart
      firstFlag.append("text").attr("x", x(fw + 0.5) + (left ? -6 : 6)).attr("y", 24)
        .attr("text-anchor", left ? "end" : "start")
        .text(`First stockout: week ${fw} (${data.dateOf(fw)})`);
    }

    // "Now" line that follows the animation.
    const cursor = g.append("line").attr("class", "cursor").attr("y1", 0).attr("y2", innerH);

    // Hover: a grey line and a box with that week's numbers.
    const hoverLine = g.append("line").attr("class", "hoverLine").attr("y1", 0).attr("y2", innerH)
      .style("display", "none");
    const tip = d3.select(container).append("div").attr("class", "tooltip").style("display", "none");
    const weekAt = (event) => Math.max(0, Math.min(data.endWeek, Math.floor(x.invert(d3.pointer(event)[0]))));
    g.append("rect").attr("class", "overlay").attr("width", width).attr("height", innerH).attr("fill", "transparent")
      .on("click", (event) => { if (onPick) onPick(weekAt(event)); })
      .on("mousemove", (event) => {
        const w = weekAt(event);
        hoverLine.style("display", null).attr("x1", x(w + 0.5)).attr("x2", x(w + 0.5));
        tip.style("display", null).html(tipHtml(w));
        const box = container.getBoundingClientRect();
        const px = event.clientX - box.left;
        tip.style("left", (px > box.width * 0.6 ? px - 230 : px + 16) + "px")
          .style("top", (event.clientY - box.top - 20) + "px");
      })
      .on("mouseleave", () => { hoverLine.style("display", "none"); tip.style("display", "none"); });

    parts = { x, clipRect, cursor, firstFlag, firstWeek: shortWeeks.length ? shortWeeks[0].week : null };
    setWeek(week);
  }

  function tipHtml(w) {
    const row = (r) => {
      const d = r.series[w];
      return `<div class="tipRule" style="color:${r === data.main ? COLORS.main : COLORS.compare}">${r.name}</div>
        <div>On the shelf: <b>${d.onHand}</b>${d.target != null && r === data.main ? ` (target ${d.target})` : ""}</div>
        <div>Kits needed: ${d.needed}${d.short ? ` · <span class="bad">short ${d.short}</span>` : ""}
          ${d.expired ? ` · <span class="warn">expired ${d.expired}</span>` : ""}
          ${d.arrived ? ` · arrived ${d.arrived}` : ""}</div>`;
    };
    return `<div class="tipWeek">Week ${w} · ${data.dateOf(w)}</div>` +
      row(data.main) + (data.compare ? row(data.compare) : "");
  }

  function setWeek(w) {
    week = w;
    if (!parts) return;
    const px = parts.x(w + 1);
    parts.clipRect.attr("width", px);
    parts.cursor.attr("x1", px).attr("x2", px);
    if (parts.firstFlag) parts.firstFlag.style("display", w >= parts.firstWeek ? null : "none");
  }

  window.addEventListener("resize", () => { if (data) draw(data); });
  return { draw, setWeek };
}
