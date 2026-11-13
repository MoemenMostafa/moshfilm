import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { Film } from "./types";

const handlers: Record<string, (d: any) => void> = {};
const reloadScene = vi.fn(async () => {});
vi.mock("./events", () => ({
  subscribe: vi.fn((h: Record<string, (d: any) => void>) => { Object.assign(handlers, h); return () => {}; }),
}));
vi.mock("./runtime/player", () => ({
  createPlayer: vi.fn(() => ({
    load: vi.fn(async () => {}), seek: vi.fn(), update: vi.fn(async () => {}),
    reloadScene, destroy: vi.fn(), duration: 2, slots: [], errors: [],
  })),
}));
vi.mock("./api", async (orig) => {
  const real = await orig<typeof import("./api")>();
  return { ...real, getFilm: vi.fn(), getVoice: vi.fn(), getProposals: vi.fn(), getQueue: vi.fn(), edit: vi.fn(), getHistory: vi.fn(), undo: vi.fn(), redo: vi.fn() };
});
import * as api from "./api";
import App from "./App.vue";

const film: Film = { version: 1, title: "t", width: 1280, height: 720, fps: 30, pace: 1, order_pinned: false,
  voice: { name: "v", rate: "+0%" }, music: null, texts: [],
  scenes: [{ id: "red", title: "Red", file: "scenes/red.js", length: 2, pinned: true, status: "ready",
    voice: { text: "", offset: 0.3, pinned: false } }] };

beforeEach(() => {
  vi.mocked(api.getFilm).mockResolvedValue({ film, folder: "/f" });
  vi.mocked(api.getVoice).mockResolvedValue({});
  vi.mocked(api.getProposals).mockResolvedValue({ proposals: [] });
  vi.mocked(api.getQueue).mockResolvedValue({ items: [], messages: [], status: null, connected: false });
});

describe("App", () => {
  it("renders preview, panel and timeline regions", async () => {
    const w = mount(App);
    await flushPromises();
    expect(w.find('[data-region="preview"]').exists()).toBe(true);
    expect(w.find('[data-region="panel"]').exists()).toBe(true);
    expect(w.find('[data-region="timeline"]').exists()).toBe(true);
    expect(w.find('[data-region="banner"]').exists()).toBe(false);
  });

  it("has the shape settings and Export movie in the top bar, once", async () => {
    const w = mount(App);
    await flushPromises();
    const top = w.get('[data-region="top"]');
    expect(top.find("[data-aspect-main]").exists()).toBe(true);
    expect(top.find("[data-aspect-second]").exists()).toBe(true);
    expect(top.find("[data-export-button]").exists()).toBe(true);
    expect(w.findAll("[data-aspect-main]")).toHaveLength(1);
  });

  it("shows banner on 409", async () => {
    vi.mocked(api.getFilm).mockRejectedValue(new api.ApiError(409, "film.json is broken: line 3"));
    const w = mount(App);
    await flushPromises();
    const banner = w.find('[data-region="banner"]');
    expect(banner.exists()).toBe(true);
    expect(banner.text()).toContain("film.json is broken: line 3");
  });

  it("reloads a scene when the server reports its file changed", async () => {
    const w = mount(App);
    await flushPromises();
    reloadScene.mockClear();
    handlers.scene({ file: "scenes/red.js", version: 777 });
    await flushPromises();
    expect(reloadScene).toHaveBeenCalledWith("red", 777);
    w.unmount();
  });

  it("arrow keys step the playhead even when the Play button has focus", async () => {
    const w = mount(App, { attachTo: document.body });
    await flushPromises();
    const play = w.find("button.play");
    (play.element as HTMLButtonElement).focus();
    await play.trigger("keydown", { key: "ArrowRight" });
    expect(w.find(".readout").text()).toContain("0:01.0 /");
    await play.trigger("keydown", { key: " " }); // Space on a button is the button's own click, not ours
    expect(w.find(".readout").text()).toContain("0:01.0 /");
    w.unmount();
  });

  it("Space and arrows in the composer do not toggle play or seek", async () => {
    const w = mount(App, { attachTo: document.body });
    await flushPromises();
    const ta = w.get('[data-region="panel"] textarea');
    (ta.element as HTMLTextAreaElement).focus();
    await ta.trigger("keydown", { key: " " });
    await ta.trigger("keydown", { key: "ArrowRight" });
    expect(w.find("button.play").attributes("aria-label")).toBe("Play");
    expect(w.find(".readout").text()).toContain("0:00.0 /");
    w.unmount();
  });

  it("Ctrl+Z undoes and Ctrl+Shift+Z redoes, but not while typing in the chat box", async () => {
    vi.mocked(api.getHistory).mockResolvedValue({ steps: [], cursor: -1, can_undo: false, can_redo: false });
    const reply = { steps: [], cursor: 0, can_undo: false, can_redo: true, film, changed: true };
    vi.mocked(api.undo).mockResolvedValue(reply);
    vi.mocked(api.redo).mockResolvedValue(reply);
    const w = mount(App, { attachTo: document.body });
    await flushPromises();
    const press = (target: Element, init: KeyboardEventInit) =>
      target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
    press(document.body, { key: "z", ctrlKey: true });
    press(document.body, { key: "z", ctrlKey: true, shiftKey: true });
    expect(api.undo).toHaveBeenCalledTimes(1);
    expect(api.redo).toHaveBeenCalledTimes(1);
    const ta = w.get('[data-region="panel"] textarea').element;
    press(ta, { key: "z", ctrlKey: true });
    press(ta, { key: "Delete" });
    expect(api.undo).toHaveBeenCalledTimes(1);
    w.unmount();
  });
});
