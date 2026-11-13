// Mirror of src/moshfilm/timing.py. Both are checked against tests/fixtures/timing_cases.json.
import type { Film, TextClip } from "../types";

export const VOICE_PAUSE = 0.8; // silence after a voice line, seconds
export const PACE_MIN = 0.75;
export const PACE_MAX = 2.0;
export const MAX_SPEEDUP = 1.25; // fastest a voice line may be played to fit a pinned scene
export const MIN_SCENE = 0.5; // shortest an automatic scene length can get, seconds
export const OVERFLOW_COPY = "voice doesn't fit — stretch scene or shorten line"; // same text as timing.py

export interface SceneSlot {
  id: string;
  start: number;
  length: number;
  voiceStart: number;
  voiceSpeed: number;
  overflow: boolean;
}

// Same 3-decimal rounding as Python's round(x, 3): correctly rounded on the exact binary
// value, with exact ties going to the even neighbour (toFixed alone rounds ties up).
// An exact tie needs x = j/16 with j odd (the only odd multiples of 1/2000 that binary floats hit).
const r = (x: number): number => {
  const sixteenths = x * 16;
  if (Number.isInteger(sixteenths) && Math.abs(sixteenths) % 2 === 1) {
    const lo = Math.floor(x * 1000); // x * 1000 = j * 62.5, exact
    return (lo % 2 === 0 ? lo : lo + 1) / 1000;
  }
  return Number(x.toFixed(3));
};

export const round3 = r;

/** Place every scene on the timeline. `voice` maps scene id to its synthesised line's duration. */
export function layout(film: Film, voice: Record<string, number>): SceneSlot[] {
  const slots: SceneSlot[] = [];
  let start = 0;
  for (const scene of film.scenes) {
    const offset = scene.voice.offset;
    const d = voice[scene.id];
    const known = d !== undefined;
    let speed = 1;
    let overflow = false;
    let length: number;
    if (scene.pinned) {
      length = scene.length;
      if (known) {
        const avail = length - offset;
        if (avail <= 0) {
          speed = MAX_SPEEDUP;
          overflow = true;
        } else if (d > avail) {
          const wanted = d / avail;
          overflow = wanted > MAX_SPEEDUP;
          speed = Math.min(wanted, MAX_SPEEDUP);
        }
      }
    } else {
      const needed = known ? offset + d + VOICE_PAUSE : 0;
      length = Math.max(Math.max(scene.length, needed) * film.pace, needed, MIN_SCENE);
    }
    slots.push({ id: scene.id, start: r(start), length: r(length), voiceStart: r(start + offset),
      voiceSpeed: r(speed), overflow });
    start += length;
  }
  return slots;
}

export function totalLength(slots: SceneSlot[]): number {
  if (!slots.length) return 0;
  const last = slots[slots.length - 1];
  return r(last.start + last.length);
}

/** Absolute [start, end] of a text clip on the film timeline. */
export function textWindow(clip: TextClip, slots: SceneSlot[]): [number, number] {
  const slot = slots.find((s) => s.id === clip.scene);
  if (!slot) throw new Error(`text ${clip.id} points to unknown scene ${clip.scene}`);
  let start = slot.start + clip.start;
  let end = slot.start + (clip.end !== null ? clip.end : slot.length);
  if (!clip.pinned) {
    const lo = slot.start;
    const hi = slot.start + slot.length;
    start = Math.min(Math.max(start, lo), hi);
    end = Math.min(Math.max(end, lo), hi);
  }
  return [r(start), r(end)];
}

/** Scene and time inside it at film time `t` (half-open scene ranges). */
export function locate(slots: SceneSlot[], t: number): { sceneId: string; sceneTime: number } | null {
  if (!slots.length) return null;
  if (t < 0) return { sceneId: slots[0].id, sceneTime: 0 };
  for (const s of slots) {
    if (t < s.start + s.length) return { sceneId: s.id, sceneTime: r(t - s.start) };
  }
  const last = slots[slots.length - 1];
  return { sceneId: last.id, sceneTime: last.length };
}
