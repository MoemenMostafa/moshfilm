import { beforeEach, describe, expect, it, vi } from "vitest";
import { computed, nextTick, ref } from "vue";
import { mount } from "@vue/test-utils";
import type { Film, QueueItem } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import { PlayheadKey } from "../composables/usePlayhead";
import { layout, OVERFLOW_COPY } from "../runtime/timing";
import { createSelection } from "../composables/useSelection";
import * as api from "../api";
import Timeline from "./Timeline.vue";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, synthesizeVoice: vi.fn(async () => ({})) };
});

const scene = (id: string, length: number, pinned: boolean, text = "", status: "ready" | "planned" = "ready") =>
  ({ id, title: id.toUpperCase(), file: `scenes/${id}.js`, length, pinned, status,
    voice: { text, offset: 0, pinned: false } });

function makeFilm(): Film {
  return { version: 1, title: "t", width: 1280, height: 720, fps: 30, pace: 1.25, order_pinned: false,
    voice: { name: "v", rate: "+0%" }, music: null,
    scenes: [scene("s1", 5, true, "hello"), scene("s2", 4, true, "a long line"), scene("s3", 3, false, "never made", "planned")],
    texts: [{ id: "t1", scene: "s1", text: "Hi", start: 1, end: 3, pinned: true, style: "caption", x: null, y: null }] };
}

function mountTimeline(film = makeFilm(), voice: Record<string, number> = { s1: 2, s2: 9 }, items: QueueItem[] = []) {
  const f = ref(film);
  const focusItem = ref<string | null>(null);
  const edit = vi.fn(async () => {});
  const sel = createSelection(f, edit as never);
  const history = ref({ steps: [], cursor: -1, can_undo: false, can_redo: false });
  const store = { history, undo: vi.fn(), redo: vi.fn(), jumpHistory: vi.fn(),
    selection: sel.selection, pendingRemove: sel.pending, selectItem: sel.select, clearSelection: sel.clear,
    requestRemove: sel.requestRemove, confirmRemove: sel.confirm, cancelRemove: sel.cancel, queue: ref({ items, messages: [], status: null, connected: false }), focusItem, voiceStatus: ref(null), voice: ref({}), film: f, voiceDurations: ref(voice), slots: computed(() => layout(f.value, voice)), edit } as unknown as FilmStore;
  const seek = vi.fn();
  const head = { time: ref(0), playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek };
  const w = mount(Timeline, { attachTo: document.body, global: { provide: { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head } } });
  return { w, edit, seek, focusItem, sel };
}
const ptr = (type: string, clientX: number, extra: object = {}) =>
  new MouseEvent(type, { clientX, bubbles: true, ...extra });

const wheel = (deltaY: number) => new WheelEvent("wheel", { deltaY, ctrlKey: true, bubbles: true, cancelable: true });

describe("Timeline", () => {
  beforeEach(() => document.body.replaceChildren());

  it("dragging scene edge emits set_length with snapped value", () => {
    const { w, edit } = mountTimeline();
    const handle = w.get('[data-scene="s1"] [data-handle="edge"]').element;
    handle.dispatchEvent(ptr("pointerdown", 100));
    window.dispatchEvent(ptr("pointermove", 140));
    window.dispatchEvent(ptr("pointerup", 140)); // +40 px at 40 px/s = +1 s
    expect(edit).toHaveBeenCalledWith([{ op: "set_length", scene: "s1", length: 6 }]);
  });

  it("holding shift while dragging turns snapping off", () => {
    const { w, edit } = mountTimeline();
    w.get('[data-scene="s1"] [data-handle="edge"]').element.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 45, { shiftKey: true }));
    expect(edit).toHaveBeenCalledWith([{ op: "set_length", scene: "s1", length: 6.125 }]);
  });

  it("dragging a scene body right by one scene sends move_scene with the final index", () => {
    const { w, edit } = mountTimeline();
    // s1 is 5 s (200 px), s2 4 s. Moving s1 by +5 s puts its centre at 7.5 s: after s2 (mid 7) -> index 1.
    w.get('[data-scene="s1"]').element.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 200));
    expect(edit).toHaveBeenCalledWith([{ op: "move_scene", scene: "s1", index: 1 }]);
  });

  it("overflow scene shows exact copy", () => {
    const { w } = mountTimeline();
    const s2 = w.get('[data-scene="s2"]');
    expect(s2.classes()).toContain("overflow");
    expect(s2.text()).toContain("voice doesn't fit — stretch scene or shorten line");
    expect(s2.attributes("title")).toBe(OVERFLOW_COPY);
    expect(w.get('[data-scene="s1"]').text()).not.toContain("doesn't fit");
  });

  it("shows title and length, and marks planned scenes", () => {
    const { w } = mountTimeline();
    expect(w.get('[data-scene="s1"]').text()).toContain("5s");
    const s3 = w.get('[data-scene="s3"]');
    expect(s3.classes()).toContain("hatched");
    expect(s3.text()).toContain("planned");
  });

  it("pin icon click sends unpin", async () => {
    const { w, edit } = mountTimeline();
    await w.get('[data-scene="s1"] [data-pin]').trigger("click");
    expect(edit).toHaveBeenCalledWith([{ op: "unpin", target: "scene:s1" }]);
    expect(w.find('[data-scene="s3"] [data-pin]').exists()).toBe(false);
  });

  it("pace slider sends set_pace on release and labels the pace", async () => {
    const { w, edit } = mountTimeline();
    expect(w.get("[data-pace-label]").text()).toBe("Pace 1.25× (slower)");
    const slider = w.get('input[type="range"]');
    expect(slider.attributes("min")).toBe("0.75");
    expect(slider.attributes("max")).toBe("2");
    expect(slider.attributes("step")).toBe("0.05");
    (slider.element as HTMLInputElement).value = "1.5";
    await slider.trigger("input"); // dragging: only "input" fires until release
    expect(edit).not.toHaveBeenCalled();
    expect(w.get("[data-pace-label]").text()).toBe("Pace 1.5× (slower)");
    await slider.trigger("change");
    expect(edit).toHaveBeenCalledWith([{ op: "set_pace", pace: 1.5 }]);
  });

  it("text clip drag sends set_text_time keeping its duration", () => {
    const { w, edit } = mountTimeline();
    const clip = w.get('[data-text="t1"]').element;
    clip.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 20)); // +0.5 s
    expect(edit).toHaveBeenCalledWith([{ op: "set_text_time", text: "t1", start: 1.5, end: 3.5 }]);
  });

  it("a 1-2 px click on an unsnapped text clip does not pin it", () => {
    const film = makeFilm();
    film.texts.push({ id: "t2", scene: "s1", text: "Yo", start: 1.33, end: 3.37, pinned: false, style: "caption", x: null, y: null });
    const { w, edit } = mountTimeline(film);
    w.get('[data-text="t2"]').element.dispatchEvent(ptr("pointerdown", 50));
    window.dispatchEvent(ptr("pointerup", 52));
    w.get('[data-text="t2"] [data-handle="end"]').element.dispatchEvent(ptr("pointerdown", 50));
    window.dispatchEvent(ptr("pointerup", 51));
    expect(edit).not.toHaveBeenCalled();
  });

  it("moving a text clip snaps its start only and keeps its duration", () => {
    const film = makeFilm();
    film.texts.push({ id: "t2", scene: "s1", text: "Yo", start: 1.33, end: 3.37, pinned: false, style: "caption", x: null, y: null });
    const { w, edit } = mountTimeline(film);
    w.get('[data-text="t2"]').element.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 20)); // +0.5 s: start 1.83 -> 1.8, end = 1.8 + 2.04
    expect(edit).toHaveBeenCalledWith([{ op: "set_text_time", text: "t2", start: 1.8, end: 3.84 }]);
  });

  it("a 1 px click on a voice clip with an unsnapped offset does not pin it", () => {
    const film = makeFilm();
    film.scenes[0].voice.offset = 0.34;
    const { w, edit } = mountTimeline(film);
    w.get('[data-voice="s1"]').element.dispatchEvent(ptr("pointerdown", 10));
    window.dispatchEvent(ptr("pointerup", 11));
    expect(edit).not.toHaveBeenCalled();
  });

  it("text clip edge drag trims", () => {
    const { w, edit } = mountTimeline();
    w.get('[data-text="t1"] [data-handle="end"]').element.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 40));
    expect(edit).toHaveBeenCalledWith([{ op: "set_text_time", text: "t1", start: 1, end: 4 }]);
  });

  it("voice clip drag sends set_voice_offset relative to the scene, never below 0", () => {
    const { w, edit } = mountTimeline();
    const clip = w.get('[data-voice="s1"]');
    clip.element.dispatchEvent(ptr("pointerdown", 0));
    window.dispatchEvent(ptr("pointerup", 40));
    expect(edit).toHaveBeenLastCalledWith([{ op: "set_voice_offset", scene: "s1", offset: 1 }]);
    clip.element.dispatchEvent(ptr("pointerdown", 100));
    window.dispatchEvent(ptr("pointerup", 0));
    expect(edit).toHaveBeenCalledTimes(1); // clamped to 0 = where it already is: nothing to send
  });

  it("voice clip width is duration over speed; unmade voice is labelled", () => {
    const { w } = mountTimeline();
    expect(w.get('[data-voice="s1"]').attributes("style")).toContain("width: 80px"); // 2 s * 40
    expect(w.get('[data-voice-missing="s3"]').text()).toContain("voice not made yet");
    expect(w.find('[data-voice-missing="s1"]').exists()).toBe(false);
  });

  it("music lane says No music, or shows a bar", () => {
    expect(mountTimeline().w.get("[data-music]").text()).toContain("No music");
    const film = makeFilm();
    film.music = { file: "music/bed.mp3", volume: 0.6 };
    expect(mountTimeline(film).w.get("[data-music]").text()).toContain("bed.mp3");
  });

  it("clicking the ruler seeks", async () => {
    const { w, seek } = mountTimeline();
    const ruler = w.get("[data-ruler]");
    ruler.element.getBoundingClientRect = () => ({ left: 10, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 10, y: 0, toJSON() {} });
    ruler.element.dispatchEvent(ptr("pointerdown", 90)); // (90-10)/40 = 2 s
    expect(seek).toHaveBeenCalledWith(2);
    window.dispatchEvent(ptr("pointerup", 90));
  });

  it("ctrl+wheel zooms within 10-200 px/s", async () => {
    const { w } = mountTimeline();
    const body = w.get("[data-timeline-body]");
    for (let i = 0; i < 60; i++) body.element.dispatchEvent(wheel(-100));
    await nextTick();
    expect(w.get("[data-scene='s1']").attributes("style")).toContain("width: 1000px"); // 5 s * 200
    for (let i = 0; i < 120; i++) body.element.dispatchEvent(wheel(100));
    await nextTick();
    expect(w.get("[data-scene='s1']").attributes("style")).toContain("width: 50px"); // 5 s * 10
  });

  it("ruler shows a coloured marker per comment; clicking seeks and focuses the thread item", async () => {
    const mk = (id: string, time: number | null, state: QueueItem["state"]): QueueItem =>
      ({ id, kind: "comment", text: id, created: "", state, time, scene: null, scene_time: null, point: null,
        attachment: null, delivered_at: null, resolved_at: null });
    const { w, seek, focusItem } = mountTimeline(makeFilm(), { s1: 2, s2: 9 },
      [mk("c1", 2, "resolved"), mk("c2", 5, "queued"), mk("c3", null, "queued")]);
    const markers = w.findAll("[data-marker]");
    expect(markers.map((m) => m.attributes("data-marker"))).toEqual(["c1", "c2"]);
    expect(markers[0].attributes("style")).toContain("left: 80px"); // 2 s at 40 px/s
    await markers[0].trigger("click");
    expect(seek).toHaveBeenCalledWith(2);
    expect(focusItem.value).toBe("c1");
  });

  describe("removing", () => {
    it("clicking a scene selects it; Delete (via the store) asks before removing and closes the gap", async () => {
      const { w, edit, sel } = mountTimeline();
      await w.get('[data-scene="s2"]').trigger("pointerdown");
      expect(w.get('[data-scene="s2"]').classes()).toContain("selected");
      await sel.requestRemove(); // what the Delete key calls
      expect(edit).not.toHaveBeenCalled();
      const dialog = document.querySelector("[data-confirm]")!;
      expect(dialog.textContent).toContain('Remove scene "S2"');
      expect(dialog.textContent).toContain("closes the gap");
      expect(dialog.textContent).toContain("You can undo this");
      (document.querySelector("[data-confirm-yes]") as HTMLElement).click();
      await nextTick();
      expect(edit).toHaveBeenCalledWith([{ op: "remove_scene", scene: "s2" }]);
      expect(document.querySelector("[data-confirm]")).toBeNull();
      w.unmount();
    });

    it("the scene's ✕ asks first; Cancel removes nothing", async () => {
      const { w, edit } = mountTimeline();
      await w.get('[data-scene="s1"] [data-remove]').trigger("click");
      expect(document.querySelector("[data-confirm]")!.textContent).toContain("its voice line and 1 caption go with it");
      (document.querySelector("[data-confirm-no]") as HTMLElement).click();
      await nextTick();
      expect(document.querySelector("[data-confirm]")).toBeNull();
      expect(edit).not.toHaveBeenCalled();
      w.unmount();
    });

    it("a caption's ✕ removes it at once, without a question", async () => {
      const { w, edit } = mountTimeline();
      await w.get('[data-text="t1"] [data-remove]').trigger("click");
      await nextTick();
      expect(edit).toHaveBeenCalledWith([{ op: "remove_text", text: "t1" }]);
      expect(document.querySelector("[data-confirm]")).toBeNull();
      w.unmount();
    });

    it("pressing on empty track space clears the selection", async () => {
      const { w, sel } = mountTimeline();
      await w.get('[data-text="t1"]').trigger("pointerdown");
      expect(sel.selection.value).toEqual({ kind: "text", id: "t1" });
      await w.get("[data-timeline-body]").trigger("pointerdown");
      expect(sel.selection.value).toBeNull();
      w.unmount();
    });

    it("the toolbar shows the undo and redo buttons", () => {
      const { w } = mountTimeline();
      expect(w.find("[data-undo]").exists() && w.find("[data-redo]").exists() && w.find("[data-history-toggle]").exists()).toBe(true);
      w.unmount();
    });
  });

  it("the shape settings live in the top bar, not here", () => {
    const { w } = mountTimeline();
    expect(w.find("[data-aspect-main]").exists()).toBe(false);
    w.unmount();
  });

  describe("header: zoom, help, empty lanes", () => {
    const sceneWidth = (w: ReturnType<typeof mountTimeline>["w"]) =>
      Number(/width: ([\d.]+)px/.exec(w.get("[data-scene='s1']").attributes("style") ?? "")?.[1]);

    it("zoom buttons step the scale and stop at the limits", async () => {
      const { w } = mountTimeline();
      expect(sceneWidth(w)).toBe(200); // 5 s * 40 px/s
      await w.get("[data-zoom-in]").trigger("click");
      expect(sceneWidth(w)).toBe(250);
      await w.get("[data-zoom-out]").trigger("click");
      await w.get("[data-zoom-out]").trigger("click");
      expect(sceneWidth(w)).toBe(160);
      for (let i = 0; i < 30; i++) await w.get("[data-zoom-out]").trigger("click");
      expect(sceneWidth(w)).toBe(50); // 10 px/s floor
      expect(w.get("[data-zoom-out]").attributes("disabled")).toBeDefined();
      for (let i = 0; i < 30; i++) await w.get("[data-zoom-in]").trigger("click");
      expect(sceneWidth(w)).toBe(1000); // 200 px/s ceiling
      expect(w.get("[data-zoom-in]").attributes("disabled")).toBeDefined();
    });

    it("the zoom slider sets the scale", async () => {
      const { w } = mountTimeline();
      await w.get("[data-zoom-range]").setValue("100");
      expect(sceneWidth(w)).toBe(500);
    });

    it("tips are behind a help button: closed by default, Escape closes", async () => {
      const { w } = mountTimeline();
      expect(w.find("[data-help]").exists()).toBe(false);
      expect(w.text()).not.toContain("Shift while dragging");
      await w.get("[data-help-toggle]").trigger("click");
      expect(w.get("[data-help]").text()).toContain("zoom");
      expect(w.get("[data-help]").text()).toContain("Space");
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      await nextTick();
      expect(w.find("[data-help]").exists()).toBe(false);
    });

    it("lane labels carry an icon each", () => {
      const { w } = mountTimeline();
      const labels = w.findAll(".inner > .row > .label").filter((l) => l.text());
      expect(labels.map((l) => l.text())).toEqual(["Scenes", "Text", "Voice", "Sound", "Music"]);
      for (const l of labels) expect(l.find("svg").exists()).toBe(true);
    });

    it("an empty music lane is a dashed target whose link opens the file picker", async () => {
      const { w } = mountTimeline();
      const lane = w.get('[data-empty-lane="music"]');
      expect(lane.text()).toContain("No music");
      const click = vi.spyOn(w.get("[data-music-file]").element as HTMLInputElement, "click");
      await lane.get("[data-empty-action='add-music']").trigger("click");
      expect(click).toHaveBeenCalled();
    });

    it("music present: no empty-lane", () => {
      const film = makeFilm();
      film.music = { file: "music/bed.mp3", volume: 0.6 };
      expect(mountTimeline(film).w.find('[data-empty-lane="music"]').exists()).toBe(false);
    });

    it("voice not made at all: the lane offers Make voice, which starts synthesis", async () => {
      vi.mocked(api.synthesizeVoice).mockClear();
      const { w } = mountTimeline(makeFilm(), {});
      const link = w.get('[data-empty-action="make-voice"]');
      expect(w.find('[data-empty-lane="voice"]').exists()).toBe(false); // the dashed lane is only for "no lines at all"
      expect(w.findAll('[data-empty-action="make-voice"]')).toHaveLength(1);
      await link.trigger("click");
      await link.trigger("click"); // double click: the second one is ignored while the first run is going
      await w.get("[data-make-voice]").trigger("click");
      expect(api.synthesizeVoice).toHaveBeenCalledTimes(1);
      expect(link.attributes("disabled")).toBeDefined();
    });

    it("voice made: no empty lane; no narration lines: the lane says so without a link", () => {
      expect(mountTimeline().w.find('[data-empty-lane="voice"]').exists()).toBe(false);
      const film = makeFilm();
      film.scenes.forEach((sc) => { sc.voice.text = ""; });
      const lane = mountTimeline(film).w.get('[data-empty-lane="voice"]');
      expect(lane.text()).toContain("No narration lines yet");
      expect(lane.find("button").exists()).toBe(false);
    });
  });
});
