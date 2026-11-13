// Small pure helpers for the working card, the frame chip and the per-film toggles.
import type { ActivityTurn, FrameRef, Scene } from "./types";

export function fmtTime(t: number): string {
  const tenths = Math.floor(Math.max(t, 0) * 10 + 1e-6);
  const m = Math.floor(tenths / 600);
  const s = (tenths - m * 600) / 10;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}

/** The chip on a chat message that points at a frame, e.g. "⏸ 0:23.4 · 03 Open the middle". */
export function atChip(at: FrameRef, scenes: Pick<Scene, "id" | "title">[]): string {
  const index = at.scene ? scenes.findIndex((s) => s.id === at.scene) : -1;
  const where = index >= 0
    ? `${String(index + 1).padStart(2, "0")} ${scenes[index].title}`
    : (at.sceneTitle ?? "");
  return `⏸ ${fmtTime(at.time)}${where ? ` · ${where}` : ""}`;
}

export function fmtElapsed(ms: number): string {
  const total = Math.max(Math.floor(ms / 1000), 0);
  const m = Math.floor(total / 60);
  return m > 0 ? `${m}m ${total % 60}s` : `${total}s`;
}

export function turnElapsedMs(turn: ActivityTurn, now: number): number {
  const end = turn.ended ? Date.parse(turn.ended) : now;
  return end - Date.parse(turn.started);
}

/** "Worked 1m 12s · 6 steps": the one line a finished turn collapses to. */
export function workedSummary(turn: ActivityTurn): string {
  const n = turn.steps.length;
  return `Worked ${fmtElapsed(turnElapsedMs(turn, Date.now()))} · ${n} ${n === 1 ? "step" : "steps"}`;
}

// Per-film remembered toggles. Storage can be missing or throw (private window, blocked data): never rely on it.
export function loadFlag(key: string, fallback: boolean): boolean {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : raw === "1";
  } catch {
    return fallback;
  }
}

export function saveFlag(key: string, value: boolean): void {
  try {
    localStorage.setItem(key, value ? "1" : "0");
  } catch {
    /* not remembered; the toggle still works for this visit */
  }
}

export const attachFrameKey = (folder: string): string => `moshfilm.attachFrame:${folder}`;
export const followKey = (folder: string): string => `moshfilm.followClaude:${folder}`;
