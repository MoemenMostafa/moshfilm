import { beforeEach, describe, expect, it } from "vitest";
import { findOverflow } from "./overflow";

const SVG = "http://www.w3.org/2000/svg";
let stage: HTMLElement;

function rectOf(el: Element, l: number, t: number, r: number, b: number): void {
  (el as any).getBoundingClientRect = () => ({ left: l, top: t, right: r, bottom: b, width: r - l, height: b - t, x: l, y: t });
}
function num(el: Element, name: string, v: number): void {
  Object.defineProperty(el, name, { value: v, configurable: true });
}
function svgIn(parent: Element): SVGSVGElement {
  const s = document.createElementNS(SVG, "svg");
  parent.appendChild(s);
  return s;
}
function svgEl(parent: Element, tag: string, text?: string): SVGElement {
  const e = document.createElementNS(SVG, tag);
  if (text) e.textContent = text;
  parent.appendChild(e);
  return e;
}
function sceneRoot(id = "s1"): HTMLElement {
  const d = document.createElement("div");
  d.dataset.scene = id;
  stage.appendChild(d);
  return d;
}

beforeEach(() => {
  document.body.replaceChildren();
  stage = document.createElement("div");
  document.body.appendChild(stage);
  rectOf(stage, 0, 0, 1000, 500);
  num(stage, "offsetWidth", 1000);
});

describe("findOverflow", () => {
  it("flags an element partly outside on the right, with side and overshoot", () => {
    const t = svgEl(svgIn(sceneRoot()), "text", "Sixteen lockers");
    rectOf(t, 900, 100, 1100, 140);
    expect(findOverflow(stage)).toEqual([
      { kind: "outside", target: "s1", side: "right", by: 100, text: '<text> "Sixteen lockers"' },
    ]);
  });

  it("ignores an element fully outside the frame", () => {
    const r = svgEl(svgIn(sceneRoot()), "rect");
    rectOf(r, 1100, 0, 1300, 50);
    const t = svgEl(svgIn(sceneRoot("s2")), "text", "gone");
    rectOf(t, -400, 10, -100, 40);
    expect(findOverflow(stage)).toEqual([]);
  });

  it("allows a full-bleed background but not full-bleed text", () => {
    const svg = svgIn(sceneRoot());
    const bg = svgEl(svg, "rect");
    rectOf(bg, -10, 0, 1010, 50);
    expect(findOverflow(stage)).toEqual([]);
    const t = svgEl(svg, "text", "wide");
    rectOf(t, -10, 0, 1010, 50);
    const hits = findOverflow(stage);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ kind: "outside", side: "left,right", by: 10 });
  });

  it("ignores invisible elements", () => {
    const svg = svgIn(sceneRoot());
    const a = svgEl(svg, "text", "a");
    (a as any).style.display = "none";
    const b = svgEl(svg, "text", "b");
    (b as any).style.visibility = "hidden";
    const g = svgEl(svg, "g");
    (g as any).style.opacity = "0.02";
    const c = svgEl(g, "text", "c");
    for (const e of [a, b, c]) rectOf(e, 900, 0, 1100, 40);
    expect(findOverflow(stage)).toEqual([]);
  });

  it("flags clipped HTML text", () => {
    const box = document.createElement("div");
    box.textContent = "long words here";
    box.style.overflow = "hidden";
    sceneRoot().appendChild(box);
    rectOf(box, 10, 10, 210, 60);
    num(box, "scrollWidth", 300);
    num(box, "clientWidth", 200);
    num(box, "scrollHeight", 50);
    num(box, "clientHeight", 50);
    expect(findOverflow(stage)).toEqual([
      { kind: "clipped", target: "s1", side: "inside", by: 0, text: '<div> "long words here"' },
    ]);
  });

  it("names the scene or caption that owns the element", () => {
    const t1 = svgEl(svgIn(sceneRoot("s2")), "text", "in scene");
    rectOf(t1, 950, 0, 1050, 20);
    const cap = document.createElement("div");
    cap.dataset.text = "t1";
    cap.textContent = "caption";
    stage.appendChild(cap);
    rectOf(cap, -20, 400, 60, 430);
    expect(findOverflow(stage).map((h) => h.target).sort()).toEqual(["s2", "text:t1"]);
  });

  it("tolerance of 2 px", () => {
    const t = svgEl(svgIn(sceneRoot()), "text", "edge");
    rectOf(t, 900, 0, 1002, 20);
    expect(findOverflow(stage)).toEqual([]);
    rectOf(t, 900, 0, 1003, 20);
    expect(findOverflow(stage)).toHaveLength(1);
  });

  it("divides by the stage scale", () => {
    rectOf(stage, 0, 0, 500, 250); // shown at half size
    const t = svgEl(svgIn(sceneRoot()), "text", "half");
    rectOf(t, 450, 0, 550, 20); // 50 px outside on screen = 100 canvas px
    expect(findOverflow(stage)[0]).toMatchObject({ side: "right", by: 100 });
  });

  it("deduplicates the same element text", () => {
    const svg = svgIn(sceneRoot());
    for (let i = 0; i < 3; i++) rectOf(svgEl(svg, "text", "same"), 950, 0, 1050, 20);
    expect(findOverflow(stage)).toHaveLength(1);
  });
});
