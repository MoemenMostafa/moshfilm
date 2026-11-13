// Shared data and drawing helpers for the "Binary search" sample film.
// Not a scene: s1..s6 import it relatively. Everything here is a pure function of its inputs.
//
// Responsive: scenes draw in "design units" and `stage()` scales them to the canvas. A wide shape (16:9) is
// designed 1280 units wide, exactly the picture the film always had; any other shape (9:16, 1:1, 4:5) is
// designed 720 units wide and as tall as its ratio needs, and the sixteen lockers wrap into two rows of eight.
// `layoutFor(ctx)` says where everything goes; the scenes place their own labels from it.

export const LOCKERS = [4, 9, 15, 22, 37, 41, 48, 52, 60, 66, 71, 79, 83, 88, 94, 99];
export const TARGET = 37;
export const STEPS = [
  { index: 7, value: 52, result: "too big" },
  { index: 3, value: 22, result: "too small" },
  { index: 5, value: 41, result: "too big" },
  { index: 4, value: 37, result: "found" },
];

export const COLORS = {
  paper: "#f6f4ef",
  ink: "#1c2230",
  muted: "#7d8496",
  faint: "#d9dce3",
  frame: "#141a26",
  door: "#2f3a4f",
  doorEdge: "#3d4a63",
  vent: "#55627c",
  focus: "#3b6ff6",
  target: "#f2a93b",
  out: "#e5604d",
  found: "#23a26d",
  bar: "#c7d2ea",
};

export const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";

// ---- timing helpers (pure functions of t) ----
export const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
export const lerp = (a, b, k) => a + (b - a) * k;
export const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
export const easeOut = (k) => 1 - Math.pow(1 - k, 3);
/** Eased progress 0..1 of the window [a, b] at time t. */
export const ramp = (t, a, b, ease = easeInOut) => ease(clamp((t - a) / (b - a), 0, 1));

// ---- layout: where things go in design units ----
const PAD = 64; // left and right margin of the header (chapter mark, target pill)
const TOP = 215; // design height above the first row: header, counters, pointers

/**
 * Layout for a canvas. `mid` is the free height between the two rows when they wrap (room for a bracket,
 * ticks or bars under the first row); `bottom` is the free height under the last row.
 * Returns { wrap, dw, dh, k, w, h, gap, mid, x(i), y(i), cx(i), cy(i), bottomOf(i), rowStart(r) }.
 */
export function layoutFor(ctx, { mid = 105, bottom = 215 } = {}) {
  const wrap = ctx.width / ctx.height < 1.5;
  const dw = wrap ? 720 : 1280;
  const dh = (dw * ctx.height) / ctx.width;
  const k = ctx.width / dw;
  let w = 62;
  let gap = 8;
  let h = 160;
  let x0 = 84;
  let y0 = 280;
  let perRow = 16;
  if (wrap) {
    perRow = 8;
    gap = 10;
    const margin = 48;
    w = (dw - 2 * margin - 7 * gap) / 8;
    h = Math.min(160, (dh - TOP - mid - bottom) / 2);
    x0 = margin;
    const extra = Math.max(0, dh - (TOP + 2 * h + mid + bottom));
    y0 = extra * 0.4 + TOP;
  }
  const rowGap = h + mid;
  return {
    wrap, dw, dh, k, w, h, gap, mid, perRow, rows: wrap ? 2 : 1,
    x: (i) => x0 + (i % perRow) * (w + gap),
    y: (i) => y0 + Math.floor(i / perRow) * rowGap,
    cx: (i) => x0 + (i % perRow) * (w + gap) + w / 2,
    cy: (i) => y0 + Math.floor(i / perRow) * rowGap + h / 2,
    bottomOf: (i) => y0 + Math.floor(i / perRow) * rowGap + h,
    /** x of the left edge of (fractional) locker f inside row r. */
    xAt: (f, r) => x0 + (f - r * perRow) * (w + gap),
  };
}

// ---- SVG helpers ----
const SVG = "http://www.w3.org/2000/svg";

export function el(name, attrs, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  if (parent) parent.appendChild(node);
  return node;
}

export function label(parent, text, attrs) {
  const node = el("text", {
    "font-family": FONT, "font-size": 20, fill: COLORS.ink, "text-anchor": "middle",
    "dominant-baseline": "central", "font-variant-numeric": "tabular-nums", ...attrs,
  }, parent);
  node.textContent = text;
  return node;
}

export function set(node, attrs) {
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
}

/**
 * Full-stage SVG with the paper background and the small chapter mark at the top left.
 * Returns { svg, L }: `svg` is the group everything is drawn into (in design units, scaled to the canvas)
 * and `L` is the layout for this canvas.
 */
export function stage(root, ctx, number, title, opts) {
  const outer = el("svg", {
    width: ctx.width, height: ctx.height, viewBox: `0 0 ${ctx.width} ${ctx.height}`,
    style: "display:block",
  }, root);
  el("rect", { x: 0, y: 0, width: ctx.width, height: ctx.height, fill: COLORS.paper }, outer);
  const L = layoutFor(ctx, opts);
  const svg = el("g", { transform: `scale(${L.k})` }, outer);
  const mark = el("g", {}, svg);
  label(mark, number, {
    x: PAD, y: 56, "text-anchor": "start", "font-size": 16, "font-weight": 700,
    fill: COLORS.focus, "letter-spacing": 1.5,
  });
  label(mark, title.toUpperCase(), {
    x: PAD + 32, y: 56, "text-anchor": "start", "font-size": 16, "font-weight": 600,
    fill: COLORS.muted, "letter-spacing": 1.5,
  });
  return { svg, L };
}

/** The "Looking for 37" pill at the top right. */
export function targetPill(svg, L) {
  const g = el("g", {}, svg);
  const x0 = L.dw - PAD - 204;
  el("rect", { x: x0, y: 34, width: 204, height: 44, rx: 22, fill: "#fff", stroke: COLORS.faint }, g);
  label(g, "Looking for", { x: x0 + 62, y: 56, "font-size": 16, fill: COLORS.muted, "font-weight": 500 });
  el("circle", { cx: x0 + 158, cy: 56, r: 17, fill: COLORS.target }, g);
  label(g, String(TARGET), { x: x0 + 158, y: 57, "font-size": 17, "font-weight": 800, fill: "#fff" });
  return g;
}

// ---- the locker row ----

/** One locker: a dark frame, an interior that shows the number when open, and a door hinged on the left. */
function locker(parent, i, lay) {
  const { w, h } = lay;
  const g = el("g", {}, parent);
  const ring = el("rect", {
    x: -5, y: -5, width: w + 10, height: h + 10, rx: 12, fill: "none",
    stroke: COLORS.focus, "stroke-width": 3, opacity: 0,
  }, g);
  el("rect", { x: 0, y: 0, width: w, height: h, rx: 8, fill: COLORS.frame }, g);
  const inner = label(g, String(LOCKERS[i]), {
    x: w / 2, y: h / 2, "font-size": 26, "font-weight": 800, fill: COLORS.focus, opacity: 0,
  });
  const door = el("g", {}, g);
  const doorRect = el("rect", {
    x: 2, y: 2, width: w - 4, height: h - 4, rx: 7, fill: COLORS.door, stroke: COLORS.doorEdge,
  }, door);
  for (let k = 0; k < 3; k++) {
    el("rect", { x: 14, y: 16 + k * 9, width: w - 28, height: 3, rx: 1.5, fill: COLORS.vent }, door);
  }
  el("rect", { x: w - 14, y: h / 2 + 26, width: 5, height: 20, rx: 2.5, fill: COLORS.vent }, door);
  const num = label(door, String(LOCKERS[i]), {
    x: w / 2, y: h / 2, "font-size": 24, "font-weight": 700, fill: "#fff",
  });
  return { g, ring, inner, door, doorRect, num, i, lay };
}

export function lockerRow(svg, lay) {
  const group = el("g", {}, svg);
  return LOCKERS.map((_, i) => locker(group, i, lay));
}

/**
 * Pose a locker for this frame.
 * lift: px upwards; open: 0 closed .. 1 open; ring: 0..1 outline; dim: 0..1 faded out.
 */
export function pose(L, { lift = 0, open = 0, ring = 0, ringColor = COLORS.focus, dim = 0, show = 1,
  innerColor = COLORS.focus, doorColor = COLORS.door } = {}) {
  set(L.g, {
    transform: `translate(${L.lay.x(L.i)}, ${L.lay.y(L.i) - lift})`,
    opacity: show * lerp(1, 0.16, dim),
  });
  set(L.ring, { opacity: ring, stroke: ringColor });
  const sx = lerp(1, 0.12, open);
  set(L.door, { transform: `matrix(${sx}, ${-0.18 * open}, 0, 1, 0, 0)` });
  set(L.doorRect, { fill: doorColor });
  set(L.num, { opacity: 1 - clamp(open * 1.6, 0, 1) });
  set(L.inner, { opacity: clamp(open * 1.6 - 0.6, 0, 1), fill: innerColor });
}

/** A small rounded tag (text on a coloured pill) centred at x, y; returns {g, bg, text}. */
export function tag(parent, text, { x, y, color, width = 120, size = 18 }) {
  const g = el("g", { transform: `translate(${x}, ${y})` }, parent);
  const bg = el("rect", { x: -width / 2, y: -18, width, height: 36, rx: 18, fill: color }, g);
  const t = label(g, text, { x: 0, y: 1, "font-size": size, "font-weight": 700, fill: "#fff" });
  return { g, bg, text: t };
}

/**
 * A bracket under lockers [a, b] with its count label; `pose` moves it smoothly between ranges.
 * When the lockers wrap into two rows the bracket is drawn in one piece per row.
 */
export function bracket(svg, L, color = COLORS.focus) {
  const g = el("g", {}, svg);
  const paths = Array.from({ length: L.rows }, () => el("path", { fill: "none", stroke: color, "stroke-width": 3,
    "stroke-linecap": "round", "stroke-linejoin": "round" }, g));
  const count = label(g, "", { "font-size": 30, "font-weight": 800, fill: color });
  return {
    g, paths, count,
    pose(from, to, text, opacity = 1) {
      let best = null;
      paths.forEach((path, r) => {
        const a = Math.max(from, r * L.perRow);
        const b = Math.min(to, r * L.perRow + L.perRow - 1);
        if (a > b) {
          set(path, { d: "", opacity: 0 });
          return;
        }
        const y = L.bottomOf(r * L.perRow) + 22;
        const x1 = L.xAt(a, r) + 4;
        const x2 = L.xAt(b, r) + L.w - 4;
        const mid = (x1 + x2) / 2;
        set(path, { d: `M${x1},${y} v12 H${mid - 10} l10,10 l10,-10 H${x2} v-12`, opacity: 1 });
        if (!best || x2 - x1 > best.span) best = { span: x2 - x1, mid, y };
      });
      if (best) set(count, { x: best.mid, y: best.y + 52 });
      count.textContent = text;
      set(g, { opacity });
    },
  };
}
