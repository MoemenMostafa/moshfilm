// Example moshFilm scene: a bar grows from left to right, then a label fades in.
// Everything is built once in setup(); render(t) only sets styles and attributes.
// Responsive: every position and size comes from ctx.width / ctx.height, so the same scene
// draws correctly in 16:9, 9:16, 1:1 and 4:5 (setup runs again whenever the size changes).

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));
const lerp = (a, b, k) => a + (b - a) * k;
const easeInOut = (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);

const SVG = "http://www.w3.org/2000/svg";

function el(name, attrs, parent) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
  parent.appendChild(node);
  return node;
}

// One place that turns the canvas size into positions: fractions of the frame, type from the short side.
function arrange(ctx) {
  const portrait = ctx.height > ctx.width; // narrow shapes use more of the width
  const unit = Math.min(ctx.width, ctx.height) / 720; // 1 at the default short side
  const width = ctx.width * (portrait ? 0.8 : 0.62);
  return {
    left: (ctx.width - width) / 2,
    top: ctx.height * 0.5,
    width,
    thickness: 24 * unit,
    labelY: ctx.height * 0.4,
    font: 48 * unit,
  };
}

let bar;
let label;

export default {
  setup(root, ctx) {
    const a = arrange(ctx);
    const svg = el("svg", { width: ctx.width, height: ctx.height, viewBox: `0 0 ${ctx.width} ${ctx.height}` }, root);
    el("rect", { x: a.left, y: a.top, width: a.width, height: a.thickness, rx: a.thickness / 2, fill: "#e5e7eb" }, svg);
    bar = el("rect", { x: a.left, y: a.top, width: 0, height: a.thickness, rx: a.thickness / 2, fill: "#2563eb" }, svg);
    label = el("text", {
      x: ctx.width / 2, y: a.labelY, "text-anchor": "middle", fill: "#111827", opacity: 0,
      "font-family": "system-ui, sans-serif", "font-size": a.font, "font-weight": 700,
    }, svg);
    label.textContent = "Done in four steps";
  },

  render(t, ctx) {
    const a = arrange(ctx);
    // Grow the bar over the first 70% of the scene, then fade the label in.
    const grow = easeInOut(clamp(t / (ctx.length * 0.7), 0, 1));
    bar.setAttribute("width", lerp(0, a.width, grow));
    const fade = clamp((t - ctx.length * 0.7) / (ctx.length * 0.2), 0, 1);
    label.setAttribute("opacity", fade);
    label.setAttribute("y", lerp(a.labelY + ctx.height * 0.03, a.labelY, easeInOut(fade)));
  },
};
