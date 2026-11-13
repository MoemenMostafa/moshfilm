<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as api from "../api";
import { chosenAspects } from "../runtime/aspect";
import { useFilm } from "../composables/useFilm";
import type { ExportStatus } from "../types";

const store = useFilm();
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const format = ref<"mp4" | "gif">("mp4");
const status = ref<ExportStatus | null>(null);
const failure = ref("");
let timer: ReturnType<typeof setInterval> | null = null;

const running = computed(() => status.value?.state === "running");
const shapes = computed(() => (store.film.value ? chosenAspects(store.film.value) : []));
const progress = computed(() => `Exporting ${status.value?.current ?? shapes.value.join(" + ")}…`);
const detail = computed(() => status.value?.progress ?? null);
const percent = computed(() => (detail.value ? Math.max(0, Math.min(100, Math.round(detail.value.percent))) : null));
// "16:9 · frames 412 / 1 380 · about 2 min left", "Building audio…", "Encoding 9:16…"
const num = (n: number): string => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, " "); // "1 380"
function left(s: number | null): string {
  if (s === null) return "";
  if (s < 10) return "a few seconds left";
  if (s < 60) return `about ${Math.round(s / 10) * 10} s left`;
  return `about ${Math.max(1, Math.round(s / 60))} min left`;
}
const line = computed(() => {
  const d = detail.value;
  if (!d) return progress.value;
  if (d.stage === "audio") return "Building audio…";
  if (d.stage === "encode") return `Encoding ${d.aspect}…`;
  return [d.aspect, `frames ${num(d.done)} / ${num(d.total)}`, left(d.eta_seconds)].filter(Boolean).join(" · ");
});

async function refresh(): Promise<void> {
  try {
    status.value = await api.getExport();
  } catch {
    /* an old server without export: the menu just stays idle */
  }
}

// the server has no push for export, so poll once a second while it runs
watch(running, (on) => {
  if (on && timer === null) timer = setInterval(() => void refresh(), 1000);
  if (!on && timer !== null) {
    clearInterval(timer);
    timer = null;
  }
});
// when an export ends (done or failed) the result opens by itself, so it is never missed with the menu closed
watch(() => status.value?.state, (now, before) => {
  if (before === "running" && (now === "done" || now === "error")) open.value = true;
});

async function start(): Promise<void> {
  if (running.value) return;
  failure.value = "";
  try {
    status.value = await api.startExport(format.value);
  } catch (e) {
    failure.value = e instanceof Error ? e.message : String(e);
    // 409: an export is already running (another tab, or before this page loaded): pick it up
    if (e instanceof api.ApiError && e.status === 409) await refresh();
  }
}

async function reveal(name: string): Promise<void> {
  try {
    await api.revealExport(name);
  } catch (e) {
    failure.value = e instanceof Error ? e.message : String(e);
  }
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape") open.value = false;
}
function onOutside(e: Event): void {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false;
}
onMounted(() => {
  void refresh();
  window.addEventListener("keydown", onKey);
  document.addEventListener("pointerdown", onOutside);
});
onBeforeUnmount(() => {
  if (timer !== null) clearInterval(timer);
  window.removeEventListener("keydown", onKey);
  document.removeEventListener("pointerdown", onOutside);
});

const fileUrl = (name: string): string => api.exportFileUrl(name);
const size = (n: number): string => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
defineExpose({ start });
</script>

<template>
  <div ref="root" class="export-menu">
    <button type="button" class="btn sm" data-export-button :class="{ on: open }" :aria-expanded="open"
      title="Render the film to a movie file" @click="open = !open">
      <span v-if="running" class="spinner" data-export-dot="running" aria-hidden="true"></span>
      <span v-if="running && percent !== null" class="pct" data-export-percent>{{ percent }}%</span>
      <span v-else-if="status?.state === 'done'" class="dot done" data-export-dot="done" title="Export finished"></span>
      <span v-else-if="status?.state === 'error'" class="dot error" data-export-dot="error" title="Export failed"></span>
      Export movie
    </button>
    <div v-if="open" class="popover" data-export-panel role="dialog" aria-label="Export movie">
      <div class="formats" role="group" aria-label="Format">
        <label v-for="f in (['mp4', 'gif'] as const)" :key="f"><input type="radio" name="export-format" :value="f"
          v-model="format" :data-export-format="f" :disabled="running" />{{ f === "mp4" ? "MP4" : "GIF" }}</label>
      </div>
      <p class="hint">{{ shapes.length > 1 ? `One file per shape: ${shapes.join(" and ")}.` : `Shape ${shapes[0] ?? ""}.` }}</p>
      <button type="button" class="btn sm primary" data-export-start :disabled="running" @click="start">Export</button>

      <p v-if="running" class="state" data-export-running role="status"><span class="spinner" aria-hidden="true"></span>{{ line }}</p>
      <div v-if="running && percent !== null" class="bar" data-export-bar role="progressbar" aria-label="Export progress"
        aria-valuemin="0" aria-valuemax="100" :aria-valuenow="percent" :aria-valuetext="`${percent}%`">
        <span class="fill" data-export-bar-fill :style="{ width: percent + '%' }"></span>
      </div>
      <p v-if="running && percent !== null" class="hint" data-export-percent-text>{{ percent }}% overall</p>
      <p v-if="failure" class="err" role="alert">{{ failure }}</p>
      <p v-if="status?.state === 'error'" class="err" data-export-error role="alert">{{ status.error }}</p>
      <ul v-if="status?.warnings?.length" class="warnings" data-export-warnings>
        <li v-for="w in status.warnings" :key="w">{{ w }}</li>
      </ul>
      <ul v-if="status?.state === 'done'" class="files" data-export-files>
        <li v-for="f in status.files" :key="f.name">
          <a :href="fileUrl(f.name)" :download="f.name" data-export-link>{{ f.name }}</a>
          <span class="meta">{{ f.aspect }} · {{ size(f.bytes) }}</span>
          <button type="button" class="btn ghost sm" data-export-reveal @click="reveal(f.name)">Show in folder</button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.export-menu { position: relative; }
.popover { position: absolute; right: 0; top: calc(100% + 6px); z-index: 20; width: 300px; padding: var(--s3); display: flex;
  flex-direction: column; gap: var(--s2); background: var(--surface); color: var(--text); border: 1px solid var(--border);
  border-radius: var(--r-card); box-shadow: var(--shadow); font-size: var(--fs-sec); }
.formats { display: flex; gap: var(--s3); }
.formats label { display: inline-flex; align-items: center; gap: 6px; }
.hint { margin: 0; color: var(--muted); }
.state { margin: 0; display: flex; align-items: center; gap: var(--s2); }
.err { margin: 0; color: var(--warn); }
.warnings { margin: 0; padding-left: var(--s4); color: var(--muted); max-height: 120px; overflow: auto; }
.files { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: var(--s1); }
.files li { display: flex; align-items: center; gap: var(--s2); flex-wrap: wrap; }
.meta { color: var(--muted); }
.dot { display: inline-block; width: 8px; height: 8px; margin-right: 6px; border-radius: 50%; }
.dot.done { background: var(--ok, #23a26d); }
.dot.error { background: var(--warn, #e5604d); }
.spinner { display: inline-block; width: 12px; height: 12px; margin-right: 6px; border: 2px solid var(--accent-soft); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; flex: none; }
.pct { margin-right: 6px; font-variant-numeric: tabular-nums; min-width: 3ch; text-align: right; }
.bar { height: 6px; border-radius: 3px; background: var(--accent-soft); overflow: hidden; }
.fill { display: block; height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.4s ease; }
@keyframes spin { to { transform: rotate(360deg); } }
/* reduced motion: no spinning, no sliding bar; the numbers carry the progress */
@media (prefers-reduced-motion: reduce) {
  .spinner { animation: none; border-top-color: var(--accent-soft); border-right-color: var(--accent); }
  .fill { transition: none; }
}
</style>
