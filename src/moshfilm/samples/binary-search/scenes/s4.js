// s4 — Halve what is left: a bracket holds the lockers still in play. Each look (numbered badge)
// throws away about half, and the bracket shrinks: 16, then 7, then 3, then 1.
import {
  COLORS, STEPS, bracket, clamp, easeOut, el, label, lerp, lockerRow, pose, ramp, set,
  stage, targetPill,
} from "./lockers.js";

// After each look the range [lo, hi] that is still in play.
const RANGES = [[0, 15]];
for (const s of STEPS.slice(0, 3)) {
  const [lo, hi] = RANGES[RANGES.length - 1];
  RANGES.push(s.result === "too big" ? [lo, s.index - 1] : [s.index + 1, hi]);
}
// Each cut finishes as the voice says the new count ("then seven", "then three", "then one").
const CUTS = [3.9, 4.7, 5.5];
const CUT_TIME = 0.7;

let lockers;
let range;
let badges;

export default {
  setup(root, ctx) {
    const { svg, L } = stage(root, ctx, "04", "Halve what is left");
    targetPill(svg, L);
    lockers = lockerRow(svg, L);
    badges = STEPS.slice(0, 3).map((s, k) => {
      const g = el("g", {}, svg);
      el("circle", { cx: L.cx(s.index), cy: L.y(s.index) - 40, r: 16, fill: COLORS.focus }, g);
      label(g, String(k + 1), { x: L.cx(s.index), y: L.y(s.index) - 39, "font-size": 16, "font-weight": 800, fill: "#fff" });
      return g;
    });
    range = bracket(svg, L);
  },

  render(t) {
    // Progress through the three cuts: 0..3, eased within each cut.
    const cut = CUTS.map((c) => ramp(t, c, c + CUT_TIME));
    const done = cut.filter((c) => c >= 1).length;
    const k = done < 3 ? cut[done] : 1;
    const [lo0, hi0] = RANGES[done];
    const [lo1, hi1] = RANGES[Math.min(done + 1, 3)];
    const lo = lerp(lo0, lo1, k);
    const hi = lerp(hi0, hi1, k);
    const count = k > 0.5 ? hi1 - lo1 + 1 : hi0 - lo0 + 1;
    range.pose(lo, hi, String(count), ramp(t, 0.6, 1.4));

    for (const L of lockers) {
      // a locker fades as the edge of the range moves past it
      const outside = Math.max(lo - L.i, L.i - hi);
      const look = STEPS.slice(0, 3).findIndex((s) => s.index === L.i);
      const flash = look >= 0 ? ramp(t, CUTS[look] - 0.5, CUTS[look] - 0.1, easeOut) : 0;
      const settle = look >= 0 ? ramp(t, CUTS[look] + 0.2, CUTS[look] + CUT_TIME) : 0;
      pose(L, {
        lift: 12 * flash * (1 - settle),
        ring: flash * (1 - settle),
        dim: clamp(outside * 1.5, 0, 1),
      });
    }
    for (const [i, b] of badges.entries()) {
      const s = ramp(t, CUTS[i] - 0.5, CUTS[i] - 0.1, easeOut);
      set(b, { opacity: s * lerp(1, 0.55, ramp(t, CUTS[i] + 0.3, CUTS[i] + CUT_TIME)),
        transform: `translate(0, ${lerp(8, 0, s)})` });
    }
  },
};
