import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import type { QueueItem, QueueSnapshot } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import { PlayheadKey } from "../composables/usePlayhead";
import { aspectViewState } from "../composables/useAspectView";

vi.mock("../api", () => ({ postComment: vi.fn(async () => ({})) }));
import * as api from "../api";
import CommentLayer from "./CommentLayer.vue";

const item = (id: string, time: number, state: QueueItem["state"], point = { x: 0.25, y: 0.5 }): QueueItem =>
  ({ id, kind: "comment", text: `text ${id}`, created: "", state, time, scene: null, scene_time: null, point,
    attachment: null, delivered_at: null, resolved_at: null });

function setup(items: QueueItem[] = [], time = 1.5, active = true, film: unknown = null) {
  const queue = ref<QueueSnapshot>({ items, messages: [
    { id: "m1", role: "claude", text: "fixed it", reply_to: "c3", created: "" }], status: null, connected: true });
  const refreshQueue = vi.fn(async () => {});
  const store = { queue, refreshQueue, film: ref(film) } as unknown as FilmStore;
  const pause = vi.fn();
  const head = { time: ref(time), playing: ref(true), play: vi.fn(), pause, toggle: vi.fn(), seek: vi.fn() };
  const w = mount(CommentLayer, { props: { active }, attachTo: document.body,
    global: { provide: { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head } } });
  // jsdom has no layout: give the layer a 400x200 box at (100, 50)
  (w.get('[data-testid="comment-layer"]').element as HTMLElement).getBoundingClientRect =
    () => ({ left: 100, top: 50, width: 400, height: 200 }) as DOMRect;
  return { w, pause, refreshQueue };
}
const click = (w: ReturnType<typeof setup>["w"], x: number, y: number) =>
  w.get('[data-testid="comment-layer"]').trigger("click", { clientX: x, clientY: y });

describe("CommentLayer", () => {
  beforeEach(() => { document.body.replaceChildren(); vi.mocked(api.postComment).mockClear(); });

  it("click in comment mode opens popover and posts with time and point", async () => {
    const { w, pause, refreshQueue } = setup();
    await click(w, 200, 150); // x = 100/400 = .25, y = 100/200 = .5
    expect(pause).toHaveBeenCalled();
    const box = w.get("textarea");
    await box.setValue("make it bluer");
    await box.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(api.postComment).toHaveBeenCalledWith(1.5, { x: 0.25, y: 0.5 }, "make it bluer");
    expect(refreshQueue).toHaveBeenCalled();
    expect(w.emitted("done")).toBeTruthy();
    expect(w.find('[data-testid="popover"]').exists()).toBe(false);
  });

  it("Esc cancels without posting", async () => {
    const { w } = setup();
    await click(w, 200, 150);
    await w.get("textarea").setValue("never mind");
    await w.get("textarea").trigger("keydown", { key: "Escape" });
    expect(api.postComment).not.toHaveBeenCalled();
    expect(w.find('[data-testid="popover"]').exists()).toBe(false);
    expect(w.emitted("done")).toBeTruthy();
  });

  it("clicks do nothing when comment mode is off", async () => {
    const { w } = setup([], 1.5, false);
    await click(w, 200, 150);
    expect(w.find('[data-testid="popover"]').exists()).toBe(false);
  });

  it("draws pins near the playhead coloured by state, with Claude's reply on hover text", () => {
    const { w } = setup([item("c1", 1.4, "queued"), item("c2", 1.6, "delivered"), item("c3", 1.5, "resolved"),
      item("far", 9, "queued")]);
    expect(w.findAll("[data-pin]").map((p) => p.attributes("data-pin"))).toEqual(["c1", "c2", "c3"]);
    expect(w.get('[data-pin="c1"]').attributes("style")).toContain("left: 25%");
    expect(w.get('[data-pin="c1"]').classes()).toContain("queued");
    expect(w.get('[data-pin="c3"]').classes()).toContain("resolved");
    expect(w.get('[data-pin="c3"]').text()).toContain("fixed it");
  });
});


describe("CommentLayer shapes", () => {
  const two = { version: 2, title: "t", width: 1280, height: 720, aspect: "16:9", second_aspect: "9:16", fps: 30, pace: 1,
    order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null, scenes: [], texts: [] };

  beforeEach(() => { document.body.replaceChildren(); vi.mocked(api.postComment).mockClear(); aspectViewState.value = "main"; });

  it("posts the current shape with the comment", async () => {
    const { w } = setup([], 1.5, true, two);
    aspectViewState.value = "second";
    await click(w, 200, 150);
    const box = w.get("textarea");
    await box.setValue("narrower");
    await box.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(api.postComment).toHaveBeenCalledWith(1.5, { x: 0.25, y: 0.5 }, "narrower", "9:16");
  });

  it("hides pins made on the other shape", async () => {
    const mine = { ...item("c1", 1.5, "queued"), aspect: "9:16" as const };
    const old = item("c2", 1.5, "queued"); // no shape: made on the main one
    const { w } = setup([mine, old], 1.5, false, two);
    expect(w.findAll("[data-pin]").map((p) => p.attributes("data-pin"))).toEqual(["c2"]);
    aspectViewState.value = "second";
    await w.vm.$nextTick();
    expect(w.findAll("[data-pin]").map((p) => p.attributes("data-pin"))).toEqual(["c1"]);
  });

  it("maps a click on a 9:16 frame to the right fraction and posts it with the shape", async () => {
    const { w } = setup([], 1.5, true, two);
    aspectViewState.value = "second";
    // the 9:16 frame is 281 x 500 at (100, 50)
    (w.get('[data-testid="comment-layer"]').element as HTMLElement).getBoundingClientRect =
      () => ({ left: 100, top: 50, width: 281, height: 500 }) as DOMRect;
    await click(w, 100 + 140.5, 50 + 125); // the middle, a quarter down
    const box = w.get("textarea");
    await box.setValue("here");
    await box.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(api.postComment).toHaveBeenCalledWith(1.5, { x: 0.5, y: 0.25 }, "here", "9:16");
  });
});
