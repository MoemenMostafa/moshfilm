<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import * as api from "../api";
import type { Film, MusicBed, Selection, SoundCatalog } from "../types";
import { timeToPx } from "../timelineMath";
import Icon from "./Icon.vue";

const props = defineProps<{ film: Film; total: number; pxPerSec: number; selected?: Selection | null; catalog?: SoundCatalog | null;
  /** A bed is being made or fetched: "New variation" waits so renders do not queue up. */
  busy?: boolean;
}>();
const emit = defineEmits<{
  (e: "edit", ops: Record<string, unknown>[]): void;
  (e: "select", sel: Selection): void;
}>();
const name = (file: string | null): string => (file ? file.split("/").pop() ?? file : "Generated music");
const cap = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);
const error = ref<string | null>(null);
const picker = ref<HTMLInputElement | null>(null);

const bed = computed(() => props.film.music?.bed ?? null);
const volumeNow = computed(() => props.film.music?.volume ?? 0.5);
const moods = computed(() => props.catalog?.moods ?? []);
const tempoRange = computed(() => props.catalog?.tempo ?? [60, 160]);
const label = computed(() => {
  const b = bed.value;
  return b ? `${cap(b.mood)} · ${b.tempo} bpm · ${b.key} ${b.scale} · ${cap(b.palette)} · ${Math.round(volumeNow.value * 100)}%` : "";
});

async function pick(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  error.value = null;
  try {
    await api.uploadMusic(file); // the server saves it and sets it as the film's music; the film event refreshes us
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err);
  }
  input.value = "";
}

/** One edit that carries every field, so each change is one undo step. */
function setBed(next: MusicBed, volume = volumeNow.value): void {
  emit("edit", [{ op: "set_music_bed", mood: next.mood, tempo: next.tempo, key: next.key, scale: next.scale,
    palette: next.palette, seed: next.seed, volume }]);
}

function generate(): void {
  const calm = moods.value.find((m) => m.name === "calm");
  if (!calm) return;
  setBed({ mood: "calm", tempo: calm.tempo, key: "C", scale: calm.scale, palette: calm.palette, seed: 1 }, 0.5);
}

function volume(e: Event): void {
  const m = props.film.music;
  if (!m) return;
  const v = Number((e.target as HTMLInputElement).value);
  if (m.bed) setBed(m.bed, v);
  else if (m.file) emit("edit", [{ op: "set_music", file: m.file, volume: v }]);
}
const onVolumeInput = (e: Event): void => { if (!bed.value) volume(e); }; // a file keeps the live slider; a bed edits on release

function remove(): void {
  emit("edit", [{ op: "set_music", file: null, volume: props.film.music?.volume ?? 0.6 }]);
}

// ---- the options panel
const panelOpen = ref(false);
/** Fixed position of the panel: below the button, or above it when the screen ends too soon. */
const panelPos = ref<Record<string, string>>({});
const optionsButton = ref<HTMLButtonElement | null>(null);
const root = ref<HTMLElement | null>(null);

function togglePanel(): void {
  if (!panelOpen.value) {
    const r = optionsButton.value?.getBoundingClientRect();
    const left = `${Math.max(4, Math.min(r?.left ?? 0, window.innerWidth - 340))}px`;
    const below = window.innerHeight - (r?.bottom ?? 0);
    panelPos.value = below >= 260 || !r ? { left, top: `${(r?.bottom ?? 0) + 4}px` }
      : { left, bottom: `${window.innerHeight - r.top + 4}px` };
  }
  panelOpen.value = !panelOpen.value;
}

function changeMood(e: Event): void {
  const b = bed.value;
  const mood = moods.value.find((m) => m.name === (e.target as HTMLSelectElement).value);
  if (b && mood) setBed({ ...b, mood: mood.name, tempo: mood.tempo, scale: mood.scale, palette: mood.palette });
}
function changeTempo(e: Event): void {
  const input = e.target as HTMLInputElement;
  const b = bed.value;
  const n = Math.round(Number(input.value));
  if (!b || !Number.isFinite(n)) return;
  const [lo, hi] = tempoRange.value;
  const tempo = Math.min(hi, Math.max(lo, n));
  input.value = String(tempo);
  if (tempo !== b.tempo) setBed({ ...b, tempo });
}
function changeKey(e: Event): void {
  const b = bed.value;
  if (b) setBed({ ...b, key: (e.target as HTMLSelectElement).value });
}
function changeScale(e: Event): void {
  const b = bed.value;
  if (b) setBed({ ...b, scale: (e.target as HTMLSelectElement).value as MusicBed["scale"] });
}
function changePalette(e: Event): void {
  const b = bed.value;
  if (b) setBed({ ...b, palette: (e.target as HTMLSelectElement).value as MusicBed["palette"] });
}
// Clicks on "New variation" arrive faster than a long bed renders: collect them and send one edit
// (seed + number of clicks), so only one render is asked for.
const REGENERATE_DELAY = 350;
let bumps = 0;
let bumpTimer: ReturnType<typeof setTimeout> | null = null;
function regenerate(): void {
  if (!bed.value) return;
  bumps += 1;
  if (bumpTimer) clearTimeout(bumpTimer);
  bumpTimer = setTimeout(() => {
    bumpTimer = null;
    const b = bed.value;
    const n = bumps;
    bumps = 0;
    if (b) setBed({ ...b, seed: b.seed + n });
  }, REGENERATE_DELAY);
}

function onDocDown(e: Event): void {
  if (panelOpen.value && root.value && !root.value.contains(e.target as Node)) panelOpen.value = false;
}
function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape") panelOpen.value = false;
}
onMounted(() => {
  document.addEventListener("pointerdown", onDocDown);
  window.addEventListener("keydown", onKey);
});
onBeforeUnmount(() => {
  if (bumpTimer) clearTimeout(bumpTimer);
  document.removeEventListener("pointerdown", onDocDown);
  window.removeEventListener("keydown", onKey);
});
</script>

<template>
  <div ref="root" class="music-lane" data-music>
    <div v-if="film.music" class="bar tl-clip k-music" :class="{ selected: selected?.kind === 'music' }" data-music-bar
      :style="{ width: Math.max(timeToPx(total, pxPerSec), bed ? 420 : 160) + 'px' }" :title="bed ? label : name(film.music.file)"
      @pointerdown="emit('select', { kind: 'music', id: 'music' })">
      <Icon name="music" />
      <span v-if="bed" class="name tl-name" data-music-label>{{ label }}</span>
      <span v-else class="name tl-name">{{ name(film.music.file) }} · <span class="mono">{{ Math.round(film.music.volume * 100) }}%</span></span>
      <button v-if="bed" ref="optionsButton" type="button" class="btn sm" data-music-options :aria-expanded="panelOpen"
        @pointerdown.stop @click="togglePanel">Options</button>
      <input type="range" min="0" max="1" step="0.05" data-music-volume :value="film.music.volume"
        aria-label="Music volume" @input="onVolumeInput" @change="bed && volume($event)" @pointerdown.stop />
      <button type="button" class="btn sm" data-music-remove @pointerdown.stop @click="remove">Remove</button>
    </div>
    <div v-else class="empty-lane" data-empty-lane="music">
      <span class="none">No music</span> ·
      <button type="button" class="btn link add" data-empty-action="generate-music" :disabled="!moods.length"
        @click="generate">Generate music</button> ·
      <button type="button" class="btn link add" data-empty-action="add-music" @click="picker?.click()">Add music…</button>
    </div>
    <button v-if="film.music" type="button" class="btn ghost sm add" @click="picker?.click()">Replace…</button>
    <input ref="picker" type="file" accept="audio/*" data-music-file hidden @change="pick" />
    <span v-if="error" class="error" data-music-error>{{ error }}</span>
    <div v-if="panelOpen && bed" class="panel" data-music-panel role="dialog" aria-label="Music options"
      :style="panelPos">
      <label>Mood
        <select data-music-mood :value="bed.mood" @change="changeMood">
          <option v-for="m in moods" :key="m.name" :value="m.name">{{ m.label }}</option>
        </select>
      </label>
      <label>Tempo
        <input type="number" data-music-tempo :min="tempoRange[0]" :max="tempoRange[1]" step="1" :value="bed.tempo" @change="changeTempo" />
        <span class="unit">bpm</span>
      </label>
      <label>Key
        <select data-music-key :value="bed.key" @change="changeKey">
          <option v-for="k in catalog?.keys ?? []" :key="k" :value="k">{{ k }}</option>
        </select>
      </label>
      <label>Scale
        <select data-music-scale :value="bed.scale" @change="changeScale">
          <option v-for="s in catalog?.scales ?? []" :key="s" :value="s">{{ cap(s) }}</option>
        </select>
      </label>
      <label>Sound
        <select data-music-palette :value="bed.palette" @change="changePalette">
          <option v-for="p in catalog?.palettes ?? []" :key="p" :value="p">{{ cap(p) }}</option>
        </select>
      </label>
      <button type="button" class="btn sm" data-music-regenerate :disabled="busy" title="Same settings, a different melody" @click="regenerate">New variation</button>
    </div>
  </div>
</template>

<style scoped>
.music-lane { height: 28px; position: relative; display: flex; align-items: center; gap: var(--s2); }
.bar { position: relative; top: auto; flex: none; height: 28px; cursor: default; padding-right: var(--s2); }
.bar input[type="range"] { width: 90px; flex: none; }
.bar .tl-name { flex: 1 1 auto; }
.bar .btn { color: inherit; background: color-mix(in srgb, var(--surface) 70%, transparent); border-color: var(--edge); }
.bar [data-music-options] { margin-left: auto; }
.bar [data-music-options] + input[type="range"] { margin-left: 0; }
.bar > input[type="range"]:first-of-type { margin-left: auto; }
.error { font-size: var(--fs-sec); color: var(--warn); }
.panel { position: fixed; z-index: 40; display: grid; grid-template-columns: auto auto; gap: var(--s2) var(--s4); padding: var(--s3); background: var(--surface); color: var(--text);
  border: 1px solid var(--border-strong); border-radius: var(--r-card); box-shadow: var(--shadow); font-size: var(--fs-sec); }
.panel label { display: flex; align-items: center; justify-content: space-between; gap: var(--s2); color: var(--muted); }
.panel select, .panel input[type="number"] { font-size: var(--fs-sec); height: 24px; padding: 0 var(--s1); border: 1px solid var(--border-strong); border-radius: 6px;
  background: var(--surface); color: var(--text); }
.panel input[type="number"] { width: 64px; }
.panel .unit { color: var(--muted); }
.panel .btn { grid-column: 1 / -1; justify-self: start; }
</style>
