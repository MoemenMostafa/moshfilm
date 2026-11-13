<script setup lang="ts">
import { computed, ref } from "vue";
import type { Film, Selection } from "../types";
import { OVERFLOW_COPY, type SceneSlot } from "../runtime/timing";
import Icon from "./Icon.vue";
import { dragEdgeLength, reorderIndex, timeToPx, trackDrag } from "../timelineMath";

const props = defineProps<{ film: Film; slots: SceneSlot[]; pxPerSec: number; selected?: Selection | null }>();
const emit = defineEmits<{
  (e: "edit", ops: Record<string, unknown>[]): void;
  (e: "select", sel: Selection): void;
  (e: "remove", sel: Selection): void;
}>();

const MOVE_THRESHOLD_PX = 3; // smaller wiggles are clicks, not reorders
type Drag = { id: string; mode: "edge" | "move"; dx: number; shift: boolean };
const drag = ref<Drag | null>(null);

const scenes = computed(() =>
  props.slots.map((slot, i) => ({ slot, scene: props.film.scenes[i], index: i })));

function newLength(slot: SceneSlot, dx: number, shift: boolean): number {
  return dragEdgeLength(slot.length, dx, props.pxPerSec, !shift);
}

/** Where a block is drawn: later scenes slide along while an edge is dragged. */
function view(slot: SceneSlot, index: number): { left: number; width: number; shift: number } {
  const d = drag.value;
  let left = slot.start;
  let length = slot.length;
  let shift = 0;
  if (d?.mode === "edge") {
    const delta = newLength(props.slots.find((s) => s.id === d.id)!, d.dx, d.shift) -
      props.slots.find((s) => s.id === d.id)!.length;
    if (slot.id === d.id) length += delta;
    else if (index > props.slots.findIndex((s) => s.id === d.id)) left += delta;
  } else if (d?.mode === "move" && d.id === slot.id) {
    shift = d.dx;
  }
  return { left: timeToPx(left, props.pxPerSec), width: timeToPx(length, props.pxPerSec), shift };
}

function startEdge(e: PointerEvent, slot: SceneSlot): void {
  drag.value = { id: slot.id, mode: "edge", dx: 0, shift: e.shiftKey };
  trackDrag(e, (dx, shift) => { drag.value = { id: slot.id, mode: "edge", dx, shift }; }, (dx, shift) => {
    drag.value = null;
    const length = newLength(slot, dx, shift);
    if (length !== slot.length) emit("edit", [{ op: "set_length", scene: slot.id, length }]);
  });
}

function startMove(e: PointerEvent, slot: SceneSlot, index: number): void {
  emit("select", { kind: "scene", id: slot.id });
  drag.value = { id: slot.id, mode: "move", dx: 0, shift: false };
  trackDrag(e, (dx) => { drag.value = { id: slot.id, mode: "move", dx, shift: false }; }, (dx) => {
    drag.value = null;
    if (Math.abs(dx) < MOVE_THRESHOLD_PX) return;
    const centre = slot.start + slot.length / 2 + dx / props.pxPerSec;
    const target = reorderIndex(props.slots, centre, slot.id);
    if (target !== index) emit("edit", [{ op: "move_scene", scene: slot.id, index: target }]);
  });
}

const fmtLen = (t: number): string => `${Number(t.toFixed(1))}s`;
</script>

<template>
  <div class="scene-lane">
    <div
      v-for="{ slot, scene, index } in scenes"
      :key="slot.id"
      class="scene tl-clip k-scene"
      :class="{ overflow: slot.overflow, hatched: scene.status !== 'ready', moving: drag?.id === slot.id && drag.mode === 'move',
        selected: selected?.kind === 'scene' && selected.id === slot.id }"
      :data-scene="slot.id"
      :title="slot.overflow ? OVERFLOW_COPY : scene.title"
      :style="{ left: view(slot, index).left + 'px', width: view(slot, index).width + 'px',
        transform: view(slot, index).shift ? `translateX(${view(slot, index).shift}px)` : undefined }"
      @pointerdown="startMove($event, slot, index)"
    >
      <div class="main">
        <Icon name="scenes" />
        <span class="name tl-name">{{ scene.title }}</span>
        <span class="len tl-len">{{ fmtLen(view(slot, index).width / pxPerSec) }}</span>
        <span v-if="scene.status !== 'ready'" class="status tl-sub">{{ scene.status }}</span>
      </div>
      <span v-if="slot.overflow" class="flag">{{ OVERFLOW_COPY }}</span>
      <button v-if="scene.pinned" class="pin tl-pin" data-pin title="Pinned: click to unpin" aria-label="Unpin scene length"
        @pointerdown.stop @click.stop="emit('edit', [{ op: 'unpin', target: `scene:${slot.id}` }])"><Icon name="pin" /></button>
      <button type="button" class="x tl-x" data-remove title="Remove this scene" aria-label="Remove scene"
        @pointerdown.stop @click.stop="emit('remove', { kind: 'scene', id: slot.id })"><Icon name="close" /></button>
      <span class="edge tl-grip" data-handle="edge" @pointerdown.stop.prevent="startEdge($event, slot)"></span>
    </div>
  </div>
</template>

<style scoped>
.scene-lane { position: relative; height: 44px; }
.scene { top: 0; bottom: 0; flex-direction: column; align-items: stretch; justify-content: center; gap: 0; padding-right: 14px; }
.main { display: flex; align-items: center; gap: 6px; min-width: 0; }
.main .ico { opacity: 0.85; }
.status { margin-left: var(--s1); }
.flag { font-size: var(--fs-meta); font-weight: 600; overflow: hidden; text-overflow: ellipsis; line-height: 1.2; }
.scene .tl-x, .scene .tl-pin { top: 11px; transform: none; }
</style>
