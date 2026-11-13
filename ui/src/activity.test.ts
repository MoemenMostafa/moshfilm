import { beforeEach, describe, expect, it } from "vitest";
import type { Scene } from "./types";
import { atChip, fmtElapsed, fmtTime, loadFlag, saveFlag, turnElapsedMs, workedSummary } from "./activity";

const scenes = [{ id: "a", title: "Intro" }, { id: "b", title: "x" }, { id: "c", title: "Open the middle" }] as Scene[];

describe("fmtTime", () => {
  it("shows minutes, seconds and tenths", () => {
    expect(fmtTime(23.44)).toBe("0:23.4");
    expect(fmtTime(0)).toBe("0:00.0");
    expect(fmtTime(75.9)).toBe("1:15.9");
  });
});

describe("atChip", () => {
  it("shows time, zero-padded scene number and title", () => {
    expect(atChip({ time: 23.4, scene: "c", sceneTitle: "Open the middle" }, scenes)).toBe("⏸ 0:23.4 · 03 Open the middle");
  });
  it("falls back to the stored title, or only the time", () => {
    expect(atChip({ time: 2, scene: "gone", sceneTitle: "Old" }, scenes)).toBe("⏸ 0:02.0 · Old");
    expect(atChip({ time: 2, scene: null, sceneTitle: null }, scenes)).toBe("⏸ 0:02.0");
  });
});

describe("elapsed text", () => {
  it("formats seconds and minutes", () => {
    expect(fmtElapsed(9_400)).toBe("9s");
    expect(fmtElapsed(72_000)).toBe("1m 12s");
    expect(fmtElapsed(-5)).toBe("0s");
  });
  it("summarises an ended turn", () => {
    const turn = { id: "t", started: "2026-01-01T00:00:00.000Z", updated: "", ended: "2026-01-01T00:01:12.000Z",
      item: null, steps: Array.from({ length: 6 }, (_, i) => ({ id: i, label: "x", state: "done" as const, started: "", ended: "" })) };
    expect(workedSummary(turn)).toBe("Worked 1m 12s · 6 steps");
    expect(workedSummary({ ...turn, steps: turn.steps.slice(0, 1) })).toBe("Worked 1m 12s · 1 step");
  });
  it("measures a running turn against now", () => {
    const turn = { id: "t", started: "2026-01-01T00:00:00.000Z", updated: "", ended: null, item: null, steps: [] };
    expect(turnElapsedMs(turn, Date.parse("2026-01-01T00:00:30.000Z"))).toBe(30_000);
  });
});

describe("flags in localStorage", () => {
  beforeEach(() => localStorage.clear());
  it("uses the default until saved, per key", () => {
    expect(loadFlag("k1", false)).toBe(false);
    expect(loadFlag("k1", true)).toBe(true);
    saveFlag("k1", true);
    expect(loadFlag("k1", false)).toBe(true);
    expect(loadFlag("k2", false)).toBe(false);
  });
  it("survives a storage that throws", () => {
    const real = Storage.prototype.getItem;
    const set = Storage.prototype.setItem;
    Storage.prototype.getItem = () => { throw new Error("blocked"); };
    Storage.prototype.setItem = () => { throw new Error("blocked"); };
    try {
      expect(loadFlag("k", true)).toBe(true);
      expect(() => saveFlag("k", false)).not.toThrow();
    } finally {
      Storage.prototype.getItem = real;
      Storage.prototype.setItem = set;
    }
  });
});
