import { describe, expect, it } from "vitest";
import cases from "../../../tests/fixtures/sfx_cases.json";
import { layout } from "./timing";
import { sfxAudible, sfxSceneEnd, sfxStart } from "./sound";
import type { Film, SfxClip } from "../types";

function film(raw: any): Film {
  return {
    version: 2, width: 1280, height: 720, fps: 30, order_pinned: false, pace: 1,
    voice: { name: "v", rate: "+0%" }, music: null, texts: [], ...raw,
    scenes: raw.scenes.map((s: any) => ({ file: null, status: "ready", pinned: false, voice: { text: "", offset: 0.3, pinned: false }, ...s })),
  };
}

describe("sfx starts match the shared fixture", () => {
  for (const c of cases as any[]) {
    it(c.name, () => {
      const f = film(c.film);
      const slots = layout(f, c.voice);
      for (const raw of c.film.sfx) {
        const clip: SfxClip = { volume: 0.7, pitch: 0, stretch: 1, seed: 0, pinned: false, at: 0, ...raw };
        expect(sfxStart(clip, slots)).toBeCloseTo(c.starts[clip.id], 3);
        expect(sfxAudible(clip, slots)).toBeCloseTo(c.audible[clip.id], 3);
      }
    });
  }

  it("keeps a sound on its cue near the scene end and cuts it at the scene end", () => {
    const slots = layout(film({ title: "t", scenes: [{ id: "s1", title: "a", length: 5, pinned: true }] }), {});
    const clip: SfxClip = { id: "x", scene: "s1", preset: "success", at: 4.8, volume: 1, pitch: 0, stretch: 1, seed: 0, pinned: false };
    expect(sfxStart(clip, slots)).toBe(4.8);
    expect(sfxAudible(clip, slots)).toBeCloseTo(0.2);
    expect(sfxSceneEnd(clip, slots)).toBe(5);
  });

  it("throws for an unknown scene", () => {
    const slots = layout(film({ title: "t", scenes: [{ id: "s1", title: "a", length: 2 }] }), {});
    expect(() => sfxStart({ id: "x", scene: "nope", preset: "pop", at: 0, volume: 1, pitch: 0, stretch: 1, seed: 0, pinned: false }, slots)).toThrow();
  });
});
