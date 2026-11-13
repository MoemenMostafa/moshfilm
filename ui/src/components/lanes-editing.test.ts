import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { Film } from "../types";
import { layout } from "../runtime/timing";
import SceneLane from "./SceneLane.vue";
import TextLane from "./TextLane.vue";
import VoiceLane from "./VoiceLane.vue";

const scene = (id: string, text: string) => ({ id, title: id.toUpperCase(), file: null, length: 5, pinned: true,
  status: "ready" as const, voice: { text, offset: 0.3, pinned: false, text_pinned: false } });
const film: Film = { version: 1, title: "t", width: 1280, height: 720, fps: 30, pace: 1, order_pinned: false,
  voice: { name: "v", rate: "+0%" }, music: null, removed_by_person: [],
  scenes: [scene("s1", "hello there"), scene("s2", "")],
  texts: [{ id: "t1", scene: "s1", text: "Hi", start: 1, end: 3, pinned: false, text_pinned: false, style: "caption", x: null, y: null }] };
const slots = layout(film, { s1: 2 });

describe("voice lane editing", () => {
  const props = { film, slots, durations: { s1: 2 }, pxPerSec: 40, selected: null };

  it("double-click opens the inline editor; Enter sends set_voice_text", async () => {
    const w = mount(VoiceLane, { props, attachTo: document.body });
    await w.get("[data-voice=s1]").trigger("dblclick");
    const input = w.get("[data-inline-edit]");
    expect((input.element as HTMLInputElement).value).toBe("hello there");
    await input.setValue("brand new narration");
    await input.trigger("keydown", { key: "Enter" });
    expect(w.emitted("edit")).toEqual([[[{ op: "set_voice_text", scene: "s1", text: "brand new narration" }]]]);
    expect(w.find("[data-inline-edit]").exists()).toBe(false);
    w.unmount();
  });

  it("blur saves, Esc cancels", async () => {
    const w = mount(VoiceLane, { props, attachTo: document.body });
    await w.get("[data-voice=s1]").trigger("dblclick");
    await w.get("[data-inline-edit]").setValue("by blur");
    await w.get("[data-inline-edit]").trigger("blur");
    expect(w.emitted("edit")).toEqual([[[{ op: "set_voice_text", scene: "s1", text: "by blur" }]]]);
    await w.get("[data-voice=s1]").trigger("dblclick");
    await w.get("[data-inline-edit]").setValue("dropped");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Escape" });
    expect(w.emitted("edit")).toHaveLength(1);
    expect(w.find("[data-inline-edit]").exists()).toBe(false);
    w.unmount();
  });

  it("a line whose voice is not made yet can still be edited", async () => {
    const w = mount(VoiceLane, { props: { ...props, durations: {} }, attachTo: document.body });
    await w.get("[data-voice-missing=s1]").trigger("dblclick");
    expect((w.get("[data-inline-edit]").element as HTMLInputElement).value).toBe("hello there");
    w.unmount();
  });

  it("clicking selects; the ✕ asks to remove that voice line", async () => {
    const w = mount(VoiceLane, { props });
    await w.get("[data-voice=s1]").trigger("pointerdown");
    expect(w.emitted("select")).toEqual([[{ kind: "voice", id: "s1" }]]);
    await w.get("[data-voice=s1] [data-remove]").trigger("click");
    expect(w.emitted("remove")).toEqual([[{ kind: "voice", id: "s1" }]]);
    const sel = mount(VoiceLane, { props: { ...props, selected: { kind: "voice", id: "s1" } } });
    expect(sel.get("[data-voice=s1]").classes()).toContain("selected");
  });
});

describe("text lane editing", () => {
  const props = { film, slots, pxPerSec: 40, selected: null };

  it("double-click edits the caption; Enter sends set_text_content", async () => {
    const w = mount(TextLane, { props, attachTo: document.body });
    await w.get("[data-text=t1]").trigger("dblclick");
    await w.get("[data-inline-edit]").setValue("A better caption");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Enter" });
    expect(w.emitted("edit")).toEqual([[[{ op: "set_text_content", text: "t1", content: "A better caption" }]]]);
    w.unmount();
  });

  it("Esc cancels without sending anything", async () => {
    const w = mount(TextLane, { props, attachTo: document.body });
    await w.get("[data-text=t1]").trigger("dblclick");
    await w.get("[data-inline-edit]").setValue("nope");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Escape" });
    expect(w.emitted("edit")).toBeUndefined();
    w.unmount();
  });

  it("select and ✕", async () => {
    const w = mount(TextLane, { props });
    await w.get("[data-text=t1]").trigger("pointerdown");
    expect(w.emitted("select")).toEqual([[{ kind: "text", id: "t1" }]]);
    await w.get("[data-text=t1] [data-remove]").trigger("click");
    expect(w.emitted("remove")).toEqual([[{ kind: "text", id: "t1" }]]);
  });
});

describe("scene lane selection", () => {
  it("clicking a scene selects it; its ✕ asks to remove it (the timeline then confirms)", async () => {
    const w = mount(SceneLane, { props: { film, slots, pxPerSec: 40, selected: { kind: "scene", id: "s2" } } });
    await w.get("[data-scene=s1]").trigger("pointerdown");
    expect(w.emitted("select")).toEqual([[{ kind: "scene", id: "s1" }]]);
    expect(w.get("[data-scene=s2]").classes()).toContain("selected");
    await w.get("[data-scene=s1] [data-remove]").trigger("click");
    expect(w.emitted("remove")).toEqual([[{ kind: "scene", id: "s1" }]]);
    expect(w.emitted("edit")).toBeUndefined();
  });
});
