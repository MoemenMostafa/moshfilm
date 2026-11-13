// s1 — The sorted row: sixteen lockers rise into place, a small bar under each shows the numbers
// climbing from left to right, then the target (37) appears.
import {
  COLORS, LOCKERS, easeOut, el, lerp, lockerRow, pose, ramp, set, stage, targetPill,
} from "./lockers.js";

let lockers;
let bars;
let pill;
let L;
// Where each little bar sits under its locker: as before on a wide frame, in the gap under its own row when wrapped.
const barBase = (i) => L.bottomOf(i) + (L.wrap ? L.mid - 14 : 132);
const barMax = () => (L.wrap ? L.mid - 38 : 92);

export default {
  setup(root, ctx) {
    const made = stage(root, ctx, "01", "The sorted row");
    const svg = made.svg;
    L = made.L;
    bars = LOCKERS.map((_, i) => el("rect", {
      x: L.x(i) + 14, width: L.w - 28, rx: 4, fill: COLORS.bar,
    }, svg));
    lockers = lockerRow(svg, L);
    pill = targetPill(svg, L);
  },

  render(t) {
    // Lockers rise in one after another (0.3 s .. 2.5 s).
    for (const L of lockers) {
      const k = ramp(t, 0.3 + L.i * 0.1, 0.9 + L.i * 0.1, easeOut);
      pose(L, { lift: lerp(-36, 0, k), show: k });
    }
    // Bars grow left to right while the voice says the numbers rise (2.6 s .. 4.6 s).
    for (const [i, bar] of bars.entries()) {
      const k = ramp(t, 2.6 + i * 0.08, 3.4 + i * 0.08);
      const h = (LOCKERS[i] / 99) * barMax() * k;
      set(bar, { y: barBase(i) - h, height: h, opacity: k > 0 ? 1 : 0 });
    }
    // The target appears at "Somewhere in here is 37" and stays.
    const p = ramp(t, 5.4, 6.2, easeOut);
    set(pill, { opacity: p, transform: `translate(0, ${lerp(-14, 0, p)})` });
  },
};
