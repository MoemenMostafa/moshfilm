<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { fmtElapsed, turnElapsedMs, workedSummary } from "../activity";
import type { ActivityTurn, PlanItem } from "../types";

const props = defineProps<{ turn: ActivityTurn | null; plan: PlanItem[] }>();

const open = ref(false);
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;
onMounted(() => { timer = setInterval(() => { now.value = Date.now(); }, 1000); });
onBeforeUnmount(() => { if (timer) clearInterval(timer); });

const working = computed(() => !!props.turn && !props.turn.ended);
const showSteps = computed(() => !!props.turn && (working.value || open.value));
const elapsed = computed(() => (props.turn ? fmtElapsed(turnElapsedMs(props.turn, now.value)) : ""));
const summary = computed(() => (props.turn ? workedSummary(props.turn) : ""));
const icon = (state: string): string => (state === "done" ? "✓" : state === "failed" ? "✗" : "");
</script>

<template>
  <div class="working" data-testid="working-card" :data-working="working">
    <ul v-if="plan.length" class="plan" data-testid="plan">
      <li v-for="(p, i) in plan" :key="i" data-testid="plan-item" :data-done="p.done" :class="{ done: p.done }">
        <span class="box">{{ p.done ? "☑" : "☐" }}</span> {{ p.text }}
      </li>
    </ul>
    <div v-if="turn && working" class="head">
      <span class="spinner" data-testid="spinner" aria-hidden="true"></span>
      <strong>Working</strong>
      <span class="elapsed" data-testid="elapsed">{{ elapsed }}</span>
    </div>
    <button v-else-if="turn" type="button" class="summary" data-testid="summary" :aria-expanded="open"
      @click="open = !open">
      <span class="chev">{{ open ? "▾" : "▸" }}</span> {{ summary }}
    </button>
    <ul v-if="showSteps && turn" class="steps" data-testid="steps">
      <li v-for="s in turn.steps" :key="s.id" data-testid="step" :data-state="s.state" :class="s.state">
        <span v-if="s.state === 'running'" class="spinner small" aria-hidden="true"></span>
        <span v-else class="mark">{{ icon(s.state) }}</span>
        {{ s.label }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.working { align-self: flex-start; box-sizing: border-box; max-width: 100%; padding: 6px var(--s3); background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--r-card); font-size: var(--fs-sec); color: var(--text); }
.head { display: flex; align-items: center; gap: 6px; }
.elapsed { color: var(--muted); margin-left: var(--s4); font-variant-numeric: tabular-nums; font-family: var(--font-mono); font-size: var(--fs-meta); }
.summary { display: inline-flex; align-items: center; gap: 4px; border: 0; background: none; padding: 0; font: inherit; color: var(--muted); cursor: pointer; text-align: left; border-radius: 4px; }
.summary:hover { color: var(--text); }
.steps, .plan { list-style: none; margin: var(--s1) 0 0; padding: 0; }
.plan { margin: 0 0 6px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.plan li.done { color: var(--muted); text-decoration: line-through; }
.steps li { display: flex; align-items: center; gap: 6px; padding: 1px 0; }
.mark { width: 12px; text-align: center; }
.done .mark { color: var(--ok); }
.failed .mark { color: var(--warn); }
.spinner { width: 12px; height: 12px; border: 2px solid var(--accent-soft); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; flex: none; }
.spinner.small { width: 9px; height: 9px; margin: 0 1.5px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 3s; } }
</style>
