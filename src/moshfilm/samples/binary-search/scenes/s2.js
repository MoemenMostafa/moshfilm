// s2 — One by one: a highlight walks from the left, one locker per look, and a counter keeps score.
// It finds 37 on the fifth look; a ghost walk then shows the worst case, all sixteen.
import {
  COLORS, STEPS, el, label, lockerRow, pose, ramp, set, stage,
  targetPill,
} from "./lockers.js";

const FOUND_AT = STEPS[STEPS.length - 1].index; // 37 sits at index 4: the fifth look
const WALK_START = 0.9;
const WALK_STEP = 0.55;
const GHOST_START = 4.4;
const GHOST_STEP = 0.16;

let lockers;
let ticks;
let looks;
let looksLabel;
let worst;
let worstLabel;

/** Where the walk is at time t: the locker index under the highlight and how many looks so far. */
function walk(t) {
  if (t < WALK_START) return { at: -1, count: 0, ghost: false };
  const real = Math.floor((t - WALK_START) / WALK_STEP);
  if (real <= FOUND_AT) return { at: real, count: real + 1, ghost: false };
  if (t < GHOST_START) return { at: FOUND_AT, count: FOUND_AT + 1, ghost: false };
  const ghost = FOUND_AT + 1 + Math.floor((t - GHOST_START) / GHOST_STEP);
  return { at: Math.min(ghost, 15), count: Math.min(ghost, 15) + 1, ghost: true };
}

export default {
  setup(root, ctx) {
    const { svg, L } = stage(root, ctx, "02", "One by one");
    targetPill(svg, L);
    lockers = lockerRow(svg, L);
    ticks = lockers.map((locker) => el("circle", {
      cx: L.cx(locker.i), cy: L.bottomOf(locker.i) + 26, r: 5, fill: COLORS.target, opacity: 0,
    }, svg));
    // the two counters sit above the first row: left and right of the frame
    const leftX = L.wrap ? L.dw * 0.27 : 160;
    const rightX = L.wrap ? L.dw * 0.73 : 1120;
    const top = L.y(0) - 80;
    looks = label(svg, "0", { x: leftX, y: top, "font-size": 64, "font-weight": 800, fill: COLORS.ink });
    looksLabel = label(svg, "looks", { x: leftX, y: top + 44, "font-size": 18, fill: COLORS.muted, "font-weight": 600 });
    worst = label(svg, "16", { x: rightX, y: top, "font-size": 64, "font-weight": 800, fill: COLORS.out, opacity: 0 });
    worstLabel = label(svg, "worst case", {
      x: rightX, y: top + 44, "font-size": 18, fill: COLORS.out, "font-weight": 600, opacity: 0,
    });
  },

  render(t) {
    const w = walk(t);
    const found = t >= WALK_START + FOUND_AT * WALK_STEP;
    for (const L of lockers) {
      const tick = { opacity: 0, fill: L.i === FOUND_AT ? COLORS.found : COLORS.target };
      if (L.i <= FOUND_AT) {
        // A real look: the door opens and the locker lifts while it is being looked at.
        const start = WALK_START + L.i * WALK_STEP;
        const enter = ramp(t, start, start + 0.3);
        const focus = L.i === FOUND_AT ? enter : enter * (1 - ramp(t, start + WALK_STEP, start + WALK_STEP + 0.3));
        pose(L, {
          open: 0.9 * enter, lift: 14 * focus, ring: focus,
          ringColor: L.i === FOUND_AT ? COLORS.found : COLORS.target,
          innerColor: L.i === FOUND_AT ? COLORS.found : COLORS.target,
        });
        tick.opacity = enter;
      } else {
        // The ghost walk (worst case) only outlines each locker as it passes.
        const passed = w.ghost && L.i <= w.at;
        pose(L, { ring: passed && L.i === w.at ? 0.5 : 0, ringColor: COLORS.out });
        tick.opacity = passed ? 0.6 : 0;
        tick.fill = COLORS.out;
      }
      // a dot under every opened locker: amber for real looks, faint red for the ghost walk
      set(ticks[L.i], tick);
    }
    // The counter shows real looks; the ghost walk counts on the right, in red.
    const real = Math.min(w.count, FOUND_AT + 1);
    looks.textContent = String(real);
    set(looks, { fill: found ? COLORS.found : COLORS.ink, opacity: ramp(t, 0.2, 0.8) });
    set(looksLabel, { opacity: ramp(t, 0.2, 0.8) });
    looksLabel.textContent = real === 1 ? "look" : "looks";
    const g = ramp(t, GHOST_START, GHOST_START + 0.4);
    worst.textContent = String(w.ghost ? w.count : FOUND_AT + 2);
    set(worst, { opacity: g });
    const done = GHOST_START + (15 - FOUND_AT - 1) * GHOST_STEP;
    set(worstLabel, { opacity: ramp(t, done, done + 0.5) });
  },
};
