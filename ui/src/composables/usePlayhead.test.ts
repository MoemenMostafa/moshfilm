import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { usePlayhead } from "./usePlayhead";

let now = 0;
let queue: Array<(t: number) => void> = [];
function frame(ms: number): void {
  now += ms;
  const run = queue;
  queue = [];
  run.forEach((cb) => cb(now));
}

beforeEach(() => {
  now = 1000;
  queue = [];
  vi.stubGlobal("requestAnimationFrame", (cb: (t: number) => void) => queue.push(cb));
  vi.stubGlobal("cancelAnimationFrame", () => { queue = []; });
  vi.spyOn(performance, "now").mockImplementation(() => now);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("usePlayhead", () => {
  it("advances by real elapsed time and stops at the end", () => {
    const p = usePlayhead(ref(1));
    p.play();
    expect(p.playing.value).toBe(true);
    frame(400);
    expect(p.time.value).toBeCloseTo(0.4, 5);
    frame(400);
    expect(p.time.value).toBeCloseTo(0.8, 5);
    frame(400);
    expect(p.time.value).toBe(1);
    expect(p.playing.value).toBe(false);
    expect(queue.length).toBe(0);
  });

  it("seek clamps to [0, duration]", () => {
    const p = usePlayhead(ref(5));
    p.seek(-3);
    expect(p.time.value).toBe(0);
    p.seek(99);
    expect(p.time.value).toBe(5);
    p.seek(2.5);
    expect(p.time.value).toBe(2.5);
  });

  it("toggle pauses and play from the end restarts", () => {
    const p = usePlayhead(ref(2));
    p.toggle();
    frame(500);
    p.toggle();
    expect(p.playing.value).toBe(false);
    frame(500);
    expect(p.time.value).toBeCloseTo(0.5, 5);
    p.seek(2);
    p.play();
    expect(p.time.value).toBe(0);
    expect(p.playing.value).toBe(true);
  });

  it("clamps the time when the duration shrinks", () => {
    const d = ref(10);
    const p = usePlayhead(d);
    p.seek(8);
    d.value = 4;
    return Promise.resolve().then(() => expect(p.time.value).toBe(4));
  });
});
