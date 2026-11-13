<script setup lang="ts">
import { computed, ref } from "vue";
import type { Film, Selection } from "../types";
import Icon from "./Icon.vue";
import InlineEdit from "./InlineEdit.vue";
import type { SceneSlot } from "../runtime/timing";
import { snap, timeToPx, trackDrag } from "../timelineMath";

const props = defineProps<{ making?: boolean; film: Film; slots: SceneSlot[]; durations: Record<string, number>; pxPerSec: number;
  selected?: Selection | null }>();
const emit = defineEmits<{
  (e: "edit", ops: Record<string, unknown>[]): void;
  (e: "select", sel: Selection): void;
  (e: "remove", sel: Selection): void;
  (e: "make-voice"): void;
}>();

const editing = ref<string | null>(null); // scene id whose narration is being edited
const isSel = (id: string): boolean => props.selected?.kind === "voice" && props.selected.id === id;
function saveText(sceneId: string, text: string): void {
  editing.value = null;
  emit("edit", [{ op: "set_voice_text", scene: sceneId, text }]);
}

const MOVE_THRESHOLD_PX = 3; // smaller wiggles are clicks, not edits
const drag = ref<{ id: string; dx: number; shift: boolean } | null>(null);

const offsetFor = (slot: SceneSlot, dx: number, shift: boolean): number => {
  const raw = Math.max(0, slot.voiceStart - slot.start + dx / props.pxPerSec);
  return shift ? Number(raw.toFixed(3)) : snap(raw);
};

const items = computed(() =>
  props.slots.map((slot, i) => ({ slot, scene: props.film.scenes[i] })).flatMap(({ slot, scene }) => {
    if (!scene.voice.text.trim()) return [];
    const d = props.durations[slot.id];
    if (d === undefined) return [{ slot, scene, missing: true, left: timeToPx(slot.start, props.pxPerSec), width: 0 }];
    const live = drag.value?.id === slot.id ? drag.value : null;
    const start = live ? slot.start + offsetFor(slot, live.dx, live.shift) : slot.voiceStart;
    return [{ slot, scene, missing: false, left: timeToPx(start, props.pxPerSec),
      width: timeToPx(d / slot.voiceSpeed, props.pxPerSec) }];
  }));

/** No made audio on the lane: it is a drop target that says why and offers the next step. */
const hasLines = computed(() => items.value.length > 0);
const nothingMade = computed(() => items.value.every((it) => it.missing));

function begin(e: PointerEvent, slot: SceneSlot): void {
  emit("select", { kind: "voice", id: slot.id });
  drag.value = { id: slot.id, dx: 0, shift: e.shiftKey };
  trackDrag(e, (dx, shift) => { drag.value = { id: slot.id, dx, shift }; }, (dx, shift) => {
    drag.value = null;
    if (Math.abs(dx) < MOVE_THRESHOLD_PX) return;
    const offset = offsetFor(slot, dx, shift);
    if (offset !== Number((slot.voiceStart - slot.start).toFixed(3))) {
      emit("edit", [{ op: "set_voice_offset", scene: slot.id, offset }]);
    }
  });
}
</script>

<template>
  <div class="voice-lane">
    <div v-if="!hasLines" class="empty-lane" data-empty-lane="voice">No narration lines yet · ask Claude to write the narration</div>
    <div v-if="nothingMade && hasLines" class="make-wrap">
      <button type="button" class="btn link make-link" data-empty-action="make-voice" :disabled="making"
        @pointerdown.stop @click="emit('make-voice')">{{ making ? "Making voice…" : "Make voice" }}</button>
    </div>
    <template v-for="it in items" :key="it.slot.id">
      <div v-if="it.missing" class="missing tl-clip k-voice hatched" :class="{ selected: isSel(it.slot.id), editing: editing === it.slot.id }"
        :data-voice-missing="it.slot.id" :style="{ left: it.left + 'px' }"
        @pointerdown="emit('select', { kind: 'voice', id: it.slot.id })" @dblclick="editing = it.slot.id">
        <InlineEdit v-if="editing === it.slot.id" :value="it.scene.voice.text" @save="saveText(it.slot.id, $event)" @cancel="editing = null" />
        <template v-else>
          <Icon name="mic" />
          <span class="tl-name">voice not made yet</span>
          <button type="button" class="x tl-x" data-remove title="Remove this voice line" aria-label="Remove voice line"
            @pointerdown.stop @click.stop="emit('remove', { kind: 'voice', id: it.slot.id })"><Icon name="close" /></button>
        </template>
      </div>
      <div v-else class="clip tl-clip k-voice" :class="{ selected: isSel(it.slot.id), editing: editing === it.slot.id }" :data-voice="it.slot.id"
        :style="{ left: it.left + 'px', width: it.width + 'px' }" :title="`${it.scene.voice.text} (double-click to edit the narration)`"
        @pointerdown="begin($event, it.slot)" @dblclick="editing = it.slot.id">
        <InlineEdit v-if="editing === it.slot.id" :value="it.scene.voice.text" @save="saveText(it.slot.id, $event)" @cancel="editing = null" />
        <template v-else>
          <Icon name="mic" />
          <span class="label tl-name">{{ it.scene.voice.text }}</span>
          <button v-if="it.scene.voice.pinned" class="pin tl-pin" data-pin title="Pinned: click to unpin" aria-label="Unpin voice time"
            @pointerdown.stop @click.stop="emit('edit', [{ op: 'unpin', target: `voice:${it.slot.id}` }])"><Icon name="pin" /></button>
          <button type="button" class="x tl-x" data-remove title="Remove this voice line" aria-label="Remove voice line"
            @pointerdown.stop @click.stop="emit('remove', { kind: 'voice', id: it.slot.id })"><Icon name="close" /></button>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
.voice-lane { position: relative; height: 28px; }
.clip, .missing { top: 0; height: 28px; }
.clip { padding-right: 10px; }
.missing { cursor: default; padding-right: 8px; font-style: italic; }
.missing .tl-name { font-weight: 500; }
.label { font-weight: 500; }
/* sits in the free space after the last scene (the header button is the always-visible one) */
.make-wrap { position: absolute; right: 4px; top: 3px; z-index: 4; }
.make-link { padding: 2px 6px; background: var(--bg); border-radius: 6px; }
</style>
