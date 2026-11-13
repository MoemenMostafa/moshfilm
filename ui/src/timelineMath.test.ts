import { afterEach, describe, expect, it, vi } from "vitest";
import { dragEdgeLength, pxToTime, reorderIndex, snap, timeToPx, trackDrag } from "./timelineMath";
import type { SceneSlot } from "./runtime/timing";

const slot = (id: string, start: number, length: number): SceneSlot =>
  ({ id, start, length, voiceStart: start, voiceSpeed: 1, overflow: false });
const slots = [slot("a", 0, 2), slot("b", 2, 2), slot("c", 4, 2)]; // midpoints 1, 3, 5

describe("timelineMath", () => {
  it("snap rounds to 0.1", () => {
    expect(snap(1.26)).toBe(1.3);
    expect(snap(0.04)).toBe(0);
    expect(snap(3.14159)).toBe(3.1);
  });
  it("converts between pixels and seconds", () => {
    expect(pxToTime(80, 40)).toBe(2);
    expect(timeToPx(2, 40)).toBe(80);
  });
  it("dragEdgeLength clamps at 0.5", () => {
    expect(dragEdgeLength(1, -400, 40, true)).toBe(0.5);
    expect(dragEdgeLength(5, 45, 40, true)).toBe(6.1);
    expect(dragEdgeLength(5, 45, 40, false)).toBeCloseTo(6.125, 6);
  });
  it("reorderIndex picks next slot", () => {
    expect(reorderIndex(slots, 0.5)).toBe(0);
    expect(reorderIndex(slots, 2.5)).toBe(1);
    expect(reorderIndex(slots, 99)).toBe(3);
  });
  it("reorderIndex returns the final position when moving right by one", () => {
    // drag a (centre 1) to centre 4: lands after b -> final index 1
    expect(reorderIndex(slots, 4, "a")).toBe(1);
    // drag c left to centre 0.5 -> final index 0
    expect(reorderIndex(slots, 0.5, "c")).toBe(0);
    // drag a past everything -> last position
    expect(reorderIndex(slots, 99, "a")).toBe(2);
  });
});

describe("trackDrag", () => {
  afterEach(() => vi.restoreAllMocks());
  it("reports distance and shift, then stops listening", () => {
    const move = vi.fn();
    const end = vi.fn();
    trackDrag(new MouseEvent("pointerdown", { clientX: 10 }), move, end);
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 30, shiftKey: true }));
    window.dispatchEvent(new MouseEvent("pointerup", { clientX: 50 }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 90 }));
    expect(move).toHaveBeenCalledTimes(1);
    expect(move).toHaveBeenCalledWith(20, true);
    expect(end).toHaveBeenCalledWith(40, false);
  });
});
