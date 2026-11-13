<script setup lang="ts">
import { computed, onBeforeUnmount } from "vue";
import { installShortcuts } from "./composables/useShortcuts";
import AspectSettings from "./components/AspectSettings.vue";
import ClaudePanel from "./components/ClaudePanel.vue";
import ExportMenu from "./components/ExportMenu.vue";
import PreviewPane from "./components/PreviewPane.vue";
import ThemeSwitch from "./components/ThemeSwitch.vue";
import Timeline from "./components/Timeline.vue";
import { createFilmStore, provideFilm } from "./composables/useFilm";
import { createFollow, provideFollow } from "./composables/useFollow";
import { providePlayhead, usePlayhead } from "./composables/usePlayhead";
import { totalLength } from "./runtime/timing";
import { initTheme } from "./theme";

initTheme();
const store = createFilmStore();
const playhead = usePlayhead(computed(() => totalLength(store.slots.value)));
provideFilm(store);
providePlayhead(playhead);
provideFollow(createFollow(store, playhead));
const stopShortcuts = installShortcuts({
  undo: () => void store.undo(),
  redo: () => void store.redo(),
  remove: () => void store.requestRemove(),
});
const filmLength = computed(() => {
  const t = Math.round(totalLength(store.slots.value));
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
});
onBeforeUnmount(() => {
  store.unsubscribe();
  stopShortcuts();
});
</script>

<template>
  <div class="editor">
    <div v-if="store.error.value" class="banner" role="alert" data-region="banner">
      {{ store.error.value }}
    </div>
    <header class="top" data-region="top">
      <span class="brand">mosh<i>Film</i></span>
      <span v-if="store.film.value" class="film" data-testid="film-name">{{ store.film.value.title }} · <span class="mono">{{ filmLength }}</span></span>
      <AspectSettings class="push" />
      <ExportMenu />
      <ThemeSwitch />
    </header>
    <div class="grid">
      <div class="preview" data-region="preview"><PreviewPane /></div>
      <aside class="panel" data-region="panel"><ClaudePanel /></aside>
      <div class="timeline" data-region="timeline"><Timeline /></div>
    </div>
  </div>
</template>

<style>
.editor { display: flex; flex-direction: column; height: 100%; }
.banner { padding: 8px 16px; background: var(--danger); color: var(--on-danger); font-weight: 600; }
.top { display: flex; align-items: center; gap: var(--s3); padding: var(--s2) var(--s3); background: var(--surface); border-bottom: 1px solid var(--border); }
.brand { font-weight: 700; letter-spacing: -0.01em; }
.brand i { font-style: normal; color: var(--accent); }
.film { color: var(--muted); font-size: var(--fs-sec); }
.top .push { margin-left: auto; }
.grid {
  flex: 1; min-height: 0; display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  grid-template-rows: minmax(0, 1fr) minmax(248px, auto);
  grid-template-areas: "preview panel" "timeline timeline";
}
.preview { grid-area: preview; min-width: 0; min-height: 0; }
.panel { grid-area: panel; padding: var(--s3); border-left: 1px solid var(--border); background: var(--surface); min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.panel > * { flex: 1; min-height: 0; }
.timeline { grid-area: timeline; padding: var(--s2) var(--s3) var(--s3); border-top: 1px solid var(--border); background: var(--bg); min-height: 0; max-height: 44vh; position: relative; z-index: 5; display: flex; flex-direction: column; }
</style>
