import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import type { Film, SfxClip, SoundCatalog } from "../types";
import { layout } from "../runtime/timing";
import SfxLane from "./SfxLane.vue";

const scene = (id: string) => ({ id, title: id.toUpperCase(), file: null, length: 5, pinned: true,
  status: "ready" as const, voice: { text: "", offset: 0.3, pinned: false } });
const clip = (over: Partial<SfxClip> = {}): SfxClip => ({ id: "fx1", scene: "s2", preset: "ding", at: 0.5, volume: 0.7,
  pitch: 0, stretch: 1, seed: 0, pinned: true, ...over });
const makeFilm = (sfx: SfxClip[]): Film => ({ version: 2, title: "t", width: 1280, height: 720, fps: 30, pace: 1,
  order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null, removed_by_person: [],
  scenes: [scene("s1"), scene("s2")], texts: [], sfx });
const catalog: SoundCatalog = { sfx: [
  { name: "ding", label: "Ding", description: "bell", duration: 1.2 },
  { name: "pop", label: "Pop", description: "soft pop", duration: 0.08 }],
  moods: [], palettes: [], keys: [], scales: [], tempo: [60, 160] };

const ptr = (type: string, clientX: number, extra: object = {}) => new MouseEvent(type, { clientX, bubbles: true, ...extra });

function setup(sfx = [clip()], extra: object = {}) {
  const film = makeFilm(sfx);
  return mount(SfxLane, { attachTo: document.body, props: { film, slots: layout(film, {}), pxPerSec: 40, selected: null,
    durations: { fx1: 1.2 }, catalog, playhead: 6.25, ...extra } });
}

describe("SfxLane", () => {
  beforeEach(() => document.body.replaceChildren());

  it("places clips at their scene start plus at", () => {
    const w = setup();
    const el = w.get("[data-sfx=fx1]");
    expect(el.attributes("style")).toContain("left: 220px"); // (5 + 0.5) s * 40 px/s
    expect(el.attributes("style")).toContain("width: 48px"); // 1.2 s
    expect(el.text()).toContain("Ding");
  });

  it("drag onto the next scene re-anchors it", () => {
    const w = setup([clip({ scene: "s1", preset: "pop", at: 4 })]); // starts at 4 s (a short sound fits the scene end)
    w.get("[data-sfx=fx1]").element.dispatchEvent(ptr("pointerdown", 160));
    window.dispatchEvent(ptr("pointermove", 220));
    window.dispatchEvent(ptr("pointerup", 220)); // +60 px = +1.5 s -> 5.5 s = scene s2 at 0.5
    expect(w.emitted("select")).toEqual([[{ kind: "sfx", id: "fx1" }]]);
    expect(w.emitted("edit")).toEqual([[[{ op: "set_sfx_time", sfx: "fx1", scene: "s2", at: 0.5 }]]]);
  });

  it("a clip sticks where it was cued near a scene end, with the cut part hatched", () => {
    // ding (1.2 s) cued 0.5 s before the end of s2 (ends at 10 s): starts at 9.5 s, only 0.5 s is heard
    const w = setup([clip({ scene: "s2", at: 4.5 })]);
    const el = w.get("[data-sfx=fx1]");
    expect(el.attributes("style")).toContain("left: 380px"); // 9.5 s * 40, not pulled back to 8.8 s
    expect(el.attributes("style")).toContain("width: 48px");
    expect(w.get("[data-sfx-cut]").attributes("style")).toContain("width: 28px"); // 0.7 s of 1.2 s is cut
    expect(setup().find("[data-sfx-cut]").exists()).toBe(false); // a clip that fits has no hatching
  });

  it("small wiggle is a click, not an edit", () => {
    const w = setup();
    w.get("[data-sfx=fx1]").element.dispatchEvent(ptr("pointerdown", 100));
    window.dispatchEvent(ptr("pointerup", 102));
    expect(w.emitted("edit")).toBeUndefined();
    expect(w.emitted("select")).toEqual([[{ kind: "sfx", id: "fx1" }]]);
  });

  it("add menu adds at the playhead", async () => {
    const w = setup();
    expect(w.find("[data-sfx-menu]").exists()).toBe(false);
    await w.get("[data-sfx-add]").trigger("click");
    expect(w.findAll("[data-sfx-preset]").map((r) => r.attributes("data-sfx-preset"))).toEqual(["ding", "pop"]);
    await w.get("[data-sfx-preset=pop]").trigger("click");
    expect(w.emitted("edit")).toEqual([[[{ op: "add_sfx", preset: "pop", scene: "s2", at: 1.25 }]]]);
    expect(w.find("[data-sfx-menu]").exists()).toBe(false);
  });

  it("add is disabled with no scenes", () => {
    const film = { ...makeFilm([]), scenes: [] };
    const w = mount(SfxLane, { props: { film, slots: [], pxPerSec: 40, catalog } });
    expect(w.get("[data-sfx-add]").attributes("disabled")).toBeDefined();
  });

  it("audition plays the preset", async () => {
    const played: string[] = [];
    vi.stubGlobal("Audio", function (src: string) {
      return { play: () => { played.push(src); return Promise.resolve(); }, pause: () => {} };
    });
    const w = setup();
    await w.get("[data-sfx-add]").trigger("click");
    await w.get("[data-sfx-preset=ding] [data-sfx-audition]").trigger("click");
    expect(played).toEqual(["/api/sound/preset/ding.wav"]);
    expect(w.emitted("edit")).toBeUndefined(); // listening does not add
    vi.unstubAllGlobals();
  });

  it("volume slider sends set_sfx", async () => {
    const w = setup([clip()], { selected: { kind: "sfx", id: "fx1" } });
    expect(w.get("[data-sfx=fx1]").classes()).toContain("selected");
    (w.get("[data-sfx-volume]").element as HTMLInputElement).value = "0.3";
    await w.get("[data-sfx-volume]").trigger("change");
    expect(w.emitted("edit")).toEqual([[[{ op: "set_sfx", sfx: "fx1", volume: 0.3 }]]]);
  });

  it("pin button unpins", async () => {
    const w = setup();
    await w.get("[data-sfx=fx1] [data-pin]").trigger("click");
    expect(w.emitted("edit")).toEqual([[[{ op: "unpin", target: "sfx:fx1" }]]]);
    expect(setup([clip({ pinned: false })]).find("[data-pin]").exists()).toBe(false);
  });

  it("✕ asks to remove", async () => {
    const w = setup();
    await w.get("[data-sfx=fx1] [data-remove]").trigger("click");
    expect(w.emitted("remove")).toEqual([[{ kind: "sfx", id: "fx1" }]]);
    expect(w.emitted("edit")).toBeUndefined();
  });

  it("empty lane says No sounds", () => {
    const w = setup([]);
    expect(w.get("[data-empty-lane=sfx]").text()).toBe("No sounds");
  });
});
