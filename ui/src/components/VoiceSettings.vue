<script setup lang="ts">
import { computed, ref } from "vue";
import * as api from "../api";
import { useFilm } from "../composables/useFilm";
import Icon from "./Icon.vue";

const VOICES = ["en-US-AndrewNeural", "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural",
  "en-GB-RyanNeural", "en-GB-SoniaNeural"];
const RATES = ["-10%", "+0%", "+8%", "+15%", "+20%"];

const store = useFilm();
const voice = computed(() => store.film.value?.voice ?? { name: VOICES[0], rate: "+8%" });
const local = ref<{ text: string; error: boolean; busy: boolean } | null>(null); // this tab's own start/failure
const status = computed(() => store.voiceStatus.value ?? local.value);
const busy = computed(() => status.value?.busy ?? false);

async function change(name: string, rate: string): Promise<void> {
  try {
    await store.edit([{ op: "set_voice_settings", name, rate }]);
  } catch {
    /* the store already reports the problem */
  }
}

async function make(): Promise<void> {
  if (busy.value) return; // a second click while the first run is going does nothing
  store.voiceStatus.value = null;
  local.value = { text: "Starting…", error: false, busy: true };
  try {
    await api.synthesizeVoice(); // progress, errors and "done" arrive as voice events
  } catch (e) {
    local.value = { text: e instanceof Error ? e.message : String(e), error: true, busy: false };
  }
}

defineExpose({ make, busy });
</script>

<template>
  <div class="voice-settings">
    <label>Voice
      <select data-voice-name :value="voice.name" @change="change(($event.target as HTMLSelectElement).value, voice.rate)">
        <option v-for="v in VOICES" :key="v" :value="v">{{ v }}</option>
      </select>
    </label>
    <label>Rate
      <select data-voice-rate :value="voice.rate" @change="change(voice.name, ($event.target as HTMLSelectElement).value)">
        <option v-for="r in RATES" :key="r" :value="r">{{ r }}</option>
      </select>
    </label>
    <button type="button" class="btn sm" data-make-voice :disabled="busy" @click="make"><Icon name="mic" />Make voice</button>
    <span v-if="status" data-voice-status class="status" :class="{ error: status.error }">{{ status.text }}</span>
  </div>
</template>

<style scoped>
.voice-settings { display: flex; align-items: center; gap: var(--s2); font-size: var(--fs-sec); color: var(--muted); }
.voice-settings label { display: inline-flex; align-items: center; gap: 6px; }
select { font-size: var(--fs-sec); height: 24px; padding: 0 var(--s1); border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); color: var(--text); }
select:hover { background: var(--surface-2); }
.status { color: var(--muted); }
.status.error { color: var(--warn); }
</style>
