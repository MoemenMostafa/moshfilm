// Finds content that does not fit the frame: pieces sticking out of it, and text clipped inside its own box.
// Runs inside the render page (see `window.moshfilm.overflow()`); the rules are Decision 4 of the aspects plan.

export interface OverflowHit {
  kind: "outside" | "clipped";
  /** Scene id, or `text:<clip id>` for a caption. */
  target: string;
  /** `left`, `right`, `top`, `bottom` (comma-joined when several) or `inside` for clipped text. */
  side: string;
  /** Largest overshoot in canvas pixels, rounded (0 for clipped text). */
  by: number;
  /** The element's tag plus up to 40 characters of its text, e.g. `<text> "Sixteen lockers"`. */
  text: string;
}

const SVG_SHAPES = new Set(["rect", "circle", "ellipse", "path", "line", "polyline", "polygon", "image", "text"]);
const HTML_MEDIA = new Set(["img", "canvas", "video"]);
const SVG_NON_RENDERED = "defs, clipPath, mask, pattern, symbol, marker, linearGradient, radialGradient, filter";
const MIN_OPACITY = 0.05;

function ownText(el: Element): string {
  let out = "";
  for (const n of Array.from(el.childNodes)) if (n.nodeType === 3) out += n.nodeValue ?? "";
  return out.replace(/\s+/g, " ").trim();
}

function isSvg(el: Element): boolean {
  return el.namespaceURI === "http://www.w3.org/2000/svg";
}

/** Effective visibility: display none on any ancestor, hidden visibility, or opacity under 0.05 hides an element. */
function visible(el: Element, stage: HTMLElement): boolean {
  let opacity = 1;
  let hiddenByInline: boolean | null = null; // nearest explicit inline visibility (for engines without inheritance)
  for (let n: Element | null = el; n && n !== stage.parentElement; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.display === "none") return false;
    const o = parseFloat(cs.opacity);
    if (!Number.isNaN(o)) opacity *= o;
    if (n === el && (cs.visibility === "hidden" || cs.visibility === "collapse")) return false;
    if (hiddenByInline === null) {
      const v = (n as HTMLElement).style?.visibility || n.getAttribute("visibility") || "";
      if (v === "hidden" || v === "collapse") hiddenByInline = true;
      else if (v === "visible") hiddenByInline = false;
    }
    if (n === stage) break;
  }
  return opacity >= MIN_OPACITY && hiddenByInline !== true;
}

export function findOverflow(stage: HTMLElement, tolerance = 2): OverflowHit[] {
  const frame = stage.getBoundingClientRect();
  const scale = stage.offsetWidth > 0 && frame.width > 0 ? frame.width / stage.offsetWidth : 1;
  const W = frame.width / scale;
  const H = frame.height / scale;
  const hits: OverflowHit[] = [];
  const seen = new Set<string>();

  const add = (el: Element, hit: Omit<OverflowHit, "target">): void => {
    const owner = el.closest("[data-text], [data-scene]");
    const target = owner?.hasAttribute("data-text")
      ? `text:${owner.getAttribute("data-text")}`
      : owner?.getAttribute("data-scene") ?? "frame";
    const key = `${target}|${hit.text}|${hit.kind}`;
    if (seen.has(key)) return;
    seen.add(key);
    hits.push({ ...hit, target });
  };

  for (const el of Array.from(stage.querySelectorAll("*"))) {
    const tag = el.localName.toLowerCase();
    const svg = isSvg(el);
    if (svg && (!SVG_SHAPES.has(tag) || el.closest(SVG_NON_RENDERED))) continue;
    const words = svg ? (tag === "text" ? (el.textContent ?? "").replace(/\s+/g, " ").trim() : "") : ownText(el);
    const isText = words !== "";
    if (svg && tag === "text" && !isText) continue;
    if (!svg && !isText && !HTML_MEDIA.has(tag)) continue;
    if (!visible(el, stage)) continue;

    const label = `<${tag}>` + (isText ? ` "${words.slice(0, 40)}"` : "");

    // (a) partly inside and partly outside the frame
    const r = el.getBoundingClientRect();
    if (r.width > 0 || r.height > 0) {
      const x0 = (r.left - frame.left) / scale;
      const x1 = (r.right - frame.left) / scale;
      const y0 = (r.top - frame.top) / scale;
      const y1 = (r.bottom - frame.top) / scale;
      const fullyOutside = x1 <= 0 || x0 >= W || y1 <= 0 || y0 >= H;
      if (!fullyOutside) {
        const bleedX = !isText && x0 <= 0 && x1 >= W; // a full-bleed background or band is fine
        const bleedY = !isText && y0 <= 0 && y1 >= H;
        const over: Array<[string, number]> = [
          ["left", bleedX ? 0 : -x0], ["right", bleedX ? 0 : x1 - W],
          ["top", bleedY ? 0 : -y0], ["bottom", bleedY ? 0 : y1 - H],
        ];
        const bad = over.filter(([, d]) => d > tolerance);
        if (bad.length) {
          add(el, { kind: "outside", side: bad.map(([s]) => s).join(","),
            by: Math.round(Math.max(...bad.map(([, d]) => d))), text: label });
        }
      }
    }

    // (b) text cut off by its own box
    if (!svg && isText) {
      const cs = getComputedStyle(el);
      const clips = [cs.overflow, cs.overflowX, cs.overflowY].some((v) => v && v !== "visible");
      const h = el as HTMLElement;
      if (clips && (h.scrollWidth - h.clientWidth > 1 || h.scrollHeight - h.clientHeight > 1)) {
        add(el, { kind: "clipped", side: "inside", by: 0, text: label });
      }
    }
  }
  return hits;
}
