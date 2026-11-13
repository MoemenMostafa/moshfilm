<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { chosenAspects } from "../runtime/aspect";
import { createPlayer, type Player } from "../runtime/player";
import { useAspectView } from "../composables/useAspectView";
import { useFilm } from "../composables/useFilm";
import { useFollow } from "../composables/useFollow";
import { useSharedPlayhead } from "../composables/usePlayhead";
import CommentLayer from "./CommentLayer.vue";
import Icon from "./Icon.vue";

const store = useFilm();
const head = useSharedPlayhead();
const follow = useFollow();
const shape = useAspectView();
const pane = ref<HTMLElement | null>(null);
const stage = ref<HTMLElement | null>(null);
/** Comment mode: the next click on the frame pins a comment there. */
const commenting = ref(false);
function toggleComment(): void {
  commenting.value = !commenting.value;
  if (commenting.value) head.pause();
}
const frame = ref({ width: 0, height: 0 });
let player: Player | null = null;
let resizer: ResizeObserver | null = null;

// The stage is anchored top-left, so the frame is sized to the film's aspect ratio and centred (letterbox).
function resize(): void {
  const f = store.film.value;
  const el = pane.value;
  if (!f || !el || el.clientWidth === 0 || el.clientHeight === 0) return;
  const { width, height } = shape.size.value;
  const k = Math.min(el.clientWidth / width, el.clientHeight / height);
  frame.value = { width: Math.floor(width * k), height: Math.floor(height * k) };
}

const voiceMap = () => store.voiceDurations.value;

async function ensurePlayer(): Promise<void> {
  const film = store.film.value;
  if (!film || !stage.value) return;
  if (!player) {
    player = createPlayer(stage.value, {
      film, voice: voiceMap(), aspect: shape.aspect.value, sceneUrl: (s) => `/film/${s.file}`,
      versionOf: (s) => store.sceneVersions.value[s.id],
    });
    await player.load();
  } else {
    await player.update(film, voiceMap());
  }
  resize();
  player?.seek(head.time.value); // gone if the pane was closed while loading
}

watch([store.film, store.voiceDurations], () => void ensurePlayer(), { deep: false });
// switching shape redraws every scene at the new size, then the frame is resized to match
watch(shape.aspect, async (a) => {
  const p = player;
  if (!p) return;
  resize(); // the frame takes the new shape's box at once; loading the scenes can take a moment
  await p.setAspect(a);
  resize();
  if (player === p) p.seek(head.time.value);
});
watch(head.time, (t) => player?.seek(t));
watch(store.sceneVersions, (now, before) => {
  for (const [id, v] of Object.entries(now)) {
    if (before?.[id] !== v) void player?.reloadScene(id, v);
  }
});

const shapes = computed(() => (store.film.value ? chosenAspects(store.film.value) : []));
const mainShape = computed(() => shapes.value[0] ?? "16:9");
const secondShape = computed(() => shapes.value[1] ?? "");

const total = computed(() => store.slots.value.reduce((m, s) => Math.max(m, s.start + s.length), 0));

function fmt(t: number): string {
  const tenths = Math.floor(Math.max(t, 0) * 10 + 1e-6);
  const m = Math.floor(tenths / 600);
  const s = (tenths - m * 600) / 10;
  return `${m}:${s < 10 ? "0" : ""}${s.toFixed(1)}`;
}

/** Where each scene starts, as a percentage of the film (for the seams on the scrubber; the first one is the left edge). */
const seams = computed(() => total.value > 0
  ? store.slots.value.slice(1).map((s) => ({ id: s.id, pct: (s.start / total.value) * 100 })) : []);
const pct = computed(() => (total.value > 0 ? Math.min(100, (head.time.value / total.value) * 100) : 0));

/** Previous scene: restart the current one, or step back if we are already at its start. */
function prevScene(): void {
  const slots = store.slots.value;
  const t = head.time.value;
  let i = slots.length - 1;
  while (i > 0 && slots[i].start > t) i--;
  const here = slots[i];
  if (!here) { head.seek(0); return; }
  head.seek(t - here.start > 0.5 || i === 0 ? here.start : slots[i - 1].start);
}
function nextScene(): void {
  const next = store.slots.value.find((s) => s.start > head.time.value + 1e-6);
  head.seek(next ? next.start : total.value);
}

function onKey(e: KeyboardEvent): void {
  const target = e.target as HTMLElement | null;
  if (target?.closest("textarea, select, [contenteditable]")) return;
  const input = target?.closest("input");
  // typing in a text box keeps its keys; only the preview's own scrub bar lets keys through (zoom and pace sliders keep theirs)
  if (input && !input.classList.contains("scrub")) return;
  // a focused button owns Space/Enter (its click); arrows still seek
  if (target?.tagName === "BUTTON" && (e.key === " " || e.key === "Enter")) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "c" || e.key === "C") {
    e.preventDefault();
    toggleComment();
  } else if (e.key === " ") {
    e.preventDefault();
    head.toggle();
  } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    const step = (e.shiftKey ? 0.1 : 1) * (e.key === "ArrowLeft" ? -1 : 1);
    head.seek(head.time.value + step);
  }
}

onMounted(() => {
  window.addEventListener("keydown", onKey);
  if (typeof ResizeObserver !== "undefined" && pane.value) {
    resizer = new ResizeObserver(resize);
    resizer.observe(pane.value);
  }
  void ensurePlayer();
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  resizer?.disconnect();
  player?.destroy();
  player = null;
});
</script>

<template>
  <section class="preview">
    <div class="pane">
      <div ref="pane" class="fit">
        <div class="frame" :style="{ width: frame.width + 'px', height: frame.height + 'px' }">
          <div ref="stage" class="stage" data-testid="stage"></div>
          <CommentLayer :active="commenting" @done="commenting = false" />
        </div>
      </div>
    </div>
    <div class="controls">
      <button type="button" class="btn icon ghost" data-testid="prev-scene" aria-label="Previous scene" title="Previous scene"
        @click="prevScene"><Icon name="prev" /></button>
      <button type="button" class="btn icon primary play" :aria-label="head.playing.value ? 'Pause' : 'Play'"
        :title="head.playing.value ? 'Pause (Space)' : 'Play (Space)'" @click="head.toggle()">
        <Icon :name="head.playing.value ? 'pause' : 'play'" />
      </button>
      <button type="button" class="btn icon ghost" data-testid="next-scene" aria-label="Next scene" title="Next scene"
        @click="nextScene"><Icon name="next" /></button>
      <div class="scrub-wrap" :style="{ '--pct': pct + '%' }">
        <input class="scrub" type="range" min="0" step="0.01" :max="total" :value="head.time.value"
          aria-label="Scrub" @input="head.seek(Number(($event.target as HTMLInputElement).value))" />
        <i v-for="s in seams" :key="s.id" class="seam" data-testid="seam" :style="{ left: s.pct + '%' }"></i>
      </div>
      <span class="readout mono"><b>{{ fmt(head.time.value) }}</b> / {{ fmt(total) }}</span>
      <span class="divider" aria-hidden="true"></span>
      <div v-if="shape.hasSecond.value" class="aspect-switch" role="group" aria-label="Preview shape" data-testid="aspect-switch">
        <button v-for="v in (['main', 'second'] as const)" :key="v" type="button" class="btn sm ghost seg"
          :class="{ on: shape.view.value === v }" :aria-pressed="shape.view.value === v" :data-aspect-view="v"
          :title="v === 'main' ? 'Main shape' : 'Second shape'" @click="shape.set(v)">
          {{ v === 'main' ? mainShape : secondShape }}</button>
      </div>
      <button type="button" class="btn comment" :class="{ on: commenting }" :aria-pressed="commenting" data-testid="comment-btn"
        aria-label="Comment" title="Pin a comment on the frame (C)" @click="toggleComment">
        <Icon name="comment" /><span class="lbl">Comment</span></button>
      <button v-if="follow" type="button" class="btn follow" :class="{ on: follow.enabled.value }"
        :aria-pressed="follow.enabled.value" data-testid="follow-btn" aria-label="Follow Claude"
        title="Jump to the scene Claude is editing and play it once after the change" @click="follow.toggle()">
        <Icon name="eye" /><span class="lbl">Follow Claude</span></button>
    </div>
  </section>
</template>

<style scoped>
.preview { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; background: var(--stage-bg); }
.pane { position: relative; flex: 1; min-height: 0; }
.fit { position: absolute; inset: var(--s4); display: flex; align-items: center; justify-content: center; overflow: hidden; }
.frame { position: relative; flex: none; background: #fff; border-radius: 6px; overflow: hidden;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.08), 0 8px 24px rgba(0, 0, 0, 0.45); }
.stage { position: absolute; inset: 0; overflow: hidden; }
.controls { display: flex; align-items: center; gap: var(--s2); padding: var(--s2) var(--s3); background: var(--ctrl-bg);
  border-top: 1px solid var(--border); color: var(--text); font-size: var(--fs-sec); }
.aspect-switch { display: inline-flex; gap: 2px; padding: 2px; border: 1px solid var(--border); border-radius: var(--r-card); }
.seg.on { background: var(--accent); color: #fff; }
.divider { width: 1px; height: 20px; background: var(--border); }
.readout { white-space: nowrap; color: var(--muted); font-size: var(--fs-sec); }
.readout b { color: var(--text); font-weight: 600; }
.lbl { display: none; }
@media (min-width: 1100px) { .lbl { display: inline; } }

.scrub-wrap { position: relative; flex: 1; min-width: 40px; height: 20px; display: flex; align-items: center; }
.scrub { appearance: none; -webkit-appearance: none; width: 100%; height: 20px; margin: 0; background: transparent; cursor: pointer; }
.scrub::-webkit-slider-runnable-track { height: 6px; border-radius: 3px; border: 1px solid var(--border);
  background: linear-gradient(to right, var(--accent) var(--pct), var(--surface-2) var(--pct)); }
.scrub::-moz-range-track { height: 6px; border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); }
.scrub::-moz-range-progress { height: 6px; border-radius: 3px; background: var(--accent); }
.scrub::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; margin-top: -5px; border-radius: 50%;
  background: var(--accent); border: 2px solid var(--ctrl-bg); box-shadow: 0 0 0 1px var(--accent); }
.scrub::-moz-range-thumb { width: 10px; height: 10px; border-radius: 50%; background: var(--accent); border: 2px solid var(--ctrl-bg); box-shadow: 0 0 0 1px var(--accent); }
.scrub:hover::-webkit-slider-thumb { background: var(--accent-hover); }
.scrub:focus-visible { outline: none; }
.scrub:focus-visible::-webkit-slider-thumb { box-shadow: 0 0 0 2px var(--focus), 0 0 0 4px var(--ctrl-bg), 0 0 0 6px var(--focus); }
.scrub:focus-visible::-moz-range-thumb { box-shadow: 0 0 0 2px var(--focus), 0 0 0 4px var(--ctrl-bg), 0 0 0 6px var(--focus); }
.seam { position: absolute; top: 3px; width: 2px; height: 14px; margin-left: -1px; background: var(--border-strong); opacity: 0.7; pointer-events: none; }
</style>
