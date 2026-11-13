import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import type { Film } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import AspectSettings from "./AspectSettings.vue";

function mountIt(over: Partial<Film> = {}) {
  const film = { aspect: "16:9", second_aspect: null, ...over } as unknown as Film;
  const edit = vi.fn(async () => {});
  const store = { film: ref(film), edit } as unknown as FilmStore;
  const w = mount(AspectSettings, { global: { provide: { [FilmKey as symbol]: store } } });
  return { w, edit };
}
const value = (w: ReturnType<typeof mountIt>["w"], sel: string) => (w.get(sel).element as HTMLSelectElement).value;

describe("AspectSettings", () => {
  it("shows the film's shapes", () => {
    const { w } = mountIt();
    expect(value(w, "[data-aspect-main]")).toBe("16:9");
    expect(value(w, "[data-aspect-second]")).toBe("");
    expect(w.findAll("[data-aspect-main] option").map((o) => o.attributes("value"))).toEqual(["16:9", "9:16", "1:1", "4:5"]);
    expect(w.findAll("[data-aspect-second] option").map((o) => o.attributes("value"))).toEqual(["", "16:9", "9:16", "1:1", "4:5"]);
    expect(w.get("[data-aspect-second]").attributes("title")).toBe("A second shape uses the same timeline and narration");
  });

  it("picking a second shape sends set_aspects", async () => {
    const { w, edit } = mountIt();
    await w.get("[data-aspect-second]").setValue("9:16");
    expect(edit).toHaveBeenCalledWith([{ op: "set_aspects", aspect: "16:9", second_aspect: "9:16" }]);
  });

  it("the main shape is disabled in the second list", () => {
    const { w } = mountIt();
    const opts = w.findAll("[data-aspect-second] option");
    expect(opts.find((o) => o.attributes("value") === "16:9")!.attributes("disabled")).toBeDefined();
    expect(opts.find((o) => o.attributes("value") === "9:16")!.attributes("disabled")).toBeUndefined();
  });

  it("choosing the second shape as main swaps them", async () => {
    const { w, edit } = mountIt({ second_aspect: "9:16" });
    await w.get("[data-aspect-main]").setValue("9:16");
    expect(edit).toHaveBeenCalledWith([{ op: "set_aspects", aspect: "9:16", second_aspect: "16:9" }]);
  });

  it("changing the main shape keeps the second one", async () => {
    const { w, edit } = mountIt({ second_aspect: "9:16" });
    await w.get("[data-aspect-main]").setValue("1:1");
    expect(edit).toHaveBeenCalledWith([{ op: "set_aspects", aspect: "1:1", second_aspect: "9:16" }]);
  });

  it("None removes the second shape", async () => {
    const { w, edit } = mountIt({ second_aspect: "9:16" });
    await w.get("[data-aspect-second]").setValue("");
    expect(edit).toHaveBeenCalledWith([{ op: "set_aspects", aspect: "16:9", second_aspect: null }]);
  });
});
