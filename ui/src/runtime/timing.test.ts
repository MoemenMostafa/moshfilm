import { describe, expect, it } from "vitest";
import cases from "../../../tests/fixtures/timing_cases.json";
import { layout, locate, textWindow, totalLength } from "./timing";
import type { Film } from "../types";

function film(raw: any): Film {
  return {
    version: 1, width: 1280, height: 720, fps: 30, order_pinned: false,
    voice: { name: "v", rate: "+0%" }, music: null, ...raw,
    scenes: raw.scenes.map((s: any) => ({ file: null, status: "ready", ...s })),
    texts: raw.texts.map((t: any) => ({ style: "caption", x: null, y: null, ...t })),
  };
}

describe("timing fixture cases", () => {
  for (const c of cases as any[]) {
    it(c.name, () => {
      const f = film(c.film);
      const slots = layout(f, c.voice);
      expect(slots.map((s) => s.id)).toEqual(c.slots.map((s: any) => s.id));
      slots.forEach((s, i) => {
        const w = c.slots[i];
        expect(s.start).toBeCloseTo(w.start, 3);
        expect(s.length).toBeCloseTo(w.length, 3);
        expect(s.voiceStart).toBeCloseTo(w.voice_start, 3);
        expect(s.voiceSpeed).toBeCloseTo(w.voice_speed, 3);
        expect(s.overflow).toBe(w.overflow);
      });
      expect(totalLength(slots)).toBe(c.expected_total);
      f.texts.forEach((t, i) => {
        const [start, end] = textWindow(t, slots);
        expect(t.id).toBe(c.texts[i].id);
        expect(start).toBeCloseTo(c.texts[i].start, 3);
        expect(end).toBeCloseTo(c.texts[i].end, 3);
      });
    });
  }
});

describe("locate", () => {
  const f = film({ title: "t", pace: 1, texts: [], scenes: [
    { id: "a", title: "a", length: 5, pinned: false, voice: { text: "", offset: 0.3, pinned: false } },
    { id: "b", title: "b", length: 3, pinned: false, voice: { text: "", offset: 0.3, pinned: false } },
  ] });
  const slots = layout(f, {});
  it("boundary belongs to the next scene", () => {
    expect(locate(slots, 5)).toEqual({ sceneId: "b", sceneTime: 0 });
  });
  it("inside a scene", () => {
    expect(locate(slots, 6)).toEqual({ sceneId: "b", sceneTime: 1 });
  });
  it("negative clamps to first scene start", () => {
    expect(locate(slots, -1)).toEqual({ sceneId: "a", sceneTime: 0 });
  });
  it("at or after the end maps to the last scene end", () => {
    expect(locate(slots, 8)).toEqual({ sceneId: "b", sceneTime: 3 });
    expect(locate(slots, 99)).toEqual({ sceneId: "b", sceneTime: 3 });
  });
  it("empty film gives null", () => {
    expect(locate([], 1)).toBeNull();
  });
});
