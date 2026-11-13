<script setup lang="ts">
import { onMounted, ref } from "vue";

const props = defineProps<{ value: string }>();
const emit = defineEmits<{ (e: "save", text: string): void; (e: "cancel"): void }>();

const draft = ref(props.value);
const input = ref<HTMLInputElement | null>(null);
let done = false; // Enter/Esc are followed by a blur when the box goes away: act once

onMounted(() => {
  input.value?.focus();
  input.value?.select();
});

function finish(save: boolean): void {
  if (done) return;
  done = true;
  const text = draft.value.trim();
  if (save && text && text !== props.value.trim()) emit("save", text);
  else emit("cancel"); // Esc, unchanged or empty: nothing to save
}

function onKey(e: KeyboardEvent): void {
  e.stopPropagation(); // Backspace, Delete and the like belong to the box, not the timeline shortcuts
  if (e.isComposing) return;
  if (e.key === "Enter") {
    e.preventDefault();
    finish(true);
  } else if (e.key === "Escape") {
    e.preventDefault();
    finish(false);
  }
}
</script>

<template>
  <input ref="input" v-model="draft" class="inline-edit" data-inline-edit type="text" aria-label="Edit text"
    @keydown="onKey" @blur="finish(true)" @pointerdown.stop @dblclick.stop @click.stop />
</template>

<style scoped>
.inline-edit { width: 100%; min-width: 240px; box-sizing: border-box; font: inherit; font-size: var(--fs-sec); padding: 0 var(--s2);
  height: 22px; border: 1px solid var(--accent); border-radius: 6px; background: var(--surface); color: var(--text); }
.inline-edit:focus-visible { outline-offset: 1px; }
</style>
