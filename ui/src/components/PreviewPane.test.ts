import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import { flushPromises } from "@vue/test-utils";
import { aspectViewState } from "../composables/useAspectView";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import { createFollow, FollowKey } from "../composables/useFollow";
import { PlayheadKey } from "../composables/usePlayhead";
import PreviewPane from "./PreviewPane.vue";

const SLOTS = [0, 7, 12, 20].map((start, i) => ({ id: `s${i}`, start, length: [7, 5, 8, 7][i], voiceStart: start, voiceSpeed: 1, overflow: false }));

function mountPane(withFollow: boolean, slots: unknown[] = []) {
  const store = { film: ref(null), folder: ref("/f"), voiceDurations: ref({}), sceneVersions: ref({}), slots: ref(slots),
    activity: ref({ turn: null, plan: [] }), queue: ref({ items: [], messages: [], status: null, connected: false }) } as unknown as FilmStore;
  const head = { time: ref(0), playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek: vi.fn() };
  const follow = createFollow(store as any, head as any);
  const provide: Record<symbol, unknown> = { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head };
  if (withFollow) provide[FollowKey as symbol] = follow;
  const w = mount(PreviewPane, { attachTo: document.body, global: { provide, stubs: { CommentLayer: true } } });
  return Object.assign(w, { head });
}

describe("PreviewPane follow toggle", () => {
  it("shows Follow Claude, on by default, and toggles it", async () => {
    localStorage.clear();
    const w = mountPane(true);
    const btn = w.get('[data-testid="follow-btn"]');
    expect(btn.attributes("aria-pressed")).toBe("true");
    await btn.trigger("click");
    expect(btn.attributes("aria-pressed")).toBe("false");
  });

  it("has no toggle when no follow is provided", () => {
    expect(mountPane(false).find('[data-testid="follow-btn"]').exists()).toBe(false);
  });
});

function press(target: EventTarget, init: KeyboardEventInit): void {
  target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
}

describe("PreviewPane transport", () => {
  it("Space plays and pauses from the page, but not while typing or on a focused button", () => {
    const w = mountPane(false);
    press(document.body, { key: " " });
    expect(w.head.toggle).toHaveBeenCalledTimes(1);
    const ta = document.createElement("textarea");
    document.body.appendChild(ta);
    press(ta, { key: " " });
    const btn = w.get('[data-testid="comment-btn"]').element;
    press(btn, { key: " " });
    expect(w.head.toggle).toHaveBeenCalledTimes(1);
    ta.remove();
    w.unmount();
  });

  it("the play button is an icon button that names its shortcut", () => {
    const w = mountPane(false);
    const play = w.get("button.play");
    expect(play.attributes("aria-label")).toBe("Play");
    expect(play.attributes("title")).toContain("Space");
    expect(play.text()).toBe("");
    w.unmount();
  });

  it("draws a seam at every scene start except the first", () => {
    const w = mountPane(false, SLOTS);
    const seams = w.findAll('[data-testid="seam"]');
    expect(seams).toHaveLength(3);
    expect(seams[0].attributes("style")).toContain("left: 25.92"); // 7s of 27s
    w.unmount();
  });

  it("next and previous scene seek to scene starts", async () => {
    const w = mountPane(false, SLOTS);
    w.head.time.value = 8;
    await w.get('[data-testid="next-scene"]').trigger("click");
    expect(w.head.seek).toHaveBeenLastCalledWith(12);
    await w.get('[data-testid="prev-scene"]').trigger("click"); // 8s is 1s into scene 2: restart it
    expect(w.head.seek).toHaveBeenLastCalledWith(7);
    w.head.time.value = 7.2;
    await w.get('[data-testid="prev-scene"]').trigger("click"); // at the start: step back
    expect(w.head.seek).toHaveBeenLastCalledWith(0);
    w.head.time.value = 25;
    await w.get('[data-testid="next-scene"]').trigger("click"); // last scene: jump to the end
    expect(w.head.seek).toHaveBeenLastCalledWith(27);
    w.unmount();
  });

  it("only the preview's own scrub bar lets keys through: zoom and pace sliders keep Space", () => {
    const w = mountPane(false);
    const other = document.createElement("input");
    other.type = "range";
    document.body.appendChild(other);
    press(other, { key: " " });
    press(other, { key: "ArrowRight" });
    expect(w.head.toggle).not.toHaveBeenCalled();
    expect(w.head.seek).not.toHaveBeenCalled();
    press(w.get("input.scrub").element, { key: " " });
    expect(w.head.toggle).toHaveBeenCalledTimes(1);
    other.remove();
    w.unmount();
  });
});

describe("PreviewPane shapes", () => {
  const filmWith = (second: string | null) => ({ version: 2, title: "t", width: 1280, height: 720, aspect: "16:9",
    second_aspect: second, fps: 30, pace: 1, order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null,
    scenes: [], texts: [] });

  function mountWith(second: string | null) {
    const film = ref<any>(filmWith(second));
    const store = { film, folder: ref("/f"), voiceDurations: ref({}), sceneVersions: ref({}), slots: ref([]),
      activity: ref({ turn: null, plan: [] }), queue: ref({ items: [], messages: [], status: null, connected: false }) } as unknown as FilmStore;
    const head = { time: ref(0), playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek: vi.fn() };
    const w = mount(PreviewPane, { attachTo: document.body, global: {
      provide: { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head }, stubs: { CommentLayer: true } } });
    return { w, film };
  }
  function sizePane(w: ReturnType<typeof mount>) {
    const fit = w.get(".fit").element;
    Object.defineProperty(fit, "clientWidth", { value: 1000, configurable: true });
    Object.defineProperty(fit, "clientHeight", { value: 500, configurable: true });
  }

  it("no switch without a second shape", () => {
    const { w } = mountWith(null);
    expect(w.find('[data-testid="aspect-switch"]').exists()).toBe(false);
    w.unmount();
  });

  it("switch shows both shapes and sizes the frame for 9:16", async () => {
    aspectViewState.value = "main";
    const { w } = mountWith("9:16");
    sizePane(w);
    const sw = w.get('[data-testid="aspect-switch"]');
    expect(sw.findAll("[data-aspect-view]").map((b) => b.text())).toEqual(["16:9", "9:16"]);
    await w.get('[data-aspect-view="second"]').trigger("click");
    await flushPromises();
    expect(w.get('[data-aspect-view="second"]').attributes("aria-pressed")).toBe("true");
    expect(w.get('[data-aspect-view="main"]').attributes("aria-pressed")).toBe("false");
    const frame = w.get(".frame").attributes("style");
    expect(frame).toContain("width: 281px");
    expect(frame).toContain("height: 500px");
    aspectViewState.value = "main";
    w.unmount();
  });
});
