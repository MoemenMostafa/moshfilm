import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";
import type { Activity, ActivityStep } from "../types";
import { createFollow } from "./useFollow";

const iso = (offsetMs = 0) => new Date(Date.now() + offsetMs).toISOString();
const slots = [{ id: "s1", start: 0, length: 5 }, { id: "s2", start: 5, length: 4 }, { id: "s3", start: 9, length: 6 }];

function setup(folder = "/f") {
  const activity = ref<Activity>({ turn: null, plan: [] });
  const sceneVersions = ref<Record<string, number>>({});
  const store = { folder: ref(folder), activity, sceneVersions, slots: ref(slots) } as any;
  const time = ref(0);
  const playing = ref(false);
  const head = {
    time, playing,
    seek: vi.fn((t: number) => { time.value = t; }),
    play: vi.fn(() => { playing.value = true; }),
    pause: vi.fn(() => { playing.value = false; }),
    toggle: vi.fn(),
  };
  const follow = createFollow(store, head as any);
  let id = 0;
  const steps: ActivityStep[] = [];
  const publish = (turnId = "t1", ended: string | null = null) => {
    activity.value = { plan: [], turn: { id: turnId, started: iso(), updated: iso(), ended, item: null, steps: steps.map((s) => ({ ...s })) } };
  };
  const addStep = (scene: string | undefined, action: "read" | "edit" | undefined, startedOffset = 0) => {
    const step: ActivityStep = { id: ++id, label: "x", state: "running", started: iso(startedOffset), ended: null, scene, action };
    steps.push(step);
    publish();
    return step;
  };
  const finish = (step: ActivityStep, state: "done" | "failed" = "done") => {
    steps.find((s) => s.id === step.id)!.state = state;
    publish();
  };
  const reload = (scene: string, v: number) => { sceneVersions.value = { ...sceneVersions.value, [scene]: v }; };
  return { follow, head, time, playing, addStep, finish, reload };
}

beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); vi.setSystemTime(new Date("2026-01-01T00:00:00Z")); });
afterEach(() => vi.useRealTimers());

describe("Follow Claude toggle", () => {
  it("is on by default and remembered per film", async () => {
    const a = setup("/a");
    expect(a.follow.enabled.value).toBe(true);
    a.follow.toggle();
    expect(a.follow.enabled.value).toBe(false);
    expect(localStorage.getItem("moshfilm.followClaude:/a")).toBe("0");
    expect(setup("/a").follow.enabled.value).toBe(false);
    expect(setup("/b").follow.enabled.value).toBe(true);
  });

  it("works when localStorage throws", () => {
    const get = Storage.prototype.getItem, set = Storage.prototype.setItem;
    Storage.prototype.getItem = () => { throw new Error("blocked"); };
    Storage.prototype.setItem = () => { throw new Error("blocked"); };
    try {
      const s = setup();
      expect(s.follow.enabled.value).toBe(true);
      expect(() => s.follow.toggle()).not.toThrow();
    } finally { Storage.prototype.getItem = get; Storage.prototype.setItem = set; }
  });
});

describe("following a scene step", () => {
  it("jumps to the scene start when a step targets it", async () => {
    const s = setup();
    s.addStep("s2", "read");
    await nextTick();
    expect(s.head.seek).toHaveBeenCalledWith(5);
    expect(s.head.play).not.toHaveBeenCalled();
  });

  it("ignores steps without a scene and steps that began before the page opened", async () => {
    const s = setup();
    s.addStep(undefined, undefined);
    await nextTick();
    s.addStep("s3", "edit", -60_000); // history shown after a page reload
    await nextTick();
    expect(s.head.seek).not.toHaveBeenCalled();
  });

  it("after an edit completes and the scene reloads, plays that scene once from its start and stops at its end", async () => {
    const s = setup();
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.head.seek.mockClear();
    s.time.value = 7; // moved elsewhere meanwhile, but still idle... user did not touch it
    vi.advanceTimersByTime(10_000);
    s.finish(step);
    await nextTick();
    expect(s.head.play).not.toHaveBeenCalled(); // not reloaded yet
    s.reload("s2", 123);
    await nextTick();
    expect(s.head.seek).toHaveBeenCalledWith(5);
    expect(s.head.play).toHaveBeenCalledTimes(1);
    s.time.value = 8.99;
    await nextTick();
    expect(s.head.pause).not.toHaveBeenCalled();
    s.time.value = 9.0;
    await nextTick();
    expect(s.head.pause).toHaveBeenCalledTimes(1);
  });

  it("works when the reload arrives before the step completes", async () => {
    const s = setup();
    const step = s.addStep("s1", "edit");
    await nextTick();
    s.reload("s1", 5);
    await nextTick();
    expect(s.head.play).not.toHaveBeenCalled();
    s.finish(step);
    await nextTick();
    expect(s.head.play).toHaveBeenCalledTimes(1);
  });

  it("does not play after a failed edit or a read", async () => {
    const s = setup();
    const bad = s.addStep("s1", "edit");
    const read = s.addStep("s2", "read");
    await nextTick();
    s.finish(bad, "failed");
    s.finish(read);
    s.reload("s1", 1);
    s.reload("s2", 1);
    await nextTick();
    expect(s.head.play).not.toHaveBeenCalled();
  });
});

describe("never takes control", () => {
  it("does nothing when the toggle is off", async () => {
    const s = setup();
    s.follow.toggle();
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.finish(step);
    s.reload("s2", 1);
    await nextTick();
    expect(s.head.seek).not.toHaveBeenCalled();
    expect(s.head.play).not.toHaveBeenCalled();
  });

  it("does nothing while the preview is playing", async () => {
    const s = setup();
    s.playing.value = true;
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.finish(step);
    s.reload("s2", 1);
    await nextTick();
    expect(s.head.seek).not.toHaveBeenCalled();
    expect(s.head.play).not.toHaveBeenCalled();
  });

  it("does nothing right after the person scrubbed, and follows again once they stop", async () => {
    const s = setup();
    s.time.value = 3.3; // a scrub by the user (not one of our seeks)
    await nextTick();
    s.addStep("s2", "read");
    await nextTick();
    expect(s.head.seek).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5_000);
    s.addStep("s3", "read");
    await nextTick();
    expect(s.head.seek).toHaveBeenCalledWith(9);
  });

  it("our own seeks do not count as the user scrubbing", async () => {
    const s = setup();
    s.addStep("s2", "read");
    await nextTick();
    s.addStep("s3", "read");
    await nextTick();
    expect(s.head.seek.mock.calls.map((c) => c[0])).toEqual([5, 9]);
  });

  it("lets go when the person scrubs away during our play-through", async () => {
    const s = setup();
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.finish(step);
    s.reload("s2", 1);
    await nextTick();
    expect(s.head.play).toHaveBeenCalled();
    s.time.value = 1; // user drags the scrubber into another scene while it plays
    await nextTick();
    s.time.value = 2;
    await nextTick();
    s.time.value = 9.5;
    await nextTick();
    expect(s.head.pause).not.toHaveBeenCalled(); // we never pause what the user took over
  });

  it("The person pausing our play-through counts as a user move, so Follow stays still for a moment", async () => {
    const s = setup();
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.finish(step);
    s.reload("s2", 1);
    await nextTick();
    s.head.seek.mockClear();
    s.playing.value = false; // the user presses pause mid play-through
    await nextTick();
    s.addStep("s3", "read");
    await nextTick();
    expect(s.head.seek).not.toHaveBeenCalled();
  });

  it("our own auto-stop at the scene end does not count as a user move", async () => {
    const s = setup();
    const step = s.addStep("s2", "edit");
    await nextTick();
    s.finish(step);
    s.reload("s2", 1);
    await nextTick();
    s.time.value = 9;
    await nextTick();
    expect(s.head.pause).toHaveBeenCalledTimes(1);
    s.head.seek.mockClear();
    s.addStep("s3", "read");
    await nextTick();
    expect(s.head.seek).toHaveBeenCalledWith(9);
  });
});
