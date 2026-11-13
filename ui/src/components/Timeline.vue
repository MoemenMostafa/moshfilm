<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useFilm } from "../composables/useFilm";
import type { Selection } from "../types";
import { useSharedPlayhead } from "../composables/usePlayhead";
import { commentColor } from "../comments";
import { PACE_MAX, PACE_MIN, totalLength } from "../runtime/timing";
import { DEFAULT_PX_PER_SEC, MAX_PX_PER_SEC, MIN_PX_PER_SEC, pxToTime, timeToPx, trackDrag } from "../timelineMath";
import { isMac } from "../composables/useShortcuts";
import { useAudioSync, type SfxPlay, type VoiceClip } from "../composables/useAudioSync";
import { sfxSceneEnd, sfxStart } from "../runtime/sound";
import HistoryBar from "./HistoryBar.vue";
import Icon from "./Icon.vue";
import MusicLane from "./MusicLane.vue";
import SfxLane from "./SfxLane.vue";
import SceneLane from "./SceneLane.vue";
import TextLane from "./TextLane.vue";
import VoiceLane from "./VoiceLane.vue";
import VoiceSettings from "./VoiceSettings.vue";

const store = useFilm();
const head = useSharedPlayhead();
const pxPerSec = ref(DEFAULT_PX_PER_SEC);
const ZOOM_STEP = 1.1;
const GUTTER = 76; // lane label column, px

const film = computed(() => store.film.value);
const slots = computed(() => store.slots.value);
const total = computed(() => totalLength(slots.value));
const widthPx = computed(() => timeToPx(total.value, pxPerSec.value) + 80);

// Voice and music audio follow the shared playhead. A line with no cached audio (never made, or edited
// since) has no entry in store.voice, so it is silent until "Make voice" is run again.
const voiceClips = computed<VoiceClip[]>(() =>
  slots.value.flatMap((slot) => {
    const info = store.voice?.value?.[slot.id];
    return info ? [{ url: info.url, start: slot.voiceStart, speed: slot.voiceSpeed, duration: info.duration }] : [];
  }));
const musicBed = computed(() => {
  const m = film.value?.music;
  if (!m) return null;
  if (m.file) return { url: `/film/${m.file.split("/").map(encodeURIComponent).join("/")}`, volume: m.volume };
  // a generated bed: the server renders it as long as the film; its URL changes when the length does
  const url = store.sound?.value?.music?.url;
  return url ? { url, volume: m.volume } : null;
});
// Sound effects: each clip plays from its scene's start plus its offset, for as long as its audio lasts.
const sfxPlays = computed<SfxPlay[]>(() =>
  (film.value?.sfx ?? []).flatMap((c) => {
    const info = store.sound?.value?.sfx?.[c.id];
    if (!info || !slots.value.some((s) => s.id === c.scene)) return [];
    return [{ id: c.id, url: info.url, start: sfxStart(c, slots.value), duration: info.duration, volume: c.volume,
      end: sfxSceneEnd(c, slots.value) }];
  }));
useAudioSync(head, voiceClips, musicBed, sfxPlays);
const sfxDurations = computed<Record<string, number>>(() =>
  Object.fromEntries(Object.entries(store.sound?.value?.sfx ?? {}).map(([id, v]) => [id, v.duration])));

const markers = computed(() =>
  store.queue.value.items.filter((i) => i.kind === "comment" && i.time != null));
function pickMarker(id: string, time: number): void {
  head.seek(time);
  store.focusItem.value = id;
}

const confirmYes = ref<HTMLButtonElement | null>(null);
watch(() => store.pendingRemove.value, async (p) => {
  if (p) {
    await nextTick();
    confirmYes.value?.focus();
  }
});

function pick(sel: Selection): void {
  store.selectItem(sel.kind, sel.id);
}
/** A press on empty track space clears the selection. */
function onBodyDown(e: PointerEvent): void {
  if (!(e.target as HTMLElement | null)?.closest("[data-scene], [data-text], [data-voice], [data-voice-missing], [data-music-bar], [data-sfx], [data-sfx-toolbar], [data-sfx-menu], [data-music-panel]")) {
    store.clearSelection();
  }
}

const paceDraft = ref<number | null>(null);
const pace = computed(() => paceDraft.value ?? film.value?.pace ?? 1);
const paceLabel = computed(() => {
  const p = Number(pace.value.toFixed(2));
  return `Pace ${p}× ${p > 1 ? "(slower)" : p < 1 ? "(faster)" : "(normal)"}`;
});

async function run(ops: Record<string, unknown>[]): Promise<void> {
  try {
    await store.edit(ops as never);
  } catch {
    /* the store already reports the problem */
  }
}

async function releasePace(): Promise<void> {
  const p = paceDraft.value;
  if (p === null) return;
  await run([{ op: "set_pace", pace: p }]);
  paceDraft.value = null;
}

const ticks = computed(() => {
  const step = pxPerSec.value >= 80 ? 1 : pxPerSec.value >= 30 ? 2 : pxPerSec.value >= 15 ? 5 : 10;
  const out: number[] = [];
  for (let t = 0; t <= total.value + 1e-9; t += step) out.push(t);
  return out;
});

const ruler = ref<HTMLElement | null>(null);
function seekFromClientX(x: number): void {
  const left = ruler.value?.getBoundingClientRect().left ?? 0;
  head.seek(pxToTime(x - left, pxPerSec.value));
}
function startSeek(e: PointerEvent): void {
  seekFromClientX(e.clientX);
  trackDrag(e, (dx) => seekFromClientX(e.clientX + dx), () => {});
}

function setZoom(next: number): void {
  pxPerSec.value = Math.min(MAX_PX_PER_SEC, Math.max(MIN_PX_PER_SEC, next));
}
const ZOOM_BUTTON_STEP = 1.25;
const zoomIn = (): void => setZoom(pxPerSec.value * ZOOM_BUTTON_STEP);
const zoomOut = (): void => setZoom(pxPerSec.value / ZOOM_BUTTON_STEP);

function onWheel(e: WheelEvent): void {
  if (!(e.ctrlKey || e.metaKey)) return;
  e.preventDefault();
  setZoom(pxPerSec.value * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP));
}

// tips live behind a help button instead of an always-on hint line
const helpOpen = ref(false);
const helpRoot = ref<HTMLElement | null>(null);
const mac = isMac();
const mod = mac ? "⌘" : "Ctrl";
function onHelpKey(e: KeyboardEvent): void {
  if (e.key === "Escape") helpOpen.value = false;
}
function onHelpOutside(e: Event): void {
  if (helpOpen.value && helpRoot.value && !helpRoot.value.contains(e.target as Node)) helpOpen.value = false;
}
onMounted(() => {
  window.addEventListener("keydown", onHelpKey);
  document.addEventListener("pointerdown", onHelpOutside);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onHelpKey);
  document.removeEventListener("pointerdown", onHelpOutside);
});

const voiceSettings = ref<InstanceType<typeof VoiceSettings> | null>(null);
</script>

<template>
  <div v-if="film" class="timeline-root">
    <div class="head">
      <h4 class="title">Timeline</h4>
      <HistoryBar />
      <label class="pace">
        <span data-pace-label>{{ paceLabel }}</span>
        <input type="range" :min="PACE_MIN" :max="PACE_MAX" step="0.05" :value="pace"
          @input="paceDraft = Number(($event.target as HTMLInputElement).value)" @change="releasePace" />
      </label>
      <VoiceSettings ref="voiceSettings" />
      <button v-if="film.order_pinned" class="btn ghost sm order-pin" data-order-pin title="Scene order is pinned: click to unpin"
        @click="run([{ op: 'unpin', target: 'order' }])"><Icon name="pin" />order</button>
      <span class="zoom" role="group" aria-label="Zoom">
        <button type="button" class="btn icon ghost" data-zoom-out aria-label="Zoom out" title="Zoom out" :disabled="pxPerSec <= MIN_PX_PER_SEC"
          @click="zoomOut"><Icon name="minus" /></button>
        <input type="range" class="zoom-range" data-zoom-range :min="MIN_PX_PER_SEC" :max="MAX_PX_PER_SEC" step="1" :value="pxPerSec"
          aria-label="Zoom" @input="setZoom(Number(($event.target as HTMLInputElement).value))" />
        <button type="button" class="btn icon ghost" data-zoom-in aria-label="Zoom in" title="Zoom in" :disabled="pxPerSec >= MAX_PX_PER_SEC"
          @click="zoomIn"><Icon name="plus" /></button>
      </span>
      <span ref="helpRoot" class="help">
        <button type="button" class="btn icon ghost" :class="{ on: helpOpen }" data-help-toggle aria-label="Shortcuts and tips"
          title="Shortcuts and tips" :aria-expanded="helpOpen" @click="helpOpen = !helpOpen"><Icon name="help" /></button>
        <div v-if="helpOpen" class="tips" data-help role="dialog" aria-label="Shortcuts and tips">
          <h5>Timeline tips</h5>
          <dl>
            <dt><kbd class="kbd">Shift</kbd> while dragging</dt><dd>no snapping</dd>
            <dt><kbd class="kbd">{{ mod }}</kbd> + wheel</dt><dd>zoom the timeline</dd>
            <dt>Double-click a clip</dt><dd>edit its words</dd>
            <dt><kbd class="kbd">Space</kbd></dt><dd>play or pause</dd>
            <dt><kbd class="kbd">C</kbd></dt><dd>pin a comment on the frame</dd>
            <dt><kbd class="kbd">←</kbd> <kbd class="kbd">→</kbd></dt><dd>step 1 s (<kbd class="kbd">Shift</kbd> 0.1 s)</dd>
            <dt><kbd class="kbd">Delete</kbd></dt><dd>remove the selected clip</dd>
            <dt><kbd class="kbd">{{ mod }}</kbd> <kbd class="kbd">Z</kbd></dt><dd>undo (add <kbd class="kbd">Shift</kbd> to redo)</dd>
          </dl>
        </div>
      </span>
    </div>
    <div class="body" data-timeline-body @wheel="onWheel" @pointerdown="onBodyDown">
      <div class="inner" :style="{ width: GUTTER + widthPx + 'px' }">
        <div class="row">
          <div class="label"></div>
          <div ref="ruler" class="ruler" data-ruler :style="{ width: widthPx + 'px' }" @pointerdown.prevent="startSeek">
            <span v-for="t in ticks" :key="t" class="tick" :style="{ left: timeToPx(t, pxPerSec) + 'px' }">{{ t }}s</span>
            <button v-for="m in markers" :key="m.id" type="button" class="marker" :data-marker="m.id" :title="m.text"
              :style="{ left: timeToPx(m.time!, pxPerSec) + 'px', background: commentColor(m.state) }"
              @pointerdown.stop @click.stop="pickMarker(m.id, m.time!)"></button>
          </div>
        </div>
        <div class="row"><div class="label tall"><Icon name="scenes" />Scenes</div>
          <div class="track" :style="{ width: widthPx + 'px' }">
            <SceneLane :film="film" :slots="slots" :px-per-sec="pxPerSec" :selected="store.selection.value"
              @edit="run" @select="pick" @remove="store.requestRemove($event)" /></div></div>
        <div class="row"><div class="label"><Icon name="text" />Text</div>
          <div class="track" :style="{ width: widthPx + 'px' }">
            <TextLane :film="film" :slots="slots" :px-per-sec="pxPerSec" :selected="store.selection.value"
              @edit="run" @select="pick" @remove="store.requestRemove($event)" /></div></div>
        <div class="row"><div class="label"><Icon name="mic" />Voice</div>
          <div class="track" :style="{ width: widthPx + 'px' }">
            <VoiceLane :film="film" :slots="slots" :durations="store.voiceDurations.value" :px-per-sec="pxPerSec"
              :selected="store.selection.value" @edit="run" @select="pick" @remove="store.requestRemove($event)" @make-voice="voiceSettings?.make()" :making="voiceSettings?.busy ?? false" /></div></div>
        <div class="row"><div class="label"><Icon name="sound" />Sound</div>
          <div class="track" :style="{ width: widthPx + 'px' }">
            <SfxLane :film="film" :slots="slots" :px-per-sec="pxPerSec" :selected="store.selection.value"
              :durations="sfxDurations" :catalog="store.catalog?.value ?? null" :playhead="head.time.value"
              @edit="run" @select="pick" @remove="store.requestRemove($event)" /></div></div>
        <div class="row"><div class="label"><Icon name="music" />Music</div>
          <div class="track" :style="{ width: widthPx + 'px' }">
            <MusicLane :film="film" :total="total" :px-per-sec="pxPerSec" :selected="store.selection.value"
              :catalog="store.catalog?.value ?? null" :busy="store.soundBusy?.value ?? false" @edit="run" @select="pick" /></div></div>
        <div class="playhead" data-playhead :style="{ left: GUTTER + timeToPx(head.time.value, pxPerSec) + 'px' }"></div>
      </div>
    </div>
  </div>
  <div v-else class="timeline-root empty">Loading…</div>
  <div v-if="store.pendingRemove.value" class="confirm-back" @keydown.esc="store.cancelRemove()">
    <div class="confirm" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" data-confirm>
      <p id="confirm-title"><strong>Remove scene "{{ store.pendingRemove.value.title }}"?</strong></p>
      <p class="detail">
        The timeline closes the gap<template v-if="store.pendingRemove.value.hasVoice || store.pendingRemove.value.captions">;
          <template v-if="store.pendingRemove.value.hasVoice">its voice line</template><template
            v-if="store.pendingRemove.value.hasVoice && store.pendingRemove.value.captions"> and </template><template
            v-if="store.pendingRemove.value.captions">{{ store.pendingRemove.value.captions }} caption{{ store.pendingRemove.value.captions > 1 ? "s" : "" }}</template>
          go with it</template>. You can undo this.
      </p>
      <div class="actions">
        <button type="button" class="btn" data-confirm-no @click="store.cancelRemove()">Cancel</button>
        <button type="button" class="btn danger" data-confirm-yes ref="confirmYes" @click="store.confirmRemove()">Remove scene</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline-root { display: flex; flex-direction: column; flex: 1; min-height: 0; color: var(--text); }
.head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s1) var(--s3); padding: 0 0 var(--s2); font-size: var(--fs-sec); }
.title { margin: 0; font-size: var(--fs-sec); letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
.pace { display: flex; align-items: center; gap: var(--s2); color: var(--muted); }
.pace input { width: 96px; }
.zoom { display: inline-flex; align-items: center; gap: var(--s1); margin-left: auto; }
.zoom-range { width: 80px; }
.help { position: relative; }
.tips { position: absolute; bottom: 100%; right: 0; z-index: 20; width: 280px; margin-bottom: var(--s1); padding: var(--s3); background: var(--surface);
  color: var(--text); border: 1px solid var(--border-strong); border-radius: var(--r-card); box-shadow: var(--shadow); }
.tips h5 { margin: 0 0 var(--s2); font-size: var(--fs-body); }
.tips dl { display: grid; grid-template-columns: auto 1fr; gap: var(--s1) var(--s3); margin: 0; font-size: var(--fs-sec); }
.tips dt { white-space: nowrap; }
.tips dd { margin: 0; color: var(--muted); }
.body { flex: 1; min-height: 0; overflow: auto; }
.inner { position: relative; padding-top: var(--s1); }
.row { display: flex; align-items: flex-start; margin-bottom: var(--s1); }
.label { flex: none; box-sizing: border-box; width: 76px; position: sticky; left: 0; z-index: 3; background: var(--bg); display: flex; align-items: center; gap: 6px;
  height: 28px; padding-right: var(--s2); font-size: var(--fs-sec); font-weight: 600; color: var(--muted); }
.label.tall { height: 44px; }
.ruler { position: relative; height: 18px; border-bottom: 1px solid var(--border); cursor: pointer; }
.tick { position: absolute; top: 2px; height: 14px; line-height: 14px; font-size: var(--fs-meta); color: var(--muted); padding-left: var(--s1);
  border-left: 1px solid var(--border-strong); font-variant-numeric: tabular-nums; }
.marker { position: absolute; bottom: 1px; width: 10px; height: 10px; margin-left: -5px; padding: 0; border: 1px solid var(--surface); border-radius: 50%; cursor: pointer; z-index: 2; }
.marker:focus-visible { outline-offset: 1px; }
.track { position: relative; }
.playhead { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--playhead); pointer-events: none; z-index: 4; }
.playhead::before { content: ""; position: absolute; top: 0; left: -5px; border: 6px solid transparent; border-top-color: var(--playhead); border-bottom: 0; }
.confirm-back { position: fixed; inset: 0; z-index: 50; background: var(--scrim); display: flex; align-items: center; justify-content: center; }
.confirm { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-card); padding: var(--s4) var(--s5); max-width: 380px; box-shadow: var(--shadow); color: var(--text); font-size: var(--fs-body); }
.confirm p { margin: 0 0 var(--s2); }
.confirm .detail { color: var(--muted); font-size: var(--fs-sec); }
.confirm .actions { display: flex; justify-content: flex-end; gap: var(--s2); margin-top: var(--s3); }
.empty { padding: var(--s3); color: var(--muted); }
</style>
