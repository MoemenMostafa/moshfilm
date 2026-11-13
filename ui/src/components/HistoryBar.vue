<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useFilm } from "../composables/useFilm";
import { isMac } from "../composables/useShortcuts";
import Icon from "./Icon.vue";

const store = useFilm();
const open = ref(false);
const root = ref<HTMLElement | null>(null);

const mac = isMac();
const undoHint = mac ? "Undo (⌘Z)" : "Undo (Ctrl+Z)";
const redoHint = mac ? "Redo (⇧⌘Z)" : "Redo (Ctrl+Shift+Z)";

/** Newest first, so the latest step is under the button. */
const rows = computed(() => [...store.history.value.steps].reverse());

function clock(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

async function jump(id: number): Promise<void> {
  open.value = false;
  await store.jumpHistory(id);
}

function onKey(e: KeyboardEvent): void {
  if (e.key === "Escape") open.value = false;
}
function onOutside(e: Event): void {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false;
}
onMounted(() => {
  window.addEventListener("keydown", onKey);
  document.addEventListener("pointerdown", onOutside);
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  document.removeEventListener("pointerdown", onOutside);
});
</script>

<template>
  <div ref="root" class="history-bar">
    <button type="button" class="btn icon ghost" data-undo :disabled="!store.history.value.can_undo" :title="undoHint" :aria-label="undoHint"
      @click="store.undo()"><Icon name="undo" /></button>
    <button type="button" class="btn icon ghost" data-redo :disabled="!store.history.value.can_redo" :title="redoHint" :aria-label="redoHint"
      @click="store.redo()"><Icon name="redo" /></button>
    <button type="button" class="btn ghost sm" :class="{ on: open }" data-history-toggle :aria-expanded="open" title="Show what you and Claude changed"
      @click="open = !open"><Icon name="history" />History</button>
    <div v-if="open" class="popover" data-history-list role="listbox" aria-label="History">
      <p v-if="rows.length <= 1" class="none">Nothing to undo yet.</p>
      <button v-for="s in rows" :key="s.id" type="button" class="step" role="option" :data-step="s.id"
        :aria-selected="s.current" :class="[s.kind, { current: s.current, future: s.future }]" @click="jump(s.id)">
        <span class="label">{{ s.label }}</span>
        <span class="when mono">{{ s.current ? "now" : clock(s.time) }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.history-bar { position: relative; display: flex; gap: var(--s1); align-items: center; }
.popover { position: absolute; bottom: 100%; left: 0; z-index: 20; width: 320px; max-height: 280px; overflow: auto; margin-bottom: var(--s1);
  background: var(--surface); color: var(--text); border: 1px solid var(--border-strong); border-radius: var(--r-ctl); box-shadow: var(--shadow);
  padding: var(--s1); display: flex; flex-direction: column; }
.step { display: flex; justify-content: space-between; gap: var(--s3); text-align: left; border: 0; background: none; padding: 6px var(--s2);
  border-radius: 6px; font-size: var(--fs-sec); cursor: pointer; color: var(--text); }
.step:hover { background: var(--surface-2); }
.step:focus-visible { outline-offset: -2px; }
.step.current { background: var(--accent-soft); font-weight: 600; }
.step.future { color: var(--muted); font-style: italic; }
.step.claude .label { color: var(--accent); }
.when { color: var(--muted); flex: none; font-size: var(--fs-meta); }
.none { margin: var(--s2); font-size: var(--fs-sec); color: var(--muted); }
</style>
