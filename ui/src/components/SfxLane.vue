<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import * as api from "../api";
import { locate, type SceneSlot } from "../runtime/timing";
import { sfxSceneEnd, sfxStart } from "../runtime/sound";
import { snap, timeToPx, trackDrag } from "../timelineMath";
import type { Film, Selection, SoundCatalog } from "../types";
import Icon from "./Icon.vue";

const props = defineProps<{
  film: Film;
  slots: SceneSlot[];
  pxPerSec: number;
  selected?: Selection | null;
  /** Sound id -> length of its rendered audio, seconds (from the server). */
  durations?: Record<string, number>;
  catalog?: SoundCatalog | null;
  /** Film time of the playhead: new sounds are added there. */
  playhead?: number;
}>();
const emit = defineEmits<{
  (e: "edit", ops: Record<string, unknown>[]): void;
  (e: "select", sel: Selection): void;
  (e: "remove", sel: Selection): void;
}>();

const ROW = 30; // px per stacked row of clips
const MOVE_THRESHOLD_PX = 3; // smaller wiggles are clicks, not edits
const round3 = (t: number): number => Number(t.toFixed(3));

const sfx = computed(() => props.film.sfx ?? []);
const label = (preset: string): string => props.catalog?.sfx.find((p) => p.name === preset)?.label ?? preset;
const isSel = (id: string): boolean => props.selected?.kind === "sfx" && props.selected.id === id;
const selectedClip = computed(() => (props.selected?.kind === "sfx" ? sfx.value.find((c) => c.id === props.selected!.id) : undefined));

const drag = ref<{ id: string; dx: number; shift: boolean } | null>(null);

function lengthOf(id: string): number {
  const known = props.durations?.[id];
  if (known !== undefined) return known;
  const clip = sfx.value.find((c) => c.id === id)!;
  const base = props.catalog?.sfx.find((p) => p.name === clip.preset)?.duration ?? 0.5;
  return base * clip.stretch;
}

/** Where a drag would put the clip's start on the film timeline (snapped to 0.1 s; Shift: no snap). */
function draggedStart(from: number, dx: number, shift: boolean): number {
  const t = Math.max(0, from + dx / props.pxPerSec);
  return shift ? round3(t) : snap(t);
}

/** End of the scene a film time falls in (the last scene's end beyond the film). */
function endOfSceneAt(t: number): number {
  const slot = props.slots.find((s) => t < s.start + s.length) ?? props.slots[props.slots.length - 1];
  return slot.start + slot.length;
}

/** Stack overlapping clips in rows so none hides another. */
const clips = computed(() => {
  const rows: number[] = [];
  const placed = sfx.value
    .filter((c) => props.slots.some((s) => s.id === c.scene))
    .map((clip) => {
      const base = sfxStart(clip, props.slots);
      const d = drag.value?.id === clip.id ? drag.value : null;
      const start = d ? draggedStart(base, d.dx, d.shift) : base;
      return { clip, start, base };
    })
    .sort((a, b) => a.start - b.start);
  return placed.map(({ clip, start }) => {
    const len = lengthOf(clip.id);
    // the part past its scene's end is cut at playback: drawn hatched so it is clear what will be heard
    const d = drag.value?.id === clip.id ? drag.value : null;
    const sceneEnd = d ? endOfSceneAt(start) : sfxSceneEnd(clip, props.slots);
    const cutPx = Math.max(0, timeToPx(Math.min(len, start + len - sceneEnd), props.pxPerSec));
    let row = rows.findIndex((last) => last <= start);
    if (row === -1) row = rows.length;
    rows[row] = start + len;
    const width = Math.max(timeToPx(len, props.pxPerSec), 6);
    return { clip, row, left: timeToPx(start, props.pxPerSec), width, cut: Math.min(cutPx, width) };
  });
});
const rowCount = computed(() => Math.max(1, ...clips.value.map((c) => c.row + 1)));

function begin(e: PointerEvent, id: string): void {
  emit("select", { kind: "sfx", id });
  drag.value = { id, dx: 0, shift: e.shiftKey };
  const clip = sfx.value.find((c) => c.id === id)!;
  const from = sfxStart(clip, props.slots);
  trackDrag(e, (dx, shift) => { drag.value = { id, dx, shift }; }, (dx, shift) => {
    drag.value = null;
    if (Math.abs(dx) < MOVE_THRESHOLD_PX) return;
    const where = locate(props.slots, draggedStart(from, dx, shift));
    if (!where) return;
    const at = round3(where.sceneTime);
    if (where.sceneId === clip.scene && at === round3(clip.at)) return;
    emit("edit", [{ op: "set_sfx_time", sfx: id, scene: where.sceneId, at }]);
  });
}

function setVolume(e: Event): void {
  const clip = selectedClip.value;
  if (clip) emit("edit", [{ op: "set_sfx", sfx: clip.id, volume: Number((e.target as HTMLInputElement).value) }]);
}

// ---- the add menu
const menuOpen = ref(false);
/** Fixed position of the menu: it opens below the button, or above it when the screen ends too soon. */
const menuPos = ref<Record<string, string>>({});
const addButton = ref<HTMLButtonElement | null>(null);
const root = ref<HTMLElement | null>(null);
const canAdd = computed(() => props.slots.length > 0);

function toggleMenu(): void {
  if (!menuOpen.value) {
    const r = addButton.value?.getBoundingClientRect();
    const left = `${Math.max(4, Math.min(r?.left ?? 0, window.innerWidth - 348))}px`;
    const below = window.innerHeight - (r?.bottom ?? 0);
    menuPos.value = below >= 360 || !r ? { left, top: `${(r?.bottom ?? 0) + 4}px` }
      : { left, bottom: `${window.innerHeight - r.top + 4}px` };
  }
  menuOpen.value = !menuOpen.value;
}

function add(preset: string): void {
  const where = locate(props.slots, props.playhead ?? 0);
  menuOpen.value = false;
  if (where) emit("edit", [{ op: "add_sfx", preset, scene: where.sceneId, at: round3(where.sceneTime) }]);
}

let current: HTMLAudioElement | null = null;
function audition(name: string): void {
  try {
    current?.pause();
    current = new Audio(api.presetUrl(name));
    void current.play()?.catch(() => { /* autoplay blocked: the next click retries */ });
  } catch {
    /* no audio available */
  }
}

function onDocDown(e: Event): void {
  if (menuOpen.value && root.value && !root.value.contains(e.target as Node)) menuOpen.value = false;
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape") menuOpen.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", onDocDown);
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  document.removeEventListener("pointerdown", onDocDown);
  window.removeEventListener("keydown", onKey);
  current?.pause();
});
</script>

<template>
  <div ref="root" class="sfx-lane">
    <div class="toolbar" data-sfx-toolbar>
      <button ref="addButton" type="button" class="btn ghost sm" data-sfx-add :disabled="!canAdd" :aria-expanded="menuOpen"
        title="Add a sound effect at the playhead" @click="toggleMenu"><Icon name="plus" />Add sound</button>
      <template v-if="selectedClip">
        <span class="sel mono">{{ label(selectedClip.preset) }}</span>
        <input type="range" min="0" max="1" step="0.05" data-sfx-volume :value="selectedClip.volume" aria-label="Sound volume"
          @change="setVolume" />
        <span class="mono pct">{{ Math.round(selectedClip.volume * 100) }}%</span>
      </template>
      <span v-else-if="!sfx.length" class="none" data-empty-lane="sfx">No sounds</span>
    </div>
    <div v-if="menuOpen" class="menu" data-sfx-menu role="menu" :style="menuPos">
      <div v-for="p in catalog?.sfx ?? []" :key="p.name" class="item" role="menuitem" tabindex="0" :data-sfx-preset="p.name"
        :title="p.description" @click="add(p.name)" @keydown.enter="add(p.name)">
        <span class="name">{{ p.label }}</span>
        <span class="desc">{{ p.description }}</span>
        <button type="button" class="btn icon ghost" data-sfx-audition :aria-label="`Listen to ${p.label}`" title="Listen"
          @click.stop="audition(p.name)"><Icon name="play" /></button>
      </div>
      <div v-if="!catalog" class="item none">Loading sounds…</div>
    </div>
    <div class="clips" :style="{ height: (sfx.length ? rowCount * ROW - 2 : 0) + 'px' }">
      <div
        v-for="c in clips"
        :key="c.clip.id"
        class="clip tl-clip k-sfx"
        :class="{ selected: isSel(c.clip.id), moving: drag?.id === c.clip.id && Math.abs(drag.dx) >= MOVE_THRESHOLD_PX }"
        :data-sfx="c.clip.id"
        :title="`${label(c.clip.preset)} (drag to move)`"
        :style="{ left: c.left + 'px', width: c.width + 'px', top: c.row * ROW + 'px' }"
        @pointerdown="begin($event, c.clip.id)"
      >
        <Icon name="sound" />
        <span class="tl-name">{{ label(c.clip.preset) }}</span>
        <span v-if="c.cut > 0.5" class="cut" data-sfx-cut :style="{ width: c.cut + 'px' }" title="Cut at the end of the scene"></span>
        <button v-if="c.clip.pinned" type="button" class="pin tl-pin" data-pin title="Pinned: click to unpin" aria-label="Unpin sound"
          @pointerdown.stop @click.stop="emit('edit', [{ op: 'unpin', target: `sfx:${c.clip.id}` }])"><Icon name="pin" /></button>
        <button type="button" class="x tl-x" data-remove title="Remove this sound" aria-label="Remove sound"
          @pointerdown.stop @click.stop="emit('remove', { kind: 'sfx', id: c.clip.id })"><Icon name="close" /></button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.sfx-lane { position: relative; }
.toolbar { position: sticky; left: 76px; z-index: 5; display: flex; align-items: center; gap: var(--s2); height: 28px; width: max-content; max-width: 100%;
  font-size: var(--fs-sec); color: var(--muted); }
.toolbar input[type="range"] { width: 90px; }
.sel { color: var(--text); }
.pct { min-width: 3ch; }
.none { padding: 0 var(--s2); border: 1px dashed var(--border-strong); border-radius: var(--r-ctl); line-height: 22px; }
.clips { position: relative; margin-top: 2px; }
.clip { height: 28px; padding-left: 8px; }
.cut { position: absolute; top: 0; bottom: 0; right: 0; pointer-events: none; opacity: 0.8; border-left: 2px solid var(--warn);
  background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--bg) 70%, transparent) 0 4px, transparent 4px 8px); }
.menu { position: fixed; z-index: 40; width: 340px; max-height: 60vh; overflow: auto; padding: var(--s1); background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-card); box-shadow: var(--shadow); }
.item { display: flex; align-items: center; gap: var(--s2); padding: 4px var(--s2); border-radius: 6px; cursor: pointer; font-size: var(--fs-sec); }
.item:hover, .item:focus-visible { background: var(--surface-2); }
.item .name { font-weight: 600; flex: none; min-width: 78px; }
.item .desc { flex: 1; min-width: 0; color: var(--muted); font-size: var(--fs-meta); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
