import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import type { Film } from "../types";

const handlers: Record<string, (d: any) => void> = {};
vi.mock("../events", () => ({
  subscribe: vi.fn((h: Record<string, (d: any) => void>) => {
    Object.assign(handlers, h);
    return () => {};
  }),
}));
vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return {
    ...real,
    getActivity: vi.fn(), getFilm: vi.fn(), getVoice: vi.fn(), getProposals: vi.fn(), getQueue: vi.fn(), edit: vi.fn(), getHistory: vi.fn(), undo: vi.fn(), redo: vi.fn(), jumpHistory: vi.fn(), getSound: vi.fn(), getSoundCatalog: vi.fn(),
  };
});
import * as api from "../api";
import { createFilmStore } from "./useFilm";

function film(title: string): Film {
  return { version: 1, title, width: 1280, height: 720, fps: 30, pace: 1, order_pinned: false,
    voice: { name: "v", rate: "+0%" }, music: null, texts: [],
    scenes: [{ id: "red", title: "Red", file: "scenes/red.js", length: 2, pinned: true, status: "ready",
      voice: { text: "", offset: 0.3, pinned: false } }] };
}
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); await nextTick(); };

beforeEach(() => {
  vi.mocked(api.getFilm).mockResolvedValue({ film: film("one"), folder: "/f" });
  vi.mocked(api.getVoice).mockResolvedValue({ red: { url: "/x.mp3", duration: 1 } });
  vi.mocked(api.getProposals).mockResolvedValue({ proposals: [] });
  vi.mocked(api.getQueue).mockResolvedValue({ items: [], messages: [], status: null, connected: false });
  vi.mocked(api.getActivity).mockResolvedValue({ turn: null, plan: [] });
  vi.mocked(api.getSound).mockResolvedValue({ music: null, sfx: {} });
  vi.mocked(api.getSoundCatalog).mockResolvedValue({ sfx: [], moods: [], palettes: [], keys: [], scales: [], tempo: [60, 160] });
  vi.mocked(api.getFilm).mockClear();
});

describe("useFilm", () => {
  it("loads everything and computes slots", async () => {
    const s = createFilmStore();
    await flush();
    expect(s.film.value?.title).toBe("one");
    expect(s.folder.value).toBe("/f");
    expect(s.slots.value.length).toBe(1);
    expect(s.voice.value.red.duration).toBe(1);
  });

  it("loads sound info with the film", async () => {
    vi.mocked(api.getSound).mockResolvedValue({ music: { url: "/api/sound/bed-0123456789abcdef.wav", duration: 2 },
      sfx: { fx1: { url: "/api/sound/sfx-0123456789abcdef.wav", duration: 1.2 } } });
    const s = createFilmStore();
    await flush();
    expect(s.sound.value.music?.duration).toBe(2);
    expect(s.sound.value.sfx.fx1.duration).toBe(1.2);
    expect(api.getSoundCatalog).toHaveBeenCalledTimes(1);
    expect(s.catalog.value).not.toBeNull();
  });

  it("refreshes sound after the voice finishes", async () => {
    const s = createFilmStore();
    await flush();
    vi.mocked(api.getVoice).mockClear();
    vi.mocked(api.getSound).mockClear();
    vi.mocked(api.getVoice).mockResolvedValue({ red: { url: "/x.mp3", duration: 4 } });
    vi.mocked(api.getSound).mockResolvedValue({ music: { url: "/api/sound/bed-aaaaaaaaaaaaaaaa.wav", duration: 4.8 }, sfx: {} });
    handlers.voice({ state: "done", overflow: [] });
    await flush();
    expect(api.getVoice).toHaveBeenCalledTimes(1);
    expect(api.getSound).toHaveBeenCalledTimes(1);
    expect(s.sound.value.music?.url).toBe("/api/sound/bed-aaaaaaaaaaaaaaaa.wav");
  });

  it("ignores a sound answer that arrives after a newer one", async () => {
    const s = createFilmStore();
    await flush();
    let slow!: (v: any) => void;
    vi.mocked(api.getSound).mockReturnValueOnce(new Promise((r) => { slow = r; }));
    vi.mocked(api.getSound).mockResolvedValueOnce({ music: { url: "/api/sound/bed-bbbbbbbbbbbbbbbb.wav", duration: 9 }, sfx: {} });
    const first = s.refreshSound();
    const second = s.refreshSound();
    await second;
    expect(s.sound.value.music?.url).toContain("bbbbbbbb");
    slow({ music: { url: "/api/sound/bed-aaaaaaaaaaaaaaaa.wav", duration: 5 }, sfx: {} }); // the old length lands last
    await first;
    expect(s.sound.value.music?.url).toContain("bbbbbbbb");
  });

  it("is busy while a sound refresh runs, and a 409 for a stale bed is not shown as an error", async () => {
    const s = createFilmStore();
    await flush();
    let fail!: (e: unknown) => void;
    vi.mocked(api.getSound).mockReturnValueOnce(new Promise((_, rej) => { fail = rej; }));
    const p = s.refreshSound();
    expect(s.soundBusy.value).toBe(true);
    fail(new api.ApiError(409, "the film changed while its music was being made"));
    await p;
    expect(s.soundBusy.value).toBe(false);
    expect(s.error.value).toBeNull();
  });

  it("refetches film on film event", async () => {
    const s = createFilmStore();
    await flush();
    vi.mocked(api.getFilm).mockResolvedValue({ film: film("two"), folder: "/f" });
    handlers.film({});
    await flush();
    expect(s.film.value?.title).toBe("two");
  });

  it("shows the server message on 409 and clears it after a good load", async () => {
    const s = createFilmStore();
    await flush();
    vi.mocked(api.getFilm).mockRejectedValueOnce(new api.ApiError(409, "film.json is broken"));
    handlers.film({});
    await flush();
    expect(s.error.value).toBe("film.json is broken");
    expect(s.film.value?.title).toBe("one");
    handlers.film({});
    await flush();
    expect(s.error.value).toBeNull();
  });

  it("bumps the version of the scene whose file changed", async () => {
    const s = createFilmStore();
    await flush();
    handlers.scene({ file: "scenes/red.js", version: 123 });
    expect(s.sceneVersions.value).toEqual({ red: 123 });
    handlers.scene({ file: "scenes/nope.js", version: 5 });
    expect(s.sceneVersions.value).toEqual({ red: 123 });  // a file no scene uses has no scene version
  });

  it("edit stores the returned film", async () => {
    const s = createFilmStore();
    await flush();
    vi.mocked(api.edit).mockResolvedValue({ film: film("edited") });
    await s.edit([{ op: "set_title" }]);
    expect(s.film.value?.title).toBe("edited");
  });

  it("remembers a scene file version that arrived before film.json named the file", async () => {
    const s = createFilmStore();
    await flush();
    handlers.scene({ file: "scenes/blue.js", version: 9 });
    expect(s.sceneVersions.value).toEqual({});
    const f = film("two");
    f.scenes.push({ ...f.scenes[0], id: "blue", file: "scenes/blue.js" });
    vi.mocked(api.getFilm).mockResolvedValue({ film: f, folder: "/f" });
    handlers.film({});
    await flush();
    expect(s.sceneVersions.value).toEqual({ blue: 9 });
  });

  it("refetches voice on voice events and activity on activity events", async () => {
    const s = createFilmStore();
    await flush();
    vi.mocked(api.getVoice).mockResolvedValue({ red: { url: "/x.mp3", duration: 2.5 } });
    handlers.voice({ state: "done" });
    await flush();
    expect(s.voiceDurations.value.red).toBe(2.5);
    const turn = { id: "t", started: "", updated: "", ended: null, item: null, steps: [] };
    vi.mocked(api.getActivity).mockResolvedValue({ turn, plan: [{ text: "a", done: false }] });
    handlers.activity({});
    await flush();
    expect(s.activity.value.turn?.id).toBe("t");
    expect(s.activity.value.plan).toHaveLength(1);
  });
});
