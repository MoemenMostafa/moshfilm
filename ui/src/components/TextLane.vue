<script setup lang="ts">
import { computed, ref } from "vue";
import type { Film, Selection } from "../types";
import Icon from "./Icon.vue";
import InlineEdit from "./InlineEdit.vue";
import { textWindow, type SceneSlot } from "../runtime/timing";
import { MIN_CLIP, snap, timeToPx, trackDrag } from "../timelineMath";

const props = defineProps<{ film: Film; slots: SceneSlot[]; pxPerSec: number; selected?: Selection | null }>();
const emit = defineEmits<{
  (e: "edit", ops: Record<string, unknown>[]): void;
  (e: "select", sel: Selection): void;
  (e: "remove", sel: Selection): void;
}>();

const editing = ref<string | null>(null); // text id being edited
const isSel = (id: string): boolean => props.selected?.kind === "text" && props.selected.id === id;
function saveText(id: string, content: string): void {
  editing.value = null;
  emit("edit", [{ op: "set_text_content", text: id, content }]);
}

const ROW = 30; // px per stacked row of clips
const MOVE_THRESHOLD_PX = 3; // smaller wiggles are clicks, not edits
type Mode = "move" | "start" | "end";
const drag = ref<{ id: string; mode: Mode; dx: number; shift: boolean } | null>(null);

const round3 = (t: number): number => Number(t.toFixed(3));

/** [start, end] relative to the clip's scene, after applying the drag in progress (or a finished one). */
function times(id: string, mode: Mode, dx: number, shift: boolean): { start: number; end: number; slotStart: number } {
  const clip = props.film.texts.find((t) => t.id === id)!;
  const slotStart = props.slots.find((s) => s.id === clip.scene)!.start;
  const [a, b] = textWindow(clip, props.slots);
  let start = a - slotStart;
  let end = b - slotStart;
  const dt = dx / props.pxPerSec;
  const fix = (t: number): number => (shift ? round3(t) : snap(t));
  if (mode === "move") {
    const duration = b - a;
    start = Math.max(0, fix(start + dt));
    end = round3(start + duration); // only the start snaps; the clip keeps its length
  } else if (mode === "start") {
    start = Math.min(end - MIN_CLIP, Math.max(0, fix(start + dt)));
  } else {
    end = Math.max(start + MIN_CLIP, fix(end + dt));
  }
  return { start, end, slotStart };
}

/** Stack overlapping clips in rows so none hides another. */
const clips = computed(() => {
  const rows: number[] = [];
  return props.film.texts.filter((t) => props.slots.some((s) => s.id === t.scene)).map((clip) => {
    const d = drag.value?.id === clip.id ? drag.value : null;
    const { start, end, slotStart } = d ? times(clip.id, d.mode, d.dx, d.shift)
      : times(clip.id, "move", 0, true);
    const abs0 = slotStart + start;
    const abs1 = slotStart + end;
    let row = rows.findIndex((last) => last <= abs0);
    if (row === -1) row = rows.length;
    rows[row] = abs1;
    return { clip, row, left: timeToPx(abs0, props.pxPerSec), width: Math.max(timeToPx(abs1 - abs0, props.pxPerSec), 6) };
  });
});
const rowCount = computed(() => Math.max(1, ...clips.value.map((c) => c.row + 1)));

function begin(e: PointerEvent, id: string, mode: Mode): void {
  emit("select", { kind: "text", id });
  drag.value = { id, mode, dx: 0, shift: e.shiftKey };
  trackDrag(e, (dx, shift) => { drag.value = { id, mode, dx, shift }; }, (dx, shift) => {
    drag.value = null;
    if (Math.abs(dx) < MOVE_THRESHOLD_PX) return;
    const { start, end } = times(id, mode, dx, shift);
    const before = times(id, "move", 0, true);
    if (round3(start) === round3(before.start) && round3(end) === round3(before.end)) return;
    emit("edit", [{ op: "set_text_time", text: id, start: round3(start), end: round3(end) }]);
  });
}
</script>

<template>
  <div class="text-lane" :style="{ height: rowCount * ROW - 2 + 'px' }">
    <div
      v-for="c in clips"
      :key="c.clip.id"
      class="clip tl-clip k-text"
      :class="{ selected: isSel(c.clip.id), editing: editing === c.clip.id }"
      :data-text="c.clip.id"
      :title="`${c.clip.text} (double-click to edit the caption)`"
      :style="{ left: c.left + 'px', width: c.width + 'px', top: c.row * ROW + 'px' }"
      @pointerdown="begin($event, c.clip.id, 'move')"
      @dblclick="editing = c.clip.id"
    >
      <span class="handle l tl-grip" data-handle="start" @pointerdown.stop.prevent="begin($event, c.clip.id, 'start')"></span>
      <template v-if="editing === c.clip.id">
        <InlineEdit :value="c.clip.text" @save="saveText(c.clip.id, $event)" @cancel="editing = null" />
      </template>
      <template v-else>
        <Icon name="text" />
        <span class="label tl-name">{{ c.clip.text }}</span>
      </template>
      <button v-if="c.clip.pinned" class="pin tl-pin" data-pin title="Pinned: click to unpin" aria-label="Unpin text time"
        @pointerdown.stop @click.stop="emit('edit', [{ op: 'unpin', target: `text:${c.clip.id}` }])"><Icon name="pin" /></button>
      <button v-if="editing !== c.clip.id" type="button" class="x tl-x" data-remove title="Remove this caption" aria-label="Remove caption"
        @pointerdown.stop @click.stop="emit('remove', { kind: 'text', id: c.clip.id })"><Icon name="close" /></button>
      <span class="handle r tl-grip" data-handle="end" @pointerdown.stop.prevent="begin($event, c.clip.id, 'end')"></span>
    </div>
  </div>
</template>

<style scoped>
.text-lane { position: relative; min-height: 28px; }
.clip { height: 28px; padding-left: 14px; }
.label { font-weight: 500; }
</style>
