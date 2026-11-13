<script setup lang="ts">
import { computed, ref } from "vue";
import * as api from "../api";
import type { Change, Film, Proposal } from "../types";

const props = defineProps<{ proposal: Proposal; film: Film | null }>();
const emit = defineEmits<{ change: [] }>();

const busy = ref(false);
const problem = ref<string | null>(null);

const title = (id: unknown): string => {
  const s = props.film?.scenes.find((x) => x.id === id);
  return s ? s.title : String(id);
};
const sceneNumber = (id: unknown): string => {
  const i = props.film?.scenes.findIndex((x) => x.id === id) ?? -1;
  return i >= 0 ? String(i + 1).padStart(2, "0") : String(id);
};
const secs = (n: unknown): string => `${Number(n).toFixed(1)}s`;

/** The scenes a scene-list proposal would add (title, voice line, length). */
const scenes = computed(() =>
  props.proposal.changes.flatMap((c) =>
    c.op === "add_scene"
      ? [c.scene as { id: string; title: string; length: number; voice?: { text?: string } }]
      : []));

function describe(c: Change): string {
  const film = props.film;
  switch (c.op) {
    case "set_scene": {
      const cur = film?.scenes.find((s) => s.id === c.id);
      const parts: string[] = [];
      if (c.title != null) parts.push(`title "${String(c.title)}"`);
      if (c.length != null) parts.push(`length ${cur ? secs(cur.length) : "?"} → ${secs(c.length)}`);
      if (c.status != null) parts.push(`status ${String(c.status)}`);
      return `scene "${title(c.id)}" ${parts.join(", ") || "changes"}`;
    }
    case "set_voice": {
      const cur = film?.scenes.find((s) => s.id === c.id);
      const parts: string[] = [];
      if (c.text != null) parts.push(`line "${String(c.text)}"`);
      if (c.offset != null) parts.push(`voice start ${cur ? secs(cur.voice.offset) : "?"} → ${secs(c.offset)}`);
      return `scene "${title(c.id)}" ${parts.join(", ") || "voice changes"}`;
    }
    case "add_text": {
      const t = c.text as { text?: string; scene?: string; start?: number; end?: number | null };
      const when = t.end != null ? `${secs(t.start ?? 0)} to ${secs(t.end)}` : `from ${secs(t.start ?? 0)}`;
      return `text "${t.text ?? ""}" is added to scene "${title(t.scene)}", ${when}`;
    }
    case "set_text": {
      const cur = film?.texts.find((t) => t.id === c.id);
      const label = cur ? `text "${cur.text}"` : `text ${String(c.id)}`;
      const parts: string[] = [];
      if (c.start != null) parts.push(`start ${cur ? secs(cur.start) : "?"} → ${secs(c.start)}`);
      if (c.end != null) parts.push(`end ${cur?.end != null ? secs(cur.end) : "scene end"} → ${secs(c.end)}`);
      return `${label} ${parts.join(", ")}`;
    }
    case "move_scene":
      return `scene "${title(c.id)}" moves to position ${Number(c.index) + 1}`;
    case "remove_scene":
      return `scene "${title(c.id)}" is removed`;
    case "remove_text": {
      const cur = film?.texts.find((t) => t.id === c.id);
      return `text "${cur ? cur.text : String(c.id)}" is removed`;
    }
    case "add_sfx": {
      const clip = c.sfx as { preset?: string; scene?: string; at?: number };
      const at = Number(Number(clip.at ?? 0).toFixed(2));
      return `Add sound "${clip.preset ?? ""}" to scene ${sceneNumber(clip.scene)} at ${at} s`;
    }
    case "set_sfx":
      return `Change sound ${String(c.id)}`;
    case "remove_sfx":
      return `Remove sound ${String(c.id)}`;
    case "set_music": {
      const bed = c.bed as { mood?: string; tempo?: number; key?: string; scale?: string } | null | undefined;
      return bed ? `Music: ${bed.mood}, ${bed.tempo} bpm, ${bed.key ?? "C"} ${bed.scale ?? "major"}` : "Remove music";
    }
    default:
      return c.op;
  }
}

/** What an approval-gated proposal does besides adding scenes (those show in the table). */
const otherChanges = computed(() =>
  props.proposal.changes.filter((c) => c.op !== "add_scene").map(describe));

const heldChanges = computed(() =>
  props.proposal.held.filter((i) => props.proposal.changes[i]).map((i) => {
    const why = props.proposal.held_reasons?.[String(i)];
    return why ? `${describe(props.proposal.changes[i])} (held: ${why})` : describe(props.proposal.changes[i]);
  }));

async function run(fn: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  problem.value = null;
  try {
    await fn();
  } catch (e) {
    problem.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
const approve = (includePinned: boolean) => run(() => api.approve(props.proposal.id, includePinned));
const reject = () => run(() => api.reject(props.proposal.id));
</script>

<template>
  <div class="card" :data-proposal="proposal.id" :data-status="proposal.status">
    <template v-if="proposal.status === 'awaiting_approval'">
      <p class="lead">{{ proposal.summary || "Claude proposes this scene list:" }}</p>
      <table v-if="scenes.length" class="scenes">
        <thead><tr><th>Scene</th><th>Voice line</th><th>Length</th></tr></thead>
        <tbody>
          <tr v-for="s in scenes" :key="s.id">
            <td>{{ s.title }}</td><td>{{ s.voice?.text ?? "" }}</td><td class="num">{{ secs(s.length) }}</td>
          </tr>
        </tbody>
      </table>
      <ul v-if="otherChanges.length" class="held" data-testid="other-changes">
        <li v-for="(o, i) in otherChanges" :key="i">{{ o }}</li>
      </ul>
      <div class="buttons">
        <button type="button" class="btn primary" data-action="approve" :disabled="busy" @click="approve(false)">Build it</button>
        <button type="button" class="btn" data-action="change" :disabled="busy" @click="emit('change')">Change…</button>
        <button type="button" class="btn ghost" data-action="reject" :disabled="busy" @click="reject()">Reject</button>
      </div>
    </template>
    <template v-else-if="proposal.status === 'partial'">
      <p class="lead">Claude wants to change things you set:</p>
      <ul class="held">
        <li v-for="(h, i) in heldChanges" :key="i">{{ h }}</li>
      </ul>
      <div class="buttons">
        <button type="button" class="btn primary" data-action="apply" :disabled="busy" @click="approve(true)">Apply Claude's version</button>
        <button type="button" class="btn" data-action="keep" :disabled="busy" @click="reject()">Keep mine</button>
      </div>
    </template>
    <template v-else-if="proposal.status === 'invalid'">
      <p class="lead">{{ proposal.summary || "A proposal from Claude could not be used." }}</p>
      <small class="error" data-testid="proposal-error">{{ proposal.error }}</small>
    </template>
    <small v-if="problem" class="error" role="alert">{{ problem }}</small>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; gap: var(--s2); margin: var(--s2) 0; padding: var(--s3); border: 1px solid var(--accent); background: var(--accent-soft);
  border-radius: var(--r-card); font-size: var(--fs-body); color: var(--text); }
.card[data-status="partial"] { border-color: var(--warn-edge); background: var(--warn-bg); }
.card[data-status="invalid"] { border-color: var(--border-strong); background: var(--surface-2); }
.lead { margin: 0; font-weight: 600; }
.scenes { width: 100%; border-collapse: collapse; font-size: var(--fs-sec); }
.scenes th { text-align: left; color: var(--muted); font-weight: 600; font-size: var(--fs-meta); }
.scenes th, .scenes td { padding: 3px var(--s1); border-bottom: 1px solid var(--border); vertical-align: top; }
.scenes .num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
.held { margin: 0; padding-left: var(--s4); font-size: var(--fs-sec); }
.buttons { display: flex; gap: var(--s2); flex-wrap: wrap; }
.error { display: block; color: var(--warn); font-size: var(--fs-meta); }
</style>
