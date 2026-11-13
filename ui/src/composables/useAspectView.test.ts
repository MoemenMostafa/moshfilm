import { describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";
import { mount } from "@vue/test-utils";
import { FilmKey, type FilmStore } from "./useFilm";
import { useAspectView, type AspectView } from "./useAspectView";
import type { Film } from "../types";

const film = (over: Partial<Film> = {}): Film => ({ version: 2, title: "t", width: 1280, height: 720, aspect: "16:9",
  second_aspect: "9:16", fps: 30, pace: 1, order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null,
  scenes: [], texts: [], ...over });

function use(f: Film) {
  const filmRef = ref<Film>(f);
  let api!: AspectView;
  const w = mount({ setup() { api = useAspectView(); return () => null; } },
    { global: { provide: { [FilmKey as symbol]: { film: filmRef } as unknown as FilmStore } } });
  return { api, filmRef, w };
}

describe("useAspectView", () => {
  it("defaults to main", () => {
    const { api, w } = use(film());
    expect(api.view.value).toBe("main");
    expect(api.aspect.value).toBe("16:9");
    expect(api.size.value).toEqual({ width: 1280, height: 720 });
    expect(api.hasSecond.value).toBe(true);
    api.set("second");
    expect(api.aspect.value).toBe("9:16");
    expect(api.size.value).toEqual({ width: 720, height: 1280 });
    api.set("main");
    w.unmount();
  });

  it("falls back to main when the second shape is removed", async () => {
    const { api, filmRef, w } = use(film());
    api.set("second");
    filmRef.value = film({ second_aspect: null });
    await nextTick();
    expect(api.view.value).toBe("main");
    expect(api.aspect.value).toBe("16:9");
    expect(api.hasSecond.value).toBe(false);
    api.set("second"); // nothing to show
    expect(api.view.value).toBe("main");
    w.unmount();
  });
});
