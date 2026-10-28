// Half-circle dial with 3 positions (D3 v7).
//
//   const dial = makeDial(el, positions, onPick);   // positions: [{value, label, color}, ...] left to right
//   dial.set("normal");                             // move the needle (animated)

function makeDial(container, positions, onPick) {
  const w = 260, h = 128, cx = w / 2, cy = 104, r = 84;
  const n = positions.length;
  const span = Math.PI / n;  // each position gets an equal slice of the half circle
  const startOf = i => -Math.PI / 2 + i * span;  // d3.arc angles: 0 = 12 o'clock, clockwise
  const midDeg = i => (startOf(i) + span / 2) * 180 / Math.PI;

  const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${w} ${h}`).attr("class", "dialSvg");
  const g = svg.append("g").attr("transform", `translate(${cx},${cy})`);
  const arc = d3.arc().innerRadius(r - 22).outerRadius(r).padAngle(0.03).cornerRadius(3);

  const slices = g.selectAll(".slice").data(positions).join("path")
    .attr("class", "slice")
    .attr("d", (d, i) => arc({ startAngle: startOf(i), endAngle: startOf(i) + span }))
    .attr("fill", d => d.color)
    .on("click", (event, d) => onPick(d.value));
  slices.append("title").text(d => d.label);

  // Labels just outside the arc.
  g.selectAll(".dialLabel").data(positions).join("text")
    .attr("class", "dialLabel")
    .attr("x", (d, i) => Math.sin((startOf(i) + span / 2)) * (r + 12))
    .attr("y", (d, i) => -Math.cos((startOf(i) + span / 2)) * (r + 12))
    .attr("text-anchor", (d, i) => i === 0 ? "end" : i === n - 1 ? "start" : "middle")
    .text(d => d.label)
    .on("click", (event, d) => onPick(d.value));

  const needle = g.append("g").attr("class", "needle");
  needle.append("path").attr("d", `M -5 0 L 0 ${-(r - 30)} L 5 0 Z`);
  g.append("circle").attr("class", "hub").attr("r", 8);

  let current = null;
  function set(value) {
    const i = positions.findIndex(p => p.value === value);
    slices.classed("off", d => d.value !== value);
    g.selectAll(".dialLabel").classed("on", d => d.value === value);
    const from = current == null ? midDeg(i) : midDeg(current);
    needle.transition().duration(current == null ? 0 : 500).ease(d3.easeBackOut)
      .attrTween("transform", () => t => `rotate(${from + (midDeg(i) - from) * t})`);
    current = i;
  }
  return { set };
}
