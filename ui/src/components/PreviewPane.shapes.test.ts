import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import { PlayheadKey } from "../composables/usePlayhead";
import { aspectViewState } from "../composables/useAspectView";

const fake = vi.hoisted(() => ({
  load: vi.fn(async () => {}), update: vi.fn(async () => {}), seek: vi.fn(), setAspect: vi.fn(async () => {}),
  reloadScene: vi.fn(async () => {}), destroy: vi.fn(), size: { width: 1280, height: 720 },
}));
vi.mock("../runtime/player", () => ({ createPlayer: vi.fn(() => fake) }));
import PreviewPane from "./PreviewPane.vue";

const filmWith = (second: string | null) => ({ version: 2, title: "t", width: 1280, height: 720, aspect: "16:9",
  second_aspect: second, fps: 30, pace: 1, order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null,
  scenes: [], texts: [] });

function mountPane(second: string | null) {
  const film = ref<any>(filmWith(second));
  const store = { film, folder: ref("/f"), voiceDurations: ref({}), sceneVersions: ref({}), slots: ref([]),
    activity: ref({ turn: null, plan: [] }), queue: ref({ items: [], messages: [], status: null, connected: false }) } as unknown as FilmStore;
  const head = { time: ref(2), playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek: vi.fn() };
  const w = mount(PreviewPane, { attachTo: document.body, global: {
    provide: { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head }, stubs: { CommentLayer: true } } });
  const fit = w.get(".fit").element;
  Object.defineProperty(fit, "clientWidth", { value: 1000, configurable: true });
  Object.defineProperty(fit, "clientHeight", { value: 500, configurable: true });
  return { w, film, head };
}
const style = (w: ReturnType<typeof mountPane>["w"]) => w.get(".frame").attributes("style")!;

describe("PreviewPane switching shapes", () => {
  beforeEach(() => { vi.clearAllMocks(); aspectViewState.value = "main"; });

  it("the switch redraws the player in the other shape and resizes the frame before it finishes loading", async () => {
    const { w, head } = mountPane("9:16");
    await flushPromises();
    let release!: () => void;
    fake.setAspect.mockImplementationOnce(() => new Promise<void>((r) => { release = r; }));
    await w.get('[data-aspect-view="second"]').trigger("click");
    expect(fake.setAspect).toHaveBeenCalledWith("9:16");
    // loading is still pending, yet the frame already has the 9:16 box
    expect(style(w)).toContain("width: 281px");
    release();
    await flushPromises();
    expect(fake.seek).toHaveBeenLastCalledWith(head.time.value);
    w.unmount();
  });

  it("falls back to main when the second shape is removed while it is shown", async () => {
    const { w, film } = mountPane("9:16");
    await w.get('[data-aspect-view="second"]').trigger("click");
    await flushPromises();
    expect(style(w)).toContain("width: 281px");
    film.value = filmWith(null);
    await flushPromises();
    expect(fake.setAspect).toHaveBeenLastCalledWith("16:9");
    expect(w.find('[data-testid="aspect-switch"]').exists()).toBe(false);
    expect(style(w)).toContain("width: 888px");
    w.unmount();
  });
});
