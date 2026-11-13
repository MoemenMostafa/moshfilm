import { describe, expect, it } from "vitest";
import { toNormalizedPoint, visiblePins } from "./comments";
import type { QueueItem } from "./types";

const rect = { left: 100, top: 50, width: 400, height: 200 } as DOMRect;
const item = (id: string, time: number | null, kind: QueueItem["kind"] = "comment"): QueueItem =>
  ({ id, kind, text: id, created: "", state: "queued", time, scene: null, scene_time: null, point: null,
    attachment: null, delivered_at: null, resolved_at: null });

describe("toNormalizedPoint", () => {
  it("maps corners and clamps", () => {
    expect(toNormalizedPoint(100, 50, rect)).toEqual({ x: 0, y: 0 });
    expect(toNormalizedPoint(500, 250, rect)).toEqual({ x: 1, y: 1 });
    expect(toNormalizedPoint(0, 9999, rect)).toEqual({ x: 0, y: 1 });
    expect(toNormalizedPoint(133, 130, rect)).toEqual({ x: 0.08, y: 0.4 });
  });
});

describe("visiblePins", () => {
  it("uses the window", () => {
    const items = [item("a", 1.0), item("b", 1.5), item("c", 1.6), item("chat", null, "chat"), item("n", null)];
    expect(visiblePins(items, 1.0).map((i) => i.id)).toEqual(["a", "b"]);
    expect(visiblePins(items, 1.6, 0.2).map((i) => i.id)).toEqual(["b", "c"]);
    expect(visiblePins(items, 1.0).every((i) => i.kind === "comment")).toBe(true);
  });
});

describe("visiblePins by shape", () => {
  it("filters by shape, old comments count as main", () => {
    const items = [item("old", 1), { ...item("m", 1), aspect: "16:9" as const }, { ...item("s", 1), aspect: "9:16" as const }];
    expect(visiblePins(items, 1, 0.5, { aspect: "16:9", main: "16:9" }).map((i) => i.id)).toEqual(["old", "m"]);
    expect(visiblePins(items, 1, 0.5, { aspect: "9:16", main: "16:9" }).map((i) => i.id)).toEqual(["s"]);
    expect(visiblePins(items, 1).map((i) => i.id)).toEqual(["old", "m", "s"]);
  });
});
