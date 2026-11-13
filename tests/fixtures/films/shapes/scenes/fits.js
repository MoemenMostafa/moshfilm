// Responsive: a centred box sized from the canvas, so it fits every shape.
const SVG = "http://www.w3.org/2000/svg";
export default {
  setup(root, ctx) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("width", ctx.width);
    svg.setAttribute("height", ctx.height);
    const box = document.createElementNS(SVG, "rect");
    const side = Math.min(ctx.width, ctx.height) * 0.5;
    box.setAttribute("x", (ctx.width - side) / 2);
    box.setAttribute("y", (ctx.height - side) / 2);
    box.setAttribute("width", side);
    box.setAttribute("height", side);
    box.setAttribute("fill", "#2563eb");
    svg.appendChild(box);
    root.appendChild(svg);
  },
  render() {},
};
