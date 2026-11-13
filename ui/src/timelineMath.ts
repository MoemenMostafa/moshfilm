import { MIN_SCENE, type SceneSlot } from "./runtime/timing";

export const DEFAULT_PX_PER_SEC = 40;
export const MIN_PX_PER_SEC = 10;
export const MAX_PX_PER_SEC = 200;
export const SNAP = 0.1;
export const MIN_CLIP = 0.1; // shortest a text clip can be trimmed to, seconds

export const pxToTime = (px: number, pxPerSec: number): number => px / pxPerSec;
export const timeToPx = (t: number, pxPerSec: number): number => t * pxPerSec;

/** Round to the nearest step (default a tenth of a second), without float dust like 0.30000000000000004. */
export const snap = (t: number, step = SNAP): number => Number((Math.round(t / step) * step).toFixed(6));

/** New scene length after dragging its right edge `dxPx` pixels; never below the shortest scene. */
export function dragEdgeLength(startLen: number, dxPx: number, pxPerSec: number, snapOn: boolean): number {
  const raw = startLen + pxToTime(dxPx, pxPerSec);
  return Math.max(MIN_SCENE, snapOn ? snap(raw) : raw);
}

/**
 * Final position (index in the new order) for a scene dropped with its centre at film time `t`:
 * the index of the first other scene whose midpoint is after `t`, counted with the dragged scene
 * left out. Pass `excludeId` for the dragged scene.
 */
export function reorderIndex(slots: SceneSlot[], t: number, excludeId?: string): number {
  const others = slots.filter((s) => s.id !== excludeId);
  const i = others.findIndex((s) => s.start + s.length / 2 > t);
  return i === -1 ? others.length : i;
}

/** Follow a pointer drag: `move` runs with the distance moved so far, `end` once on release. */
export function trackDrag(
  start: PointerEvent | MouseEvent,
  move: (dxPx: number, shift: boolean) => void,
  end: (dxPx: number, shift: boolean) => void,
): void {
  const x0 = start.clientX;
  const onMove = (e: MouseEvent): void => move(e.clientX - x0, e.shiftKey);
  const onUp = (e: MouseEvent): void => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    end(e.clientX - x0, e.shiftKey);
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}
