import { describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";
import type { Film } from "../types";
import { createSelection } from "./useSelection";

const scene = (id: string, text = "") => ({ id, title: id.toUpperCase(), file: null, length: 4, pinned: false,
  status: "ready" as const, voice: { text, offset: 0.3, pinned: false, text_pinned: false } });
const makeFilm = (): Film => ({ version: 1, title: "t", width: 1280, height: 720, fps: 30, pace: 1, order_pinned: false,
  voice: { name: "v", rate: "+0%" }, music: { file: "music/a.mp3", volume: 0.5 }, removed_by_person: [],
  scenes: [scene("s1", "hello"), scene("s2")],
  texts: [{ id: "t1", scene: "s1", text: "Hi", start: 0, end: 1, pinned: false, text_pinned: false, style: "caption", x: null, y: null },
    { id: "t2", scene: "s1", text: "Yo", start: 1, end: 2, pinned: false, text_pinned: false, style: "caption", x: null, y: null }] });

function setup() {
  const film = ref<Film | null>(makeFilm());
  const edit = vi.fn(async () => {});
  return { film, edit, sel: createSelection(film, edit) };
}

describe("selection and removal", () => {
  it("removing a scene asks first and does not remove until confirmed", async () => {
    const { sel, edit } = setup();
    sel.select("scene", "s1");
    await sel.requestRemove();
    expect(edit).not.toHaveBeenCalled();
    expect(sel.pending.value).toEqual({ kind: "scene", id: "s1", title: "S1", captions: 2, hasVoice: true });
    await sel.confirm();
    expect(edit).toHaveBeenCalledWith([{ op: "remove_scene", scene: "s1" }]);
    expect(sel.pending.value).toBeNull();
    expect(sel.selection.value).toBeNull();
  });

  it("cancelling the confirm removes nothing and keeps the selection", async () => {
    const { sel, edit } = setup();
    sel.select("scene", "s2");
    await sel.requestRemove();
    sel.cancel();
    expect(sel.pending.value).toBeNull();
    expect(edit).not.toHaveBeenCalled();
    expect(sel.selection.value).toEqual({ kind: "scene", id: "s2" });
  });

  it("texts, voice lines and music go at once (every removal is undoable)", async () => {
    const { sel, edit } = setup();
    sel.select("text", "t1");
    await sel.requestRemove();
    sel.select("voice", "s1");
    await sel.requestRemove();
    sel.select("music", "music");
    await sel.requestRemove();
    expect(edit.mock.calls).toEqual([
      [[{ op: "remove_text", text: "t1" }]],
      [[{ op: "remove_voice", scene: "s1" }]],
      [[{ op: "set_music", file: null, volume: 0.5 }]],
    ]);
    expect(sel.pending.value).toBeNull();
  });

  it("removes a selected sound with remove_sfx", async () => {
    const { sel, edit, film } = setup();
    film.value = { ...film.value!, sfx: [{ id: "fx1", scene: "s1", preset: "ding", at: 0.5, volume: 0.7, pitch: 0,
      stretch: 1, seed: 0, pinned: true }] };
    sel.select("sfx", "fx1");
    await sel.requestRemove();
    expect(edit).toHaveBeenCalledWith([{ op: "remove_sfx", sfx: "fx1" }]);
    expect(sel.selection.value).toBeNull();
  });

  it("with nothing selected, remove does nothing", async () => {
    const { sel, edit } = setup();
    await sel.requestRemove();
    expect(edit).not.toHaveBeenCalled();
    expect(sel.pending.value).toBeNull();
  });

  it("a ✕ can name its target directly without selecting first", async () => {
    const { sel, edit } = setup();
    await sel.requestRemove({ kind: "text", id: "t2" });
    expect(edit).toHaveBeenCalledWith([{ op: "remove_text", text: "t2" }]);
  });

  it("clears the selection when the thing disappears, and a second request while asking is ignored", async () => {
    const { sel, film, edit } = setup();
    sel.select("text", "t1");
    film.value = { ...film.value!, texts: [] };
    await nextTick();
    expect(sel.selection.value).toBeNull();
    sel.select("scene", "s1");
    await sel.requestRemove();
    await sel.requestRemove({ kind: "text", id: "t2" });
    expect(edit).not.toHaveBeenCalled();
    expect(sel.pending.value?.id).toBe("s1");
  });
});
