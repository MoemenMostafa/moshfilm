import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import type { ExportStatus, Film } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, getExport: vi.fn(), startExport: vi.fn(), revealExport: vi.fn(async () => ({ ok: true })) };
});
import * as api from "../api";
import ExportMenu from "./ExportMenu.vue";

const st = (over: Partial<ExportStatus> = {}): ExportStatus => ({ state: "idle", format: null, files: [], warnings: [],
  current: null, error: null, started_at: null, finished_at: null, ...over });
const film = { aspect: "16:9", second_aspect: "9:16", width: 1280, height: 720 } as unknown as Film;

function mountIt() {
  const store = { film: ref(film) } as unknown as FilmStore;
  return mount(ExportMenu, { attachTo: document.body, global: { provide: { [FilmKey as symbol]: store } } });
}
const openMenu = async (w: ReturnType<typeof mountIt>) => { await w.get("[data-export-button]").trigger("click"); };

describe("ExportMenu", () => {
  beforeEach(() => { vi.mocked(api.getExport).mockResolvedValue(st()); vi.mocked(api.startExport).mockReset(); });
  afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });

  it("opens a menu with MP4 selected, GIF as the other choice", async () => {
    const w = mountIt();
    await flushPromises();
    expect(w.find("[data-export-panel]").exists()).toBe(false);
    await openMenu(w);
    expect((w.get('[data-export-format="mp4"]').element as HTMLInputElement).checked).toBe(true);
    expect(w.find('[data-export-format="gif"]').exists()).toBe(true);
    expect(w.text()).toContain("16:9 and 9:16");
  });

  it("Export starts the chosen format", async () => {
    vi.mocked(api.startExport).mockResolvedValue(st({ state: "running", format: "gif" }));
    const w = mountIt();
    await openMenu(w);
    await w.get('[data-export-format="gif"]').setValue(true);
    await w.get("[data-export-start]").trigger("click");
    await flushPromises();
    expect(api.startExport).toHaveBeenCalledWith("gif");
  });

  it("running: spinner text names the shape, the buttons are disabled, and it polls until done", async () => {
    vi.useFakeTimers();
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", format: "mp4", current: "16:9" }));
    const w = mountIt();
    await flushPromises();
    expect(w.get("[data-export-button]").attributes("disabled")).toBeUndefined(); // the menu can be reopened
    expect(w.find('[data-export-dot="running"]').exists()).toBe(true);
    // the server finishes: the next poll shows it
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "done", format: "mp4",
      files: [{ name: "t-16x9.mp4", aspect: "16:9", bytes: 2_500_000 }] }));
    await vi.advanceTimersByTimeAsync(1100);
    await flushPromises();
    expect(w.find('[data-export-dot="done"]').exists()).toBe(true);
    // the result opened by itself (the menu was closed when the export finished)
    expect(w.find("[data-export-panel]").exists()).toBe(true);
    expect(w.get("[data-export-link]").attributes("href")).toBe("/api/export/file/t-16x9.mp4");
    expect(w.text()).toContain("2.5 MB");
  });

  it("shows 'Exporting 16:9…' while running", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "idle" }));
    vi.mocked(api.startExport).mockResolvedValue(st({ state: "running", format: "mp4", current: "16:9" }));
    const w = mountIt();
    await openMenu(w);
    await w.get("[data-export-start]").trigger("click");
    await flushPromises();
    expect(w.get("[data-export-running]").text()).toContain("Exporting 16:9…");
    expect(w.get("[data-export-start]").attributes("disabled")).toBeDefined();
  });

  it("done: one link per file, warnings as text, Show in folder", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "done", format: "mp4", warnings: ["wide: [9:16] sticks out"],
      files: [{ name: "t-16x9.mp4", aspect: "16:9", bytes: 900 }, { name: "t-9x16.mp4", aspect: "9:16", bytes: 900 }] }));
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    expect(w.findAll("[data-export-link]").map((a) => a.text())).toEqual(["t-16x9.mp4", "t-9x16.mp4"]);
    expect(w.get("[data-export-warnings]").text()).toContain("wide: [9:16] sticks out");
    await w.findAll("[data-export-reveal]")[1].trigger("click");
    expect(api.revealExport).toHaveBeenCalledWith("t-9x16.mp4");
  });

  it("an error shows its message; a 409 from the server shows too", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "error", error: 'scenes not ready: "Two"' }));
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    expect(w.get("[data-export-error]").text()).toContain("scenes not ready");
    vi.mocked(api.startExport).mockRejectedValue(new api.ApiError(409, "an export is already running"));
    await w.get("[data-export-start]").trigger("click");
    await flushPromises();
    expect(w.text()).toContain("an export is already running");
  });

  it("while running the toggle stays usable and only Export is disabled", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", format: "mp4", current: "16:9" }));
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    expect(w.find("[data-export-panel]").exists()).toBe(true);
    expect(w.get("[data-export-start]").attributes("disabled")).toBeDefined();
    await openMenu(w);
    expect(w.find("[data-export-panel]").exists()).toBe(false);
  });

  it("a failed export opens the panel with a red dot", async () => {
    vi.useFakeTimers();
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", format: "mp4" }));
    const w = mountIt();
    await flushPromises();
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "error", error: "ffmpeg failed" }));
    await vi.advanceTimersByTimeAsync(1100);
    await flushPromises();
    expect(w.find('[data-export-dot="error"]').exists()).toBe(true);
    expect(w.get("[data-export-error]").text()).toContain("ffmpeg failed");
  });

  it("a 409 on Export picks up the export that is already running", async () => {
    vi.useFakeTimers();
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    vi.mocked(api.startExport).mockRejectedValue(new api.ApiError(409, "an export is already running"));
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", format: "gif", current: "16:9" }));
    await w.get("[data-export-start]").trigger("click");
    await flushPromises();
    expect(w.get("[data-export-running]").text()).toContain("Exporting 16:9…");
    expect(w.get("[data-export-start]").attributes("disabled")).toBeDefined();
    const calls = vi.mocked(api.getExport).mock.calls.length;
    await vi.advanceTimersByTimeAsync(2100); // polling started
    expect(vi.mocked(api.getExport).mock.calls.length).toBeGreaterThan(calls);
  });

  const prog = (over: Partial<NonNullable<ExportStatus["progress"]>> = {}) => ({ stage: "frames" as const, aspect: "16:9" as const,
    aspect_index: 0, aspect_count: 2, done: 412, total: 1380, percent: 30.4, eta_seconds: 120, ...over });

  it("running: the bar, the line and the toggle % come from the status payload", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", format: "mp4", current: "16:9", progress: prog() }));
    const w = mountIt();
    await flushPromises();
    expect(w.get("[data-export-button] [data-export-percent]").text()).toBe("30%"); // visible with the menu closed
    await openMenu(w);
    const bar = w.get("[data-export-bar]");
    expect(bar.attributes("aria-valuenow")).toBe("30");
    expect(w.get("[data-export-bar-fill]").attributes("style")).toContain("width: 30%");
    expect(w.get("[data-export-running]").text()).toBe("16:9 · frames 412 / 1 380 · about 2 min left");
    expect(w.get("[data-export-percent-text]").text()).toContain("30%");
    expect(w.find('[data-export-dot="running"]').exists()).toBe(true);
  });

  it("running: audio and encode stages have their own lines, no estimate yet leaves it out", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", progress: prog({ stage: "audio", aspect: null, percent: 1 }) }));
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    expect(w.get("[data-export-running]").text()).toBe("Building audio…");
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", progress: prog({ stage: "encode", aspect: "9:16", percent: 96 }) }));
    vi.useFakeTimers();
    w.unmount();
    const w2 = mountIt();
    await flushPromises();
    await openMenu(w2);
    expect(w2.get("[data-export-running]").text()).toBe("Encoding 9:16…");
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", progress: prog({ eta_seconds: null }) }));
    await vi.advanceTimersByTimeAsync(1100);
    await flushPromises();
    expect(w2.get("[data-export-running]").text()).toBe("16:9 · frames 412 / 1 380");
  });

  it("running without progress (older server, or before the first report) keeps the plain text and no bar", async () => {
    vi.mocked(api.getExport).mockResolvedValue(st({ state: "running", current: "16:9" }));
    const w = mountIt();
    await flushPromises();
    await openMenu(w);
    expect(w.get("[data-export-running]").text()).toContain("Exporting 16:9…");
    expect(w.find("[data-export-bar]").exists()).toBe(false);
    expect(w.find("[data-export-percent]").exists()).toBe(false);
  });
});
