import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { ref } from "vue";
import type { Playhead } from "./usePlayhead";
import { activeClip, useAudioSync, type SfxPlay } from "./useAudioSync";

const clips = [
  { url: "/api/voice/aaaaaaaaaaaaaaaa.mp3", start: 1, speed: 1.25, duration: 5 }, // 1 .. 5
  { url: "/api/voice/bbbbbbbbbbbbbbbb.mp3", start: 8, speed: 1, duration: 2 }, // 8 .. 10
];

function fakeHead(): Playhead {
  return { time: ref(0), playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek: vi.fn() };
}

describe("activeClip", () => {
  it("returns offset scaled by speed", () => {
    expect(activeClip(clips, 3)).toEqual({ index: 0, offset: 2.5 });
    expect(activeClip(clips, 1)).toEqual({ index: 0, offset: 0 });
  });
  it("null in gaps", () => {
    expect(activeClip(clips, 0.5)).toBeNull();
    expect(activeClip(clips, 5)).toBeNull(); // clip is [start, start + duration/speed)
    expect(activeClip(clips, 6)).toBeNull();
    expect(activeClip(clips, 10)).toBeNull();
  });
});

describe("useAudioSync", () => {
  let created: HTMLAudioElement[];
  let playing: Set<HTMLAudioElement>;
  let play: Mock<() => Promise<void>>;
  let pause: Mock<() => void>;
  const byUrl = (u: string) => created.find((a) => a.src.endsWith(u))!;

  beforeEach(() => {
    created = [];
    playing = new Set();
    play = vi.fn(async () => {});
    pause = vi.fn();
    vi.stubGlobal("Audio", function (src?: string) {
      const a = document.createElement("audio");
      if (src) a.src = src;
      created.push(a);
      return a;
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLAudioElement) {
      playing.add(this);
      return play();
    });
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLAudioElement) {
      playing.delete(this);
      pause();
    });
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  function setup(music: { url: string; volume: number } | null = null) {
    const head = fakeHead();
    const clipRef = ref(clips);
    const musicRef = ref(music);
    const sync = useAudioSync(head, clipRef, musicRef);
    return { head, clipRef, musicRef, sync };
  }

  it("seek sets currentTime and playbackRate", () => {
    const { head } = setup();
    head.playing.value = true;
    head.time.value = 3;
    const a = created[0];
    expect(a.currentTime).toBeCloseTo(2.5);
    expect(a.playbackRate).toBe(1.25);
    expect((a as any).preservesPitch).toBe(true);
    expect(play).toHaveBeenCalled();
  });

  it("does not play while paused, but a seek positions the clip", () => {
    const { head, sync } = setup();
    head.time.value = 3;
    expect(play).not.toHaveBeenCalled();
    sync.dispose();
  });

  it("pauses every element on pause and when the playhead leaves the clip", () => {
    const { head } = setup();
    head.playing.value = true;
    head.time.value = 3;
    pause.mockClear();
    head.time.value = 6; // gap
    expect(pause).toHaveBeenCalled();
    head.time.value = 8.5;
    expect(created.length).toBeGreaterThan(1);
    pause.mockClear();
    head.playing.value = false;
    expect(pause).toHaveBeenCalled();
  });

  it("music volume ducks while voice active", () => {
    const { head, sync } = setup({ url: "/film/music/a.mp3", volume: 0.5 });
    head.playing.value = true;
    head.time.value = 0.2;
    expect(sync.musicElement()!.volume).toBeCloseTo(0.5);
    expect(sync.musicElement()!.loop).toBe(false);
    head.time.value = 3;
    expect(sync.musicElement()!.volume).toBeCloseTo(0.2); // 0.5 * 0.4
    head.time.value = 6;
    expect(sync.musicElement()!.volume).toBeCloseTo(0.5);
  });

  it("music follows the playhead position", () => {
    const { head, sync } = setup({ url: "/film/music/a.mp3", volume: 0.5 });
    head.playing.value = true;
    head.time.value = 7;
    expect(sync.musicElement()!.currentTime).toBeCloseTo(7);
  });

  it("a replaced voice url (edited line) uses the new audio, not the old", () => {
    const { head, clipRef } = setup();
    head.playing.value = true;
    head.time.value = 3;
    clipRef.value = [{ ...clips[0], url: "/api/voice/cccccccccccccccc.mp3" }];
    head.time.value = 3.1;
    expect(byUrl("/api/voice/cccccccccccccccc.mp3")).toBeTruthy();
    expect([...playing].map((a) => a.src)).toEqual([expect.stringContaining("cccccccccccccccc.mp3")]);
  });

  describe("sound effects", () => {
    const fx = (over: Partial<SfxPlay> = {}): SfxPlay => ({ id: "fx1", url: "/api/sound/sfx-aaaaaaaaaaaaaaaa.wav", start: 1, duration: 0.5, volume: 0.7, ...over });
    function withSfx(list: SfxPlay[]) {
      const head = fakeHead();
      const sfxRef = ref(list);
      const sync = useAudioSync(head, ref([]), ref(null), sfxRef);
      return { head, sfxRef, sync };
    }

    it("plays an sfx clip only inside its window", () => {
      const { head } = withSfx([fx()]);
      head.playing.value = true;
      head.time.value = 0.9;
      expect(playing.size).toBe(0);
      head.time.value = 1.1;
      const a = byUrl("sfx-aaaaaaaaaaaaaaaa.wav");
      expect(playing.has(a)).toBe(true);
      expect(a.currentTime).toBeCloseTo(0.1);
      head.time.value = 1.6;
      expect(playing.has(a)).toBe(false);
    });

    it("a 30 ms clip is not dropped by coarse playhead steps, and plays to its end", () => {
      const { head } = withSfx([fx({ id: "tick", url: "/api/sound/sfx-dddddddddddddddd.wav", start: 1.0, duration: 0.03 })]);
      head.playing.value = true;
      head.time.value = 0.9;
      expect(playing.size).toBe(0);
      head.time.value = 1.25; // 350 ms step: jumped clean over the 30 ms window
      const a = byUrl("sfx-dddddddddddddddd.wav");
      expect(playing.has(a)).toBe(true);
      pause.mockClear();
      head.time.value = 1.6; // the next tick must not cut the clip short
      expect(playing.has(a)).toBe(true);
      expect(pause).not.toHaveBeenCalled();
    });

    it("a short clip is triggered by an ordinary tick after its start and fires once", () => {
      const { head } = withSfx([fx({ start: 1.0, duration: 0.03 })]);
      head.playing.value = true;
      head.time.value = 0.99;
      head.time.value = 1.033; // 33 ms tick: already past the 30 ms of audio
      play.mockClear();
      head.time.value = 1.066;
      head.time.value = 1.1;
      expect(play).not.toHaveBeenCalled(); // already started, not restarted every tick
      expect(byUrl("sfx-aaaaaaaaaaaaaaaa.wav").currentTime).toBeCloseTo(0, 1);
    });

    it("a sound is faded out before its scene end and stopped there", () => {
      const { head } = withSfx([fx({ start: 1, duration: 3, end: 2 })]);
      head.playing.value = true;
      head.time.value = 1.1;
      const a = byUrl("sfx-aaaaaaaaaaaaaaaa.wav");
      expect(playing.has(a)).toBe(true);
      expect(a.volume).toBeCloseTo(0.7);
      head.time.value = 1.96; // 40 ms before the scene end: halfway down the 80 ms fade
      expect(playing.has(a)).toBe(true);
      expect(a.volume).toBeCloseTo(0.35, 1);
      head.time.value = 2.0; // the next scene starts: nothing rings over it
      expect(playing.has(a)).toBe(false);
      head.time.value = 2.1;
      expect(playing.has(a)).toBe(false);
    });

    it("a sound cued at the scene end does not start", () => {
      const { head } = withSfx([fx({ start: 2, duration: 1, end: 2 })]);
      head.playing.value = true;
      head.time.value = 1.9;
      head.time.value = 2.0;
      head.time.value = 2.1;
      expect(playing.size).toBe(0);
    });

    it("overlapping sfx play together", () => {
      const { head } = withSfx([fx(), fx({ id: "fx2", url: "/api/sound/sfx-bbbbbbbbbbbbbbbb.wav", start: 1.2, duration: 1 })]);
      head.playing.value = true;
      head.time.value = 1.3;
      expect(playing.size).toBe(2);
    });

    it("sfx use their own volume and are not ducked", () => {
      const head = fakeHead();
      useAudioSync(head, ref(clips), ref(null), ref([fx({ start: 2, duration: 1 })]));
      head.playing.value = true;
      head.time.value = 2.5; // inside the first voice clip (1 .. 5)
      expect(byUrl("sfx-aaaaaaaaaaaaaaaa.wav").volume).toBeCloseTo(0.7);
    });

    it("seek while paused places sfx without playing", () => {
      const { head } = withSfx([fx()]);
      head.time.value = 1.1;
      expect(byUrl("sfx-aaaaaaaaaaaaaaaa.wav").currentTime).toBeCloseTo(0.1);
      expect(play).not.toHaveBeenCalled();
    });

    it("keeps the element until the url changes", () => {
      const { head, sfxRef } = withSfx([fx()]);
      head.time.value = 1.1;
      const before = created.length;
      sfxRef.value = [fx({ volume: 0.3 })]; // same id + url: no new element
      expect(created.length).toBe(before);
      sfxRef.value = [fx({ url: "/api/sound/sfx-cccccccccccccccc.wav" })];
      expect(created.length).toBe(before + 1);
    });
  });

  it("generated bed url replaces the element when the length changes", () => {
    const { head, musicRef, sync } = setup({ url: "/api/sound/bed-aaaaaaaaaaaaaaaa.wav", volume: 0.5 });
    head.playing.value = true;
    head.time.value = 7;
    const first = sync.musicElement();
    expect(first!.src).toContain("bed-aaaaaaaaaaaaaaaa.wav");
    musicRef.value = { url: "/api/sound/bed-bbbbbbbbbbbbbbbb.wav", volume: 0.5 };
    const second = sync.musicElement();
    expect(second).not.toBe(first);
    expect(second!.src).toContain("bed-bbbbbbbbbbbbbbbb.wav");
    expect(playing.has(first!)).toBe(false);
  });
});
