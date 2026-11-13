import { describe, expect, it } from "vitest";
import cases from "../../../tests/fixtures/aspect_cases.json";
import { aspectFromSlug, aspectSlug, canvasSize, chosenAspects, mainAspect } from "./aspect";
import type { Film } from "../types";

function film(over: Partial<Film>): Film {
  return { version: 2, title: "t", width: 1280, height: 720, fps: 30, pace: 1, order_pinned: false,
    voice: { name: "v", rate: "+0%" }, music: null, scenes: [], texts: [], ...over };
}

describe("aspect", () => {
  it("canvas sizes match the shared fixture", () => {
    for (const c of cases as any[]) {
      const f = film(c.film);
      const { width, height } = canvasSize(f, c.aspect);
      expect([width, height]).toEqual(c.size);
    }
  });

  it("missing aspect means 16:9 main and no second", () => {
    const f = film({});
    expect(mainAspect(f)).toBe("16:9");
    expect(chosenAspects(f)).toEqual(["16:9"]);
    expect(chosenAspects(film({ second_aspect: "9:16" }))).toEqual(["16:9", "9:16"]);
  });

  it("slugs round-trip", () => {
    expect(aspectSlug("4:5")).toBe("4x5");
    expect(aspectFromSlug("1x1")).toBe("1:1");
    expect(aspectFromSlug("2x3")).toBeNull();
  });
});
