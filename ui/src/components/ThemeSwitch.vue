<script setup lang="ts">
import { THEME_MODES, useTheme, type ThemeMode } from "../theme";

const theme = useTheme();
const label = (m: ThemeMode): string => m[0].toUpperCase() + m.slice(1);
</script>

<template>
  <div class="seg" role="group" aria-label="Theme" data-theme-switch>
    <button v-for="m in THEME_MODES" :key="m" type="button" :data-theme-option="m" :aria-pressed="theme.mode.value === m"
      @click="theme.set(m)">{{ label(m) }}</button>
  </div>
</template>

<style scoped>
.seg { display: inline-flex; border: 1px solid var(--border-strong); border-radius: var(--r-ctl); overflow: hidden; background: var(--surface); }
.seg button { border: 0; background: none; padding: 4px 12px; font-size: var(--fs-sec); color: var(--text); cursor: pointer; }
.seg button:hover:not([aria-pressed="true"]) { background: var(--surface-2); }
.seg button[aria-pressed="true"] { background: var(--accent); color: var(--on-accent); font-weight: 600; }
.seg button:focus-visible { outline-offset: -3px; }
</style>
