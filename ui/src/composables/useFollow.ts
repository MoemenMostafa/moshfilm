// "Follow Claude": while Claude works on a scene the preview jumps to it, then plays it once after the edit lands.
// It only ever moves a preview that is paused and untouched; any user action wins.
import { inject, provide, ref, watch, type InjectionKey, type Ref } from "vue";
import { followKey, loadFlag, saveFlag } from "../activity";
import type { Activity, ActivityStep } from "../types";
import type { Playhead } from "./usePlayhead";

/** How long after the person last moved the playhead the preview counts as "in use". */
export const USER_QUIET_MS = 3000;
/** An edit whose completion and reload do not both show up within this long is forgotten. */
const PENDING_MS = 20_000;
const SLACK_MS = 2000;

interface FollowStore {
  folder: Ref<string>;
  activity: Ref<Activity>;
  sceneVersions: Ref<Record<string, number>>;
  slots: Ref<{ id: string; start: number; length: number }[]>;
}

export function createFollow(store: FollowStore, head: Playhead) {
  const enabled = ref(true);
  watch(store.folder, (f) => { enabled.value = loadFlag(followKey(f), true); }, { immediate: true });
  function toggle(): void {
    enabled.value = !enabled.value;
    saveFlag(followKey(store.folder.value), enabled.value);
  }

  const openedAt = Date.now();
  let lastUserMove = 0;
  let ownSeek: number | null = null;
  /** Set while we play a scene once: its time window. */
  let playing: { start: number; end: number } | null = null;
  /** True only while we pause at the end of our own play-through. */
  let autoPause = false;

  const idle = (): boolean => !head.playing.value && Date.now() - lastUserMove > USER_QUIET_MS;
  const slot = (id: string) => store.slots.value.find((s) => s.id === id);

  function seekTo(t: number): void {
    ownSeek = t;
    head.seek(t);
    if (head.time.value !== t) ownSeek = null;
  }

  // Any move of the playhead that is not ours is the user's.
  watch(head.time, (t) => {
    if (ownSeek !== null && Math.abs(t - ownSeek) < 1e-9) {
      ownSeek = null;
      return;
    }
    if (playing) {
      if (t < playing.start - 0.05 || t > playing.end + 0.5) { // scrubbed away: it is theirs now
        playing = null;
        lastUserMove = Date.now();
      } else if (t >= playing.end) {
        playing = null;
        autoPause = true;
        head.pause();
        autoPause = false;
      }
      return;
    }
    if (!head.playing.value) lastUserMove = Date.now();
  }, { flush: "sync" });

  watch(head.playing, (p) => {
    if (p) return;
    playing = null;
    if (!autoPause) lastUserMove = Date.now(); // a pause we did not make is the user's, even mid play-through
  }, { flush: "sync" });

  const seen = new Set<string>();
  const done = new Set<string>();
  const pending = new Map<string, { completed: boolean; reloaded: boolean; at: number }>();

  function tryPlay(id: string): void {
    const p = pending.get(id);
    if (!p || !p.completed || !p.reloaded) return;
    pending.delete(id);
    const s = slot(id);
    if (!s || !enabled.value || !idle()) return;
    seekTo(s.start);
    playing = { start: s.start, end: s.start + s.length };
    head.play();
  }

  function onStep(turnId: string, step: ActivityStep): void {
    const key = `${turnId}:${step.id}`;
    if (!step.scene || Date.parse(step.started) < openedAt - SLACK_MS) return;
    if (!seen.has(key)) {
      seen.add(key);
      if (!enabled.value) return;
      for (const [id, p] of pending) if (Date.now() - p.at > PENDING_MS) pending.delete(id);
      if (step.action === "edit") pending.set(step.scene, { completed: false, reloaded: false, at: Date.now() });
      const s = slot(step.scene);
      if (s && idle()) seekTo(s.start);
    }
    if (step.state !== "running" && !done.has(key)) {
      done.add(key);
      const p = step.action === "edit" ? pending.get(step.scene) : undefined;
      if (!p) return;
      if (step.state === "failed") pending.delete(step.scene);
      else {
        p.completed = true;
        tryPlay(step.scene);
      }
    }
  }

  watch(() => store.activity.value.turn, (turn) => {
    if (turn) for (const step of turn.steps) onStep(turn.id, step);
  }, { deep: true });

  watch(store.sceneVersions, (now, before) => {
    for (const [id, v] of Object.entries(now)) {
      if (before?.[id] === v) continue;
      const p = pending.get(id);
      if (!p) continue;
      p.reloaded = true;
      tryPlay(id);
    }
  });

  return { enabled, toggle };
}

export type Follow = ReturnType<typeof createFollow>;
export const FollowKey: InjectionKey<Follow> = Symbol("follow");
export const provideFollow = (f: Follow): void => provide(FollowKey, f);
export const useFollow = (): Follow | null => inject(FollowKey, null);
