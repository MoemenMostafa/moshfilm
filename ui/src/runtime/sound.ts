// Mirror of timing.sfx_start in src/moshfilm/timing.py. Both are checked against tests/fixtures/sfx_cases.json.
import type { SfxClip } from "../types";
import { round3, type SceneSlot } from "./timing";

/** Base length of every preset in seconds; same table as film.SFX_SECONDS (a clip lasts this times `stretch`). */
export const SFX_SECONDS: Record<string, number> = {
  whoosh: 0.55, "swoosh-up": 0.4, door: 0.7, ding: 1.2, pop: 0.08, tick: 0.02, click: 0.06,
  success: 0.9, error: 0.45, typewriter: 1.0, riser: 1.5, thud: 0.3,
};

export const sfxSeconds = (clip: SfxClip): number => (SFX_SECONDS[clip.preset] ?? 0.5) * clip.stretch;

/** A sound that crosses its scene's end fades out over the last 80 ms before it and is cut (timing.SFX_SCENE_FADE). */
export const SFX_SCENE_FADE = 0.08;

const clampAt = (clip: SfxClip, slot: SceneSlot): number => Math.min(Math.max(clip.at, 0), slot.length);

function slotOf(clip: SfxClip, slots: SceneSlot[]): SceneSlot {
  const slot = slots.find((s) => s.id === clip.scene);
  if (!slot) throw new Error(`sound ${clip.id} points to unknown scene ${clip.scene}`);
  return slot;
}

/** Absolute start of a sound clip: exactly its scene's start plus `at` (the person's cue), `at` only clamped
 *  into the scene (0 to the scene length). */
export function sfxStart(clip: SfxClip, slots: SceneSlot[]): number {
  const slot = slotOf(clip, slots);
  return round3(slot.start + clampAt(clip, slot));
}

/** Seconds of the sound that play before its scene ends (the rest is faded out and cut). */
export function sfxAudible(clip: SfxClip, slots: SceneSlot[]): number {
  const slot = slotOf(clip, slots);
  return round3(Math.max(0, Math.min(sfxSeconds(clip), slot.length - clampAt(clip, slot))));
}

/** Absolute second the sound is cut at: the end of its scene. */
export const sfxSceneEnd = (clip: SfxClip, slots: SceneSlot[]): number => {
  const slot = slotOf(clip, slots);
  return round3(slot.start + slot.length);
};
