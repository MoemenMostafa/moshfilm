import { ref, watch, type Ref } from "vue";
import type { EditOp, Film, Selection } from "../types";

export interface PendingRemove {
  kind: "scene";
  id: string;
  title: string;
  /** Text clips that go with the scene. */
  captions: number;
  hasVoice: boolean;
}

/** What is selected on the timeline, and removing it (scenes ask first; everything is undoable). */
export function createSelection(film: Ref<Film | null>, edit: (ops: EditOp[]) => Promise<void>) {
  const selection = ref<Selection | null>(null);
  const pending = ref<PendingRemove | null>(null);

  function exists(sel: Selection): boolean {
    const f = film.value;
    if (!f) return false;
    if (sel.kind === "scene" || sel.kind === "voice") {
      const scene = f.scenes.find((s) => s.id === sel.id);
      return !!scene && (sel.kind === "scene" || !!scene.voice.text.trim());
    }
    if (sel.kind === "text") return f.texts.some((t) => t.id === sel.id);
    if (sel.kind === "sfx") return (f.sfx ?? []).some((c) => c.id === sel.id);
    return !!f.music;
  }

  watch(film, () => {
    if (selection.value && !exists(selection.value)) selection.value = null;
    if (pending.value && !film.value?.scenes.some((s) => s.id === pending.value!.id)) pending.value = null;
  });

  function select(kind: Selection["kind"], id: string): void {
    selection.value = { kind, id };
  }

  function clear(): void {
    selection.value = null;
  }

  async function removeNow(sel: Selection): Promise<void> {
    let op: EditOp;
    if (sel.kind === "scene") op = { op: "remove_scene", scene: sel.id };
    else if (sel.kind === "text") op = { op: "remove_text", text: sel.id };
    else if (sel.kind === "voice") op = { op: "remove_voice", scene: sel.id };
    else if (sel.kind === "sfx") op = { op: "remove_sfx", sfx: sel.id };
    else op = { op: "set_music", file: null, volume: film.value?.music?.volume ?? 0.6 };
    try {
      await edit([op]);
    } catch {
      return; // the store already shows why; the selection stays
    }
    if (selection.value && selection.value.kind === sel.kind && selection.value.id === sel.id) selection.value = null;
  }

  /** Delete key or ✕. A scene waits for `confirm()`; the rest go at once. */
  async function requestRemove(target?: Selection): Promise<void> {
    const sel = target ?? selection.value;
    if (!sel || pending.value || !exists(sel)) return;
    if (sel.kind !== "scene") return removeNow(sel);
    const scene = film.value!.scenes.find((s) => s.id === sel.id)!;
    pending.value = {
      kind: "scene", id: scene.id, title: scene.title,
      captions: film.value!.texts.filter((t) => t.scene === scene.id).length,
      hasVoice: !!scene.voice.text.trim(),
    };
  }

  async function confirm(): Promise<void> {
    const p = pending.value;
    if (!p) return;
    pending.value = null;
    await removeNow({ kind: "scene", id: p.id });
  }

  function cancel(): void {
    pending.value = null;
  }

  return { selection, pending, select, clear, requestRemove, confirm, cancel };
}
