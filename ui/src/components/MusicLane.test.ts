import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { Film, MusicBed, SoundCatalog } from "../types";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, uploadMusic: vi.fn(async () => ({ film: {} })) };
});
import * as api from "../api";
import MusicLane from "./MusicLane.vue";

const film = (music: Film["music"]) => ({ music }) as unknown as Film;
const catalog: SoundCatalog = { sfx: [], palettes: ["keys", "pluck", "pad", "chip"],
  keys: ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"], scales: ["major", "minor"], tempo: [60, 160],
  moods: [
    { name: "calm", label: "Calm", tempo: 80, scale: "major", palette: "pad" },
    { name: "tense", label: "Tense", tempo: 92, scale: "minor", palette: "pad" },
    { name: "playful", label: "Playful", tempo: 120, scale: "major", palette: "chip" }] };
const bed: MusicBed = { mood: "calm", tempo: 80, key: "C", scale: "major", palette: "keys", seed: 1 };
const withBed = (over: Partial<MusicBed> = {}, volume = 0.5) =>
  mount(MusicLane, { attachTo: document.body, props: { film: film({ file: null, bed: { ...bed, ...over }, volume }), total: 10, pxPerSec: 40, catalog } });
const full = (over: object = {}) => ({ op: "set_music_bed", ...bed, volume: 0.5, ...over });

describe("MusicLane", () => {
  beforeEach(() => vi.mocked(api.uploadMusic).mockClear());

  it("picker accepts audio and uploads the chosen file", async () => {
    const w = mount(MusicLane, { props: { film: film(null), total: 10, pxPerSec: 40 } });
    const input = w.get("[data-music-file]");
    expect(input.attributes("accept")).toBe("audio/*");
    const file = new File(["x"], "bed.mp3", { type: "audio/mpeg" });
    Object.defineProperty(input.element, "files", { value: [file] });
    await input.trigger("change");
    await flushPromises();
    expect(api.uploadMusic).toHaveBeenCalledWith(file);
  });

  it("volume slider and Remove send set_music", async () => {
    const w = mount(MusicLane, { props: { film: film({ file: "music/bed.mp3", volume: 0.6 }), total: 10, pxPerSec: 40 } });
    await w.get("[data-music-volume]").setValue("0.3");
    expect(w.emitted("edit")![0]).toEqual([[{ op: "set_music", file: "music/bed.mp3", volume: 0.3 }]]);
    await w.get("[data-music-remove]").trigger("click");
    expect(w.emitted("edit")![1]).toEqual([[{ op: "set_music", file: null, volume: 0.6 }]]);
  });

  it("without music shows 'No music' and no volume or Remove", () => {
    const w = mount(MusicLane, { props: { film: film(null), total: 10, pxPerSec: 40 } });
    expect(w.text()).toContain("No music");
    expect(w.find("[data-music-volume]").exists()).toBe(false);
    expect(w.find("[data-music-remove]").exists()).toBe(false);
  });

  it("generate music sends a calm bed", async () => {
    const w = mount(MusicLane, { props: { film: film(null), total: 10, pxPerSec: 40, catalog } });
    await w.get("[data-empty-action=generate-music]").trigger("click");
    expect(w.emitted("edit")).toEqual([[[full({ palette: "pad" })]]]);
    expect(w.find("[data-empty-action=add-music]").exists()).toBe(true);
  });

  it("bed bar shows its settings", () => {
    const w = withBed();
    expect(w.get("[data-music-bar]").text()).toContain("Calm · 80 bpm · C major · Keys · 50%");
    expect(w.find("[data-music-panel]").exists()).toBe(false);
  });

  it("options open a panel; changing mood resets tempo, scale and palette", async () => {
    const w = withBed({ key: "D", seed: 4 });
    await w.get("[data-music-options]").trigger("click");
    expect(w.find("[data-music-panel]").exists()).toBe(true);
    const mood = w.get("[data-music-mood]");
    (mood.element as HTMLSelectElement).value = "tense";
    await mood.trigger("change");
    expect(w.emitted("edit")).toEqual([[[full({ mood: "tense", tempo: 92, scale: "minor", palette: "pad", key: "D", seed: 4 })]]]);
  });

  it("key, scale and palette each send one edit with every field", async () => {
    const w = withBed();
    await w.get("[data-music-options]").trigger("click");
    for (const [hook, value] of [["key", "F#"], ["scale", "minor"], ["palette", "chip"]] as const) {
      const el = w.get(`[data-music-${hook}]`);
      (el.element as HTMLSelectElement).value = value;
      await el.trigger("change");
    }
    expect(w.emitted("edit")).toEqual([[[full({ key: "F#" })]], [[full({ scale: "minor" })]], [[full({ palette: "chip" })]]]);
  });

  it("tempo is clamped to 60-160", async () => {
    const w = withBed();
    await w.get("[data-music-options]").trigger("click");
    const t = w.get("[data-music-tempo]");
    (t.element as HTMLInputElement).value = "300";
    await t.trigger("change");
    (t.element as HTMLInputElement).value = "10";
    await t.trigger("change");
    expect(w.emitted("edit")).toEqual([[[full({ tempo: 160 })]], [[full({ tempo: 60 })]]]);
  });

  it("new variation bumps the seed, and quick clicks coalesce into one edit", async () => {
    vi.useFakeTimers();
    try {
      const w = withBed({ seed: 7 });
      await w.get("[data-music-options]").trigger("click");
      await w.get("[data-music-regenerate]").trigger("click");
      await w.get("[data-music-regenerate]").trigger("click");
      await w.get("[data-music-regenerate]").trigger("click");
      expect(w.emitted("edit")).toBeUndefined(); // nothing sent while the clicks keep coming
      vi.advanceTimersByTime(400);
      expect(w.emitted("edit")).toEqual([[[full({ seed: 10 })]]]);
      await w.get("[data-music-regenerate]").trigger("click");
      vi.advanceTimersByTime(400);
      expect(w.emitted("edit")![1]).toEqual([[full({ seed: 8 })]]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("New variation waits while a sound refresh is in flight", async () => {
    const w = mount(MusicLane, { attachTo: document.body, props: { film: film({ file: null, bed, volume: 0.5 }), total: 10,
      pxPerSec: 40, catalog, busy: true } });
    await w.get("[data-music-options]").trigger("click");
    expect(w.get("[data-music-regenerate]").attributes("disabled")).toBeDefined();
    await w.setProps({ busy: false });
    expect(w.get("[data-music-regenerate]").attributes("disabled")).toBeUndefined();
  });

  it("volume on a bed sends set_music_bed", async () => {
    const w = withBed();
    const slider = w.get("[data-music-volume]");
    (slider.element as HTMLInputElement).value = "0.3";
    await slider.trigger("change");
    expect(w.emitted("edit")).toEqual([[[full({ volume: 0.3 })]]]);
    await w.get("[data-music-remove]").trigger("click");
    expect(w.emitted("edit")![1]).toEqual([[{ op: "set_music", file: null, volume: 0.5 }]]);
  });

  it("file music keeps sending set_music and has no options", async () => {
    const w = mount(MusicLane, { props: { film: film({ file: "music/bed.mp3", volume: 0.6 }), total: 10, pxPerSec: 40, catalog } });
    expect(w.find("[data-music-options]").exists()).toBe(false);
    await w.get("[data-music-volume]").setValue("0.2");
    expect(w.emitted("edit")).toEqual([[[{ op: "set_music", file: "music/bed.mp3", volume: 0.2 }]]]);
  });
});
