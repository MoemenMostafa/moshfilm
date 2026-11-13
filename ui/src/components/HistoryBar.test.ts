import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { mount } from "@vue/test-utils";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import type { HistoryInfo } from "../types";
import HistoryBar from "./HistoryBar.vue";

const info = (over: Partial<HistoryInfo> = {}): HistoryInfo => ({
  cursor: 2, can_undo: true, can_redo: true,
  steps: [
    { id: 1, label: "Start", kind: "base", time: "2026-11-11T10:00:00.000+00:00", current: false, future: false },
    { id: 2, label: "Changed length of scene 01", kind: "person", time: "2026-11-11T10:01:00.000+00:00", current: false, future: false },
    { id: 3, label: "Claude: edited scene 03", kind: "claude", time: "2026-11-11T10:02:00.000+00:00", current: true, future: false },
    { id: 4, label: "Removed scene 02 \"Middle\"", kind: "person", time: "2026-11-11T10:03:00.000+00:00", current: false, future: true },
  ], ...over });

function mountIt(h = info()) {
  const store = { history: ref(h), undo: vi.fn(async () => {}), redo: vi.fn(async () => {}),
    jumpHistory: vi.fn(async () => {}) } as unknown as FilmStore;
  const w = mount(HistoryBar, { global: { provide: { [FilmKey as symbol]: store } }, attachTo: document.body });
  return { w, store };
}

describe("HistoryBar", () => {
  it("undo and redo buttons call the store and follow can_undo / can_redo", async () => {
    const { w, store } = mountIt();
    await w.get("[data-undo]").trigger("click");
    await w.get("[data-redo]").trigger("click");
    expect(store.undo).toHaveBeenCalledTimes(1);
    expect(store.redo).toHaveBeenCalledTimes(1);
    w.unmount();
    const off = mountIt(info({ can_undo: false, can_redo: false }));
    expect(off.w.get("[data-undo]").attributes("disabled")).toBeDefined();
    expect(off.w.get("[data-redo]").attributes("disabled")).toBeDefined();
    off.w.unmount();
  });

  it("the popover is closed at first and lists the steps, newest first, with labels", async () => {
    const { w } = mountIt();
    expect(w.find("[data-history-list]").exists()).toBe(false);
    await w.get("[data-history-toggle]").trigger("click");
    const rows = w.findAll("[data-step]");
    expect(rows.map((r) => r.attributes("data-step"))).toEqual(["4", "3", "2", "1"]);
    expect(rows[0].text()).toContain('Removed scene 02 "Middle"');
    expect(rows[1].text()).toContain("Claude: edited scene 03");
    expect(rows[1].classes()).toContain("current");
    expect(rows[0].classes()).toContain("future");
    w.unmount();
  });

  it("clicking a step jumps to that point and closes the popover", async () => {
    const { w, store } = mountIt();
    await w.get("[data-history-toggle]").trigger("click");
    await w.get('[data-step="2"]').trigger("click");
    expect(store.jumpHistory).toHaveBeenCalledWith(2);
    expect(w.find("[data-history-list]").exists()).toBe(false);
    w.unmount();
  });

  it("Esc and a click elsewhere close it; an empty history says so", async () => {
    const { w } = mountIt();
    await w.get("[data-history-toggle]").trigger("click");
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await w.vm.$nextTick();
    expect(w.find("[data-history-list]").exists()).toBe(false);
    await w.get("[data-history-toggle]").trigger("click");
    document.body.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true }));
    await w.vm.$nextTick();
    expect(w.find("[data-history-list]").exists()).toBe(false);
    w.unmount();
    const empty = mountIt(info({ steps: [], cursor: -1, can_undo: false, can_redo: false }));
    await empty.w.get("[data-history-toggle]").trigger("click");
    expect(empty.w.get("[data-history-list]").text()).toContain("Nothing to undo yet");
    empty.w.unmount();
  });
});
