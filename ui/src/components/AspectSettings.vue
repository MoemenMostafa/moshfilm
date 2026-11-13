<script setup lang="ts">
import { computed } from "vue";
import { useFilm } from "../composables/useFilm";
import { ALL_ASPECTS, mainAspect } from "../runtime/aspect";
import type { Aspect } from "../types";

const store = useFilm();
const main = computed<Aspect>(() => (store.film.value ? mainAspect(store.film.value) : "16:9"));
const second = computed<Aspect | "">(() => store.film.value?.second_aspect ?? "");

async function change(aspect: Aspect, second_aspect: Aspect | null): Promise<void> {
  try {
    await store.edit([{ op: "set_aspects", aspect, second_aspect }]);
  } catch {
    /* the store already reports the problem */
  }
}

// picking the current second shape as the main one swaps them, so the request is never rejected
function pickMain(a: Aspect): void {
  void change(a, a === second.value ? main.value : second.value || null);
}
function pickSecond(v: string): void {
  void change(main.value, (v || null) as Aspect | null);
}
</script>

<template>
  <div class="aspect-settings">
    <label>Shape
      <select data-aspect-main :value="main" @change="pickMain(($event.target as HTMLSelectElement).value as Aspect)">
        <option v-for="a in ALL_ASPECTS" :key="a" :value="a">{{ a }}</option>
      </select>
    </label>
    <label>Second
      <select data-aspect-second :value="second" title="A second shape uses the same timeline and narration"
        @change="pickSecond(($event.target as HTMLSelectElement).value)">
        <option value="">None</option>
        <option v-for="a in ALL_ASPECTS" :key="a" :value="a" :disabled="a === main">{{ a }}</option>
      </select>
    </label>
  </div>
</template>

<style scoped>
.aspect-settings { display: flex; align-items: center; gap: var(--s2); font-size: var(--fs-sec); color: var(--muted); }
.aspect-settings label { display: inline-flex; align-items: center; gap: 6px; }
select { font-size: var(--fs-sec); height: 24px; padding: 0 var(--s1); border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
select:hover { background: var(--surface-2); }
</style>
