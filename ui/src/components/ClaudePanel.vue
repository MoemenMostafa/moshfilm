<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { atChip, attachFrameKey, fmtTime, loadFlag, saveFlag } from "../activity";
import { locate } from "../runtime/timing";
import * as api from "../api";
import { useAspectView } from "../composables/useAspectView";
import { useFilm } from "../composables/useFilm";
import { useSharedPlayhead } from "../composables/usePlayhead";
import type { FrameRef, Message, QueueItem } from "../types";
import Icon from "./Icon.vue";
import ProposalCard from "./ProposalCard.vue";
import WorkingCard from "./WorkingCard.vue";

const store = useFilm();
const head = useSharedPlayhead();
const shape = useAspectView();

const connected = computed(() => store.queue.value.connected);
const status = computed(() => store.queue.value.status);
const command = computed(() =>
  `cd "${store.folder.value}" && claude "Use the moshfilm skill to work on this film"`);
const copied = ref(false);

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(command.value);
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 1500);
  } catch {
    /* clipboard blocked: the command is selectable text */
  }
}

interface Entry { key: string; created: string; item?: QueueItem; message?: Message; replies: Message[] }

const entries = computed<Entry[]>(() => {
  const { items, messages } = store.queue.value;
  const byItem = new Map<string, Message[]>();
  const loose: Message[] = [];
  const ids = new Set(items.map((i) => i.id));
  for (const m of messages) {
    if (m.reply_to && ids.has(m.reply_to)) byItem.set(m.reply_to, [...(byItem.get(m.reply_to) ?? []), m]);
    else loose.push(m);
  }
  const byTime = (a: { created: string }, b: { created: string }) => a.created.localeCompare(b.created);
  const out: Entry[] = [
    ...items.map((item) => ({ key: item.id, created: item.created, item,
      replies: (byItem.get(item.id) ?? []).sort(byTime) })),
    ...loose.map((message) => ({ key: message.id, created: message.created, message, replies: [] })),
  ];
  return out.sort(byTime);
});

const cards = computed(() => store.proposals.value.filter(
  (p) => p.status === "awaiting_approval" || p.status === "partial" || p.status === "invalid"));

const hasQueued = computed(() => store.queue.value.items.some((i) => i.state === "queued"));
const empty = computed(() =>
  (store.film.value?.scenes.length ?? 0) === 0 && entries.value.length === 0 && cards.value.length === 0);

const fmt = fmtTime;

// working card: under the chat item Claude is working on, else a standalone card at the end of the thread
const activity = computed(() => store.activity.value);
const showCard = computed(() => !!activity.value.turn || activity.value.plan.length > 0);
const cardAnchor = computed<string | null>(() => {
  const turn = activity.value.turn;
  const ids = new Set(store.queue.value.items.map((i) => i.id));
  if (turn?.item && ids.has(turn.item)) return turn.item;
  if (turn && !turn.ended) {
    const delivered = store.queue.value.items.filter((i) => i.state === "delivered" && i.kind !== "event");
    return delivered.length ? delivered[delivered.length - 1].id : null;
  }
  return null;
});

function chip(item: QueueItem): string {
  return item.at ? atChip(item.at, store.film.value?.scenes ?? []) : "";
}

function commentLabel(item: QueueItem): string {
  const scene = store.film.value?.scenes.find((s) => s.id === item.scene);
  const at = item.time != null ? `at ${fmt(item.time)}` : "";
  return `💬 ${at}${scene ? ` · scene "${scene.title}"` : ""}`.replace("💬 ", "💬 ").trim();
}

function seekTo(item: QueueItem): void {
  if (item.kind === "comment" && item.time != null) head.seek(item.time);
}

// composer
const draft = ref("");
const file = ref<File | null>(null);
const sending = ref(false);
const sendError = ref<string | null>(null);
const composer = ref<HTMLTextAreaElement | null>(null);
const picker = ref<HTMLInputElement | null>(null);
const thread = ref<HTMLElement | null>(null);
// "Attach frame": off by default, remembered per film
const attachFrame = ref(false);
watch(store.folder, (folder) => { attachFrame.value = loadFlag(attachFrameKey(folder), false); }, { immediate: true });
function toggleAttachFrame(): void {
  attachFrame.value = !attachFrame.value;
  saveFlag(attachFrameKey(store.folder.value), attachFrame.value);
}
function currentFrame(): FrameRef {
  const t = head.time.value;
  const found = locate(store.slots.value, t);
  const scene = store.film.value?.scenes.find((s) => s.id === found?.sceneId);
  const frame: FrameRef = { time: t, scene: scene?.id ?? null, sceneTitle: scene?.title ?? null };
  if (shape.hasSecond.value) frame.aspect = shape.aspect.value; // the shape the preview shows
  return frame;
}

function onPick(e: Event): void {
  const input = e.target as HTMLInputElement;
  file.value = input.files?.[0] ?? null;
  input.value = "";
}

async function send(): Promise<void> {
  const text = draft.value.trim();
  if (sending.value || (!text && !file.value)) return;
  sending.value = true;
  sendError.value = null;
  try {
    await api.postChat(text, file.value ?? undefined, attachFrame.value ? currentFrame() : undefined);
    draft.value = "";
    file.value = null;
    await store.refreshQueue();
  } catch (e) {
    sendError.value = e instanceof Error ? e.message : String(e);
  } finally {
    sending.value = false;
  }
}

function onEnter(e: KeyboardEvent): void {
  if (e.shiftKey || e.isComposing) return;
  e.preventDefault();
  void send();
}

async function changeSceneList(): Promise<void> {
  draft.value = "About the scene list: ";
  await nextTick();
  const el = composer.value;
  if (el) {
    el.focus();
    el.setSelectionRange(draft.value.length, draft.value.length);
  }
}

watch(() => entries.value.length + cards.value.length + (activity.value.turn?.steps.length ?? 0), async () => {
  await nextTick();
  if (thread.value) thread.value.scrollTop = thread.value.scrollHeight;
});

const highlighted = ref<string | null>(null);
watch(store.focusItem, async (id) => {
  if (!id) return;
  highlighted.value = id;
  await nextTick();
  thread.value?.querySelector(`[data-item="${CSS.escape(id)}"]`)?.scrollIntoView?.({ block: "nearest" });
  setTimeout(() => { if (highlighted.value === id) highlighted.value = null; }, 2000);
  store.focusItem.value = null;
});
</script>

<template>
  <div class="claude">
    <header class="head">
      <strong>Claude</strong> <span class="pill" :class="{ ok: connected }" data-testid="status-pill"><i class="dot" :class="connected ? 'on' : 'off'" data-testid="dot"></i><span class="ptext">{{ connected ? "connected" : "not connected" }}</span></span>
    </header>
    <div v-if="!connected" class="start" data-testid="start-box">
      <p>Start Claude Code for this film:</p>
      <code>{{ command }}</code>
      <button type="button" class="btn sm" data-action="copy" @click="copy">{{ copied ? "Copied" : "Copy" }}</button>
      <p v-if="hasQueued" class="note">Your queued messages will be delivered when Claude connects.</p>
    </div>
    <p v-if="status" class="status" data-testid="status">Claude: {{ status }}</p>

    <div ref="thread" class="thread" data-testid="thread">
      <p v-if="empty" class="prompt">What should the film be about? Give a topic, paste a script, or attach a document.</p>
      <div v-for="e in entries" :key="e.key" class="entry">
        <div v-if="e.item" class="item" :class="[e.item.kind, { hot: highlighted === e.item.id }]"
          :data-item="e.item.id" @click="seekTo(e.item)">
          <div v-if="e.item.kind === 'comment'" class="meta">{{ commentLabel(e.item) }}</div>
          <div class="text">{{ e.item.text }}</div>
          <div v-if="e.item.attachment" class="meta attachment"><Icon name="attach" /> {{ e.item.attachment }}</div>
          <button v-if="e.item.at" type="button" class="chip" data-testid="at-chip" title="Jump to this moment"
            @click.stop="head.seek(e.item.at.time)">{{ chip(e.item) }}</button>
          <div class="state" :data-state="e.item.state">{{ e.item.state }}</div>
        </div>
        <div v-else-if="e.message" class="claude-msg" :data-message="e.message.id">{{ e.message.text }}</div>
        <div v-for="r in e.replies" :key="r.id" class="claude-msg reply" :data-message="r.id">{{ r.text }}</div>
        <WorkingCard v-if="showCard && cardAnchor === e.key" :turn="activity.turn" :plan="activity.plan" />
      </div>
      <WorkingCard v-if="showCard && !entries.some((e) => e.key === cardAnchor)" :turn="activity.turn"
        :plan="activity.plan" />
      <ProposalCard v-for="p in cards" :key="p.id" :proposal="p" :film="store.film.value" @change="changeSceneList" />
    </div>

    <form class="composer" @submit.prevent="send">
      <small v-if="sendError" class="error" role="alert">{{ sendError }}</small>
      <small v-if="file" class="attached"><Icon name="attach" /> {{ file.name }}
        <button type="button" class="btn link" data-action="detach" @click="file = null">remove</button></small>
      <textarea ref="composer" v-model="draft" rows="3" placeholder="Message Claude"
        aria-label="Message Claude" @keydown.enter="onEnter"></textarea>
      <div class="row">
        <input ref="picker" type="file" accept=".txt,.md,.pdf,.docx" hidden data-testid="picker" @change="onPick" />
        <button type="button" class="btn icon ghost" data-action="attach" aria-label="Attach file" title="Attach a file (.txt, .md, .pdf, .docx)"
          @click="picker?.click()"><Icon name="attach" /></button>
        <button type="button" class="btn toggle" :class="{ on: attachFrame }" data-action="attach-frame"
          :aria-pressed="attachFrame" title="Send the current playhead position with the message"
          @click="toggleAttachFrame"><Icon name="star" /> Attach frame</button>
        <button type="submit" class="btn primary" data-action="send" :disabled="sending"><Icon name="send" /> Send</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.claude { display: flex; flex-direction: column; gap: var(--s2); height: 100%; min-height: 0; font-size: var(--fs-body); color: var(--text); }
.head { display: flex; align-items: center; gap: var(--s2); font-weight: 600; }
.ptext { display: inline-block; }
.ptext::first-letter { text-transform: uppercase; }
.dot.on { background: var(--ok); }
.dot.off { background: var(--border-strong); }
.start { padding: var(--s2) var(--s3); background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-card); }
.start p { margin: 0 0 var(--s1); }
.start code { display: block; padding: 6px var(--s2); background: var(--bg); border: 1px solid var(--border); border-radius: 6px; font-family: var(--font-mono);
  font-size: var(--fs-meta); word-break: break-all; margin-bottom: var(--s2); user-select: all; }
.note { color: var(--muted); font-size: var(--fs-sec); margin-top: var(--s2) !important; }
.status { margin: 0; padding: var(--s1) var(--s2); background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); border-radius: var(--r-ctl); font-size: var(--fs-sec); }
.thread { flex: 1; min-height: 0; overflow: auto; display: flex; flex-direction: column; gap: var(--s2); padding: var(--s1) 0; }
.prompt { color: var(--muted); margin: 0; }
.entry { display: flex; flex-direction: column; gap: var(--s1); }

/* your messages: accent bubbles on the right with their delivery state; Claude: neutral bubbles on the left */
.item { align-self: flex-end; max-width: 88%; padding: 6px var(--s3); border-radius: var(--r-card); border-bottom-right-radius: var(--s1);
  background: var(--accent); color: var(--on-accent); }
.item.comment { cursor: pointer; }
.item.event { align-self: center; background: var(--surface-2); color: var(--muted); font-style: italic; border-radius: var(--r-ctl); }
.item.hot { outline: 2px solid var(--focus); outline-offset: 2px; }
.meta { font-size: var(--fs-meta); opacity: 0.85; }
.attachment { display: flex; align-items: center; gap: 4px; }
.text { white-space: pre-wrap; overflow-wrap: anywhere; }
.state { text-align: right; font-size: var(--fs-meta); opacity: 0.85; margin-top: 2px; letter-spacing: 0.04em; text-transform: uppercase; }
.item.event .state { display: none; }
.state[data-state="resolved"]::before { content: "✓ "; }
.claude-msg { align-self: flex-start; max-width: 88%; padding: 6px var(--s3); background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--r-card); border-bottom-left-radius: var(--s1); white-space: pre-wrap; overflow-wrap: anywhere; }
.chip { display: inline-flex; margin-top: var(--s1); padding: 1px var(--s2); font-size: var(--fs-meta); border-radius: var(--r-pill);
  border: 1px solid var(--accent); background: var(--accent-soft); color: var(--text); cursor: pointer; }
.chip:hover { background: var(--surface-2); }
.chip:focus-visible { outline-offset: 1px; }

/* composer: one rounded box that shows the focus ring as a whole */
.composer { display: flex; flex-direction: column; gap: var(--s1); border: 1px solid var(--border-strong); border-radius: var(--r-card); background: var(--bg); padding: 6px; }
.composer:focus-within { outline: 2px solid var(--focus); outline-offset: 1px; }
textarea { resize: none; border: 0; background: transparent; padding: 2px var(--s1) var(--s2); font: inherit; color: var(--text); }
textarea:focus-visible { outline: none; }
textarea::placeholder { color: var(--muted); }
.row { display: flex; align-items: center; gap: var(--s1); }
.row .primary { margin-left: auto; }
.error { color: var(--warn); padding: 0 var(--s1); }
.attached { display: flex; align-items: center; gap: 4px; color: var(--muted); padding: 0 var(--s1); }
</style>
