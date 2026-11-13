// s5 — Found it: the last locker in play opens on 37 with a burst; bars then compare
// four looks (halving) with five one by one here, and up to sixteen.
import {
  COLORS, STEPS, TARGET, easeOut, el, label, lerp, lockerRow, pose, ramp, set,
  stage, tag, targetPill,
} from "./lockers.js";

const FOUND = STEPS[STEPS.length - 1].index; // 4
const LOOKS = STEPS.length; // 4
const RAYS = 14;
// The comparison bars: wide frame as it always was, a narrower set under the last row when the lockers wrap.
let UNIT = 38; // design px per look
let BARS_X = 360;
let L;
let cx;
let cy;

let lockers;
let burst;
let rays;
let foundTag;
let halving;
let linear;
let worst;
let worstLabel;

/** One comparison bar: a name, a pale track (16 looks long), the bar and its value label. */
function barRow(svg, y, name, color) {
  const g = el("g", {}, svg);
  label(g, name, { x: BARS_X - 24, y, "text-anchor": "end", "font-size": 20, "font-weight": 600, fill: COLORS.ink });
  el("rect", { x: BARS_X, y: y - 14, width: 16 * UNIT, height: 28, rx: 14, fill: "#ebe8e1" }, g);
  const bar = el("rect", { x: BARS_X, y: y - 14, height: 28, rx: 14, fill: color }, g);
  const value = label(g, "", { y, "text-anchor": "start", "font-size": 20, "font-weight": 800, fill: color });
  return { g, bar, value };
}

/** Grow a bar to `looks` and keep its label just past the end. */
function grow(row, looks, text) {
  set(row.bar, { width: Math.max(looks * UNIT, 0.01) });
  row.value.textContent = text;
  set(row.value, { x: BARS_X + Math.max(looks, 0.7) * UNIT + 12, opacity: looks > 0.2 ? 1 : 0 });
}

export default {
  setup(root, ctx) {
    // no bracket here, so the rows sit close and the bars get the room under them
    const made = stage(root, ctx, "05", "Found it", { mid: 40, bottom: 190 });
    const svg = made.svg;
    L = made.L;
    UNIT = L.wrap ? 22 : 38;
    BARS_X = L.wrap ? 190 : 360;
    const halvingY = L.wrap ? L.bottomOf(15) + 60 : 520;
    const linearY = halvingY + 52;
    targetPill(svg, L);
    cx = L.cx(FOUND);
    cy = L.cy(FOUND);
    burst = el("circle", { cx, cy, r: 40, fill: "none", stroke: COLORS.found, "stroke-width": 4 }, svg);
    // Ray lengths vary a little; ctx.random is seeded per scene, so they come out the same every time.
    rays = Array.from({ length: RAYS }, (_, k) => {
      const a = (k / RAYS) * Math.PI * 2;
      const len = 26 + ctx.random() * 22;
      return { a, len, node: el("line", { stroke: COLORS.found, "stroke-width": 4, "stroke-linecap": "round" }, svg) };
    });
    lockers = lockerRow(svg, L);
    foundTag = tag(svg, `Found ${TARGET}`, { x: cx, y: L.y(FOUND) - 52, color: COLORS.found, width: 140 });
    halving = barRow(svg, halvingY, "Halving", COLORS.focus);
    linear = barRow(svg, linearY, "One by one", COLORS.target);
    // the worst case one by one: a dashed outline over the whole track
    worst = el("rect", { x: BARS_X, y: linearY - 14, height: 28, rx: 14, fill: "none", stroke: COLORS.out,
      "stroke-width": 2, "stroke-dasharray": "6 6" }, linear.g);
    worstLabel = label(linear.g, "16 at worst", { x: BARS_X + 16 * UNIT + 14, y: linearY, "text-anchor": "start",
      "font-size": 20, "font-weight": 800, fill: COLORS.out });
  },

  render(t) {
    const open = ramp(t, 0.6, 1.5);
    for (const L of lockers) {
      if (L.i === FOUND) {
        pose(L, { lift: 16 * open, open, ring: open, ringColor: COLORS.found, innerColor: COLORS.found });
      } else {
        pose(L, { dim: 1 - 0.3 * ramp(t, 3.0, 3.8) });
      }
    }
    // Burst: a ring and rays spread out and fade once (1.3 s .. 2.5 s).
    const b = ramp(t, 1.3, 2.5, easeOut);
    const cyNow = cy - 16 * open;
    set(burst, { r: lerp(50, 150, b), opacity: b > 0 ? (1 - b) * 0.8 : 0, cy: cyNow });
    for (const r of rays) {
      const r0 = lerp(60, 120, b);
      const r1 = r0 + r.len * (1 - b * 0.5);
      set(r.node, {
        x1: cx + Math.cos(r.a) * r0, y1: cyNow + Math.sin(r.a) * r0,
        x2: cx + Math.cos(r.a) * r1, y2: cyNow + Math.sin(r.a) * r1,
        opacity: b > 0 ? 1 - b : 0,
      });
    }
    const f = ramp(t, 1.4, 2.0, easeOut);
    set(foundTag.g, { opacity: f, transform: `translate(${cx}, ${L.y(FOUND) - 52 + lerp(10, 0, f)})` });

    // Comparison bars: halving 4, one by one 5 here, then up to 16 (dashed).
    const show = ramp(t, 3.0, 3.6);
    set(halving.g, { opacity: show });
    set(linear.g, { opacity: show });
    const h = ramp(t, 3.4, 4.2) * LOOKS;
    const l = ramp(t, 4.4, 5.2) * (FOUND + 1);
    grow(halving, h, `${Math.round(h)} looks`);
    grow(linear, l, `${Math.round(l)} here`);
    const w = ramp(t, 5.4, 6.2) * 16;
    set(worst, { width: Math.max(w * UNIT, 0.01), opacity: w > 0 ? 1 : 0 });
    set(worstLabel, { opacity: ramp(t, 6.0, 6.5) });
  },
};
