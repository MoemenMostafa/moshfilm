// Not responsive: a 1200 px wide line at a fixed x. Fits 1280 wide, sticks out at 720 wide.
const SVG = "http://www.w3.org/2000/svg";
export default {
  setup(root, ctx) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("width", ctx.width);
    svg.setAttribute("height", ctx.height);
    const text = document.createElementNS(SVG, "text");
    text.setAttribute("x", 40);
    text.setAttribute("y", 200);
    text.setAttribute("textLength", 1200);
    text.setAttribute("lengthAdjust", "spacing");
    text.setAttribute("font-family", "system-ui, sans-serif");
    text.setAttribute("font-size", 40);
    text.textContent = "Sixteen lockers in a row";
    svg.appendChild(text);
    root.appendChild(svg);
  },
  render() {},
};
