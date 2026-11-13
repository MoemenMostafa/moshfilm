// s6 — Why it scales: looks needed (worst case) against the number of sorted items, on a log scale.
// The halving staircase climbs one step each time the items double; one by one shoots off the chart.
import { COLORS, easeOut, el, label, lerp, ramp, set, stage } from "./lockers.js";

// The plot area in design units; setup() sets it from the layout (wide frame: the original 200..1100 by 210..560).
const PLOT = { left: 200, right: 1100, top: 210, bottom: 560 };
const MAX_LOG = 6; // x axis: 1 .. 1,000,000 items
const MAX_LOOKS = 20;
const X = (n) => PLOT.left + (Math.log10(n) / MAX_LOG) * (PLOT.right - PLOT.left);
const Y = (looks) => PLOT.bottom - (looks / MAX_LOOKS) * (PLOT.bottom - PLOT.top);
/** Worst-case looks for n sorted items. */
const looksFor = (n) => Math.floor(Math.log2(n)) + 1;
const POINTS = [
  { n: 16, text: "16 → 5", dx: 0, dy: -32, anchor: "middle" },
  { n: 1024, text: "1,024 → 11", dx: 12, dy: 30, anchor: "start" },
  { n: 1000000, text: "1,000,000 → 20", dx: -14, dy: -30, anchor: "end" },
];
const TICKS = [[1, "1"], [10, "10"], [100, "100"], [1e3, "1K"], [1e4, "10K"], [1e5, "100K"], [1e6, "1M"]];

let axes;
let reveal;
let linear;
let linearLabel;
let double;
let points;

function staircase() {
  let d = `M${X(1)},${Y(1)}`;
  for (let k = 1; 2 ** k <= 1e6; k++) d += ` H${X(2 ** k)} V${Y(k + 1)}`;
  return `${d} H${X(1e6)}`;
}

export default {
  setup(root, ctx) {
    const { svg, L } = stage(root, ctx, "06", "Why it scales");
    // a narrow frame gets a narrower plot, and the plot's height follows the frame's design height
    Object.assign(PLOT, L.wrap
      ? { left: 100, right: 660, top: L.dh * 0.36, bottom: L.dh * 0.78 }
      : { left: 200, right: 1100, top: 210, bottom: 560 });
    const defs = el("defs", {}, svg);
    const clip = el("clipPath", { id: "bs-s6-reveal" }, defs);
    reveal = el("rect", { x: PLOT.left - 10, y: PLOT.top - 30, width: 0, height: PLOT.bottom - PLOT.top + 60 }, clip);

    axes = el("g", {}, svg);
    for (const v of [0, 5, 10, 15, 20]) {
      el("line", { x1: PLOT.left, x2: PLOT.right, y1: Y(v), y2: Y(v), stroke: v ? COLORS.faint : COLORS.muted,
        "stroke-width": v ? 1 : 1.5 }, axes);
      label(axes, String(v), { x: PLOT.left - 18, y: Y(v), "text-anchor": "end", "font-size": 16, fill: COLORS.muted });
    }
    for (const [n, text] of TICKS) {
      label(axes, text, { x: X(n), y: PLOT.bottom + 24, "font-size": 16, fill: COLORS.muted });
    }
    label(axes, "sorted items (each step right = ×10)", {
      x: (PLOT.left + PLOT.right) / 2, y: PLOT.bottom + 58, "font-size": 16, fill: COLORS.muted, "font-weight": 600,
    });
    label(axes, "looks", { x: PLOT.left - 18, y: PLOT.top - 34, "text-anchor": "end", "font-size": 16,
      fill: COLORS.muted, "font-weight": 600 });

    // One by one: n looks for n items — it leaves the top of the chart at only 20 items.
    let lin = "";
    for (let n = 1; n <= MAX_LOOKS; n += 0.25) lin += `${lin ? " L" : "M"}${X(n)},${Y(n)}`;
    linear = el("path", { d: lin, fill: "none", stroke: COLORS.target, "stroke-width": 3,
      "stroke-dasharray": "2 7", "stroke-linecap": "round" }, svg);
    linearLabel = label(svg, "one by one", { x: X(MAX_LOOKS) + 10, y: Y(MAX_LOOKS) - 4, "text-anchor": "start",
      "font-size": 18, "font-weight": 700, fill: COLORS.target });

    const drawn = el("g", { "clip-path": "url(#bs-s6-reveal)" }, svg);
    el("path", { d: staircase(), fill: "none", stroke: COLORS.focus, "stroke-width": 4,
      "stroke-linejoin": "round" }, drawn);

    // "Double → +1": the step between 16 and 32 items, called out.
    double = el("g", {}, svg);
    el("path", { d: `M${X(16)},${Y(5)} H${X(32)} V${Y(6)}`, fill: "none", stroke: COLORS.ink, "stroke-width": 6,
      "stroke-linejoin": "round", "stroke-linecap": "round" }, double);
    const [fromX, fromY] = [(X(16) + X(32)) / 2, Y(5) + 8];
    el("path", { d: `M${fromX},${fromY} L${fromX + 40},${Y(5) + 44} H${fromX + 92}`, fill: "none", stroke: COLORS.ink,
      "stroke-width": 1.5 }, double);
    label(double, "×2 items → +1 look", { x: fromX + 100, y: Y(5) + 44, "text-anchor": "start", "font-size": 20,
      "font-weight": 700, fill: COLORS.ink });

    points = POINTS.map((p) => {
      const g = el("g", {}, svg);
      el("circle", { cx: X(p.n), cy: Y(looksFor(p.n)), r: 8, fill: COLORS.focus, stroke: "#fff", "stroke-width": 3 }, g);
      label(g, p.text, { x: X(p.n) + p.dx, y: Y(looksFor(p.n)) + p.dy, "text-anchor": p.anchor,
        "font-size": 22, "font-weight": 800, fill: COLORS.ink });
      return { g, x: X(p.n) };
    });
  },

  render(t) {
    set(axes, { opacity: ramp(t, 0.2, 0.9) });
    const r = lerp(PLOT.left - 10, PLOT.right + 30, ramp(t, 0.8, 4.8));
    set(reveal, { width: r - (PLOT.left - 10) });
    const lin = ramp(t, 1.2, 2.0);
    set(linear, { opacity: lin * 0.9 });
    set(linearLabel, { opacity: lin });
    const d = ramp(t, 2.4, 3.0, easeOut);
    set(double, { opacity: d * (1 - 0.65 * ramp(t, 4.2, 4.8)) });
    for (const p of points) {
      set(p.g, { opacity: Math.min(1, Math.max(0, (r - p.x) / 25)) });
    }
  },
};
