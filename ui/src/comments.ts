import type { Aspect, QueueItem } from "./types";

const round2 = (n: number): number => Math.round(n * 100) / 100;
const clamp01 = (n: number): number => Math.min(1, Math.max(0, n));

/** Click position -> 0..1 fraction pair inside the frame (the letterboxed stage, not the whole pane). */
export function toNormalizedPoint(clientX: number, clientY: number, stageRect: DOMRect): { x: number; y: number } {
  const w = stageRect.width || 1;
  const h = stageRect.height || 1;
  return {
    x: round2(clamp01((clientX - stageRect.left) / w)),
    y: round2(clamp01((clientY - stageRect.top) / h)),
  };
}

/** Comments pinned within `window` seconds of the playhead (only ones with a time). With `shape`, only the ones
 * made on that shape (a comment without one was made on the main shape). */
export function visiblePins(items: QueueItem[], t: number, window = 0.5,
  shape?: { aspect: Aspect; main: Aspect }): QueueItem[] {
  return items.filter((i) => i.kind === "comment" && i.time != null && Math.abs(i.time - t) <= window + 1e-9
    && (!shape || (i.aspect ?? shape.main) === shape.aspect));
}

export const commentColor = (state: QueueItem["state"]): string =>
  state === "resolved" ? "#22c55e" : state === "delivered" ? "#3b82f6" : "#9ca3af";
