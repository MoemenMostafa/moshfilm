// s3 — Open the middle: a pointer finds the middle locker, its door swings open on 52,
// 52 is compared with 37 (too big), and every locker to its right fades out.
import {
  COLORS, STEPS, TARGET, bracket, easeOut, el, label, lerp, lockerRow, pose, ramp,
  set, stage, tag, targetPill,
} from "./lockers.js";

const MID = STEPS[0].index; // 7
const VALUE = STEPS[0].value; // 52

let lockers;
let pointer;
let compare;
let verdict;
let out;
let L;

export default {
  setup(root, ctx) {
    const made = stage(root, ctx, "03", "Open the middle");
    const svg = made.svg;
    L = made.L;
    targetPill(svg, L);
    lockers = lockerRow(svg, L);
    const x = L.cx(MID);
    const top = L.y(MID); // everything about the middle locker hangs above it
    pointer = el("g", {}, svg);
    label(pointer, "middle", { x, y: top - 66, "font-size": 18, "font-weight": 600, fill: COLORS.focus });
    el("path", { d: `M${x - 9},${top - 44} h18 l-9,12 z`, fill: COLORS.focus }, pointer);
    compare = label(svg, `${VALUE} > ${TARGET}`, {
      x, y: top - 112, "font-size": 40, "font-weight": 800, fill: COLORS.ink,
    });
    verdict = tag(svg, "too big", { x, y: top - 60, color: COLORS.out });
    out = bracket(svg, L, COLORS.out);
  },

  render(t) {
    const point = ramp(t, 0.5, 1.3, easeOut);
    const open = ramp(t, 2.1, 3.1);
    const cmp = ramp(t, 3.6, 4.3, easeOut);
    for (const L of lockers) {
      if (L.i === MID) {
        pose(L, {
          lift: 14 * open, open, ring: open, innerColor: COLORS.out,
          ringColor: cmp > 0 ? COLORS.out : COLORS.focus, dim: 0.5 * ramp(t, 6.4, 7.0),
        });
      } else {
        // the right half fades out one after another (5.3 s .. 6.6 s)
        const d = L.i > MID ? ramp(t, 5.3 + (L.i - MID - 1) * 0.12, 5.8 + (L.i - MID - 1) * 0.12) : 0;
        pose(L, { dim: d });
      }
    }
    set(pointer, { opacity: point * (1 - ramp(t, 3.2, 3.6)), transform: `translate(0, ${lerp(-16, 0, point)})` });
    set(compare, { opacity: cmp, transform: `translate(0, ${lerp(10, 0, cmp)})` });
    const v = ramp(t, 4.4, 4.9, easeOut);
    set(verdict.g, { opacity: v, transform: `translate(${L.cx(MID)}, ${L.y(MID) - 60 + lerp(8, 0, v)})` });
    out.pose(MID + 1, 15, "out", ramp(t, 5.6, 6.4) * 0.9);
  },
};
