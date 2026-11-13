<script setup lang="ts">
// One inline SVG icon set (16px grid, currentColor) so icons follow the theme and look the same on every OS.
import { computed } from "vue";

const PATHS = {
  prev: "M3 2h2v12H3zM13 2v12L6 8z",
  play: "M4 2.5v11l9-5.5z",
  pause: "M4 2h3v12H4zM9 2h3v12H9z",
  next: "M11 2h2v12h-2zM3 2l7 6-7 6z",
  comment: "M2 3h12v8H7l-3 3v-3H2z",
  eye: "M8 3C4.5 3 2 6 1 8c1 2 3.5 5 7 5s6-3 7-5c-1-2-3.5-5-7-5zm0 8a3 3 0 110-6 3 3 0 010 6z",
  help: "M8 1a7 7 0 100 14A7 7 0 008 1zm-.8 10.5v-1.7h1.6v1.7zM8 4a2.5 2.5 0 011 4.8c-.4.2-.5.4-.5.9H7c0-1.2.5-1.6 1-1.9.4-.2.5-.4.5-.8A1 1 0 008 5.1c-.6 0-1 .4-1 1H5.6A2.5 2.5 0 018 4z",
  attach: "M5 8l4-4a2.5 2.5 0 013.5 3.5L7.5 12.5a4 4 0 01-5.6-5.6L7 2",
  star: "M8 1l2 4 4 .6-3 3 .8 4.2L8 10.7 4.2 12.8 5 8.6 2 5.6 6 5z",
  pin: "M9.5 1.5l5 5-2 .6-2.2 2.2.4 3.4-1 1-2.7-2.7L3.5 14.5l-.9-.9 3.5-3.5L3.4 7.4l1-1 3.4.4L10 4.6z",
  send: "M1 2l14 6-14 6 2-6z",
  minus: "M2 7h12v2H2z",
  plus: "M7 2h2v5h5v2H9v5H7V9H2V7h5z",
  close: "M3.5 2.3L8 6.8l4.5-4.5 1.2 1.2L9.2 8l4.5 4.5-1.2 1.2L8 9.2l-4.5 4.5-1.2-1.2L6.8 8 2.3 3.5z",
  scenes: "M2 3h12v10H2zM4 5v6h8V5z",
  text: "M3 3h10v2H9v8H7V5H3z",
  mic: "M8 1a2.5 2.5 0 00-2.5 2.5v4a2.5 2.5 0 005 0v-4A2.5 2.5 0 008 1zM3.5 7a4.5 4.5 0 009 0h-1.5a3 3 0 01-6 0z",
  music: "M6 2v8.2A2.5 2.5 0 104 12.5V5l8-2v6.2A2.5 2.5 0 1010 11.5V2z",
  sound: "M2 6h3l4-3.5v11L5 10H2zM10.5 5.2l1-.9a4.5 4.5 0 010 7.4l-1-.9a3.3 3.3 0 000-5.6z",
  undo: "M6 3L2 7l4 4V8c3 0 5 1 6 4 0-4-2-7-6-7z",
  redo: "M10 3l4 4-4 4V8c-3 0-5 1-6 4 0-4 2-7 6-7z",
  history: "M8 2a6 6 0 11-5.7 4H4a4.5 4.5 0 104.5-3.5V5.5L5.5 3 8.5.5V2zM7.3 5h1.4v3.3l2.2 1.3-.7 1.2-2.9-1.7z",
  check: "M6.2 11.6L2.6 8l1.2-1.2 2.4 2.4 6-6 1.2 1.2z",
  chevron: "M5 3l5 5-5 5z",
  info: "M8 1a7 7 0 100 14A7 7 0 008 1zM7.2 7h1.6v5H7.2zm0-2.6h1.6V6H7.2z",
} as const;

export type IconName = keyof typeof PATHS;
const props = defineProps<{ name: IconName }>();
const d = computed(() => PATHS[props.name]);
</script>

<template>
  <svg class="ico" viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path :d="d" /></svg>
</template>
