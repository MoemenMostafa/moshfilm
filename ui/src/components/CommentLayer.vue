<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import * as api from "../api";
import { commentColor, toNormalizedPoint, visiblePins } from "../comments";
import { useAspectView } from "../composables/useAspectView";
import { useFilm } from "../composables/useFilm";
import { mainAspect } from "../runtime/aspect";
import { useSharedPlayhead } from "../composables/usePlayhead";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ (e: "done"): void }>();

const store = useFilm();
const head = useSharedPlayhead();
const shape = useAspectView();
const root = ref<HTMLElement | null>(null);
const box = ref<HTMLTextAreaElement | null>(null);
/** The spot being commented on: time and point are captured at click, so playback can't drift them. */
const draft = ref<{ time: number; x: number; y: number } | null>(null);
const text = ref("");
const failure = ref("");
const sending = ref(false);

// pins show only on the shape they were made on (an old comment counts as the main shape)
const pins = computed(() => visiblePins(store.queue.value.items, head.time.value, 0.5, {
  aspect: shape.aspect.value, main: store.film.value ? mainAspect(store.film.value) : "16:9" }));

function replyTo(id: string): string {
  return store.queue.value.messages.filter((m) => m.reply_to === id).map((m) => m.text).join("\n");
}
function tip(id: string, body: string): string {
  const reply = replyTo(id);
  return reply ? `${body}\n\nClaude: ${reply}` : body;
}

function reset(): void {
  draft.value = null;
  text.value = "";
  failure.value = "";
}

watch(() => props.active, (on) => { if (!on) reset(); });

async function place(e: MouseEvent): Promise<void> {
  if (!props.active || !root.value) return;
  const p = toNormalizedPoint(e.clientX, e.clientY, root.value.getBoundingClientRect());
  head.pause();
  draft.value = { time: head.time.value, ...p };
  text.value = "";
  failure.value = "";
  await nextTick();
  box.value?.focus();
}

function cancel(): void {
  reset();
  emit("done");
}

async function send(): Promise<void> {
  const d = draft.value;
  const body = text.value.trim();
  if (!d || !body || sending.value) return;
  sending.value = true;
  try {
    // the shape is sent only when the film has two; otherwise the server takes the main one
    await api.postComment(d.time, { x: d.x, y: d.y }, body, ...(shape.hasSecond.value ? [shape.aspect.value] as const : []));
    await store.refreshQueue();
    reset();
    emit("done");
  } catch (e) {
    failure.value = e instanceof Error ? e.message : String(e);
  } finally {
    sending.value = false;
  }
}

function onBoxKey(e: KeyboardEvent): void {
  if (e.key === "Escape") {
    e.preventDefault();
    cancel();
  } else if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    void send();
  }
}
</script>

<template>
  <div ref="root" class="layer" :class="{ active }" data-testid="comment-layer" @click.self="place">
    <span v-for="p in pins" :key="p.id" class="pin" :class="p.state" :data-pin="p.id"
      :title="tip(p.id, p.text)"
      :style="{ left: (p.point?.x ?? 0.5) * 100 + '%', top: (p.point?.y ?? 0.5) * 100 + '%', background: commentColor(p.state) }"
      @click.stop>
      <span class="tip">{{ tip(p.id, p.text) }}</span>
    </span>
    <form v-if="draft" class="pop" data-testid="popover" :style="{ left: draft.x * 100 + '%', top: draft.y * 100 + '%' }"
      :class="{ flip: draft.x > 0.6, up: draft.y > 0.6 }" @submit.prevent="send" @click.stop>
      <textarea ref="box" v-model="text" rows="3" placeholder="Comment on this moment…" aria-label="Comment"
        @keydown="onBoxKey"></textarea>
      <p v-if="failure" class="err" role="alert">{{ failure }}</p>
      <div class="row">
        <button type="button" class="btn sm ghost" data-testid="cancel" @click="cancel">Cancel</button>
        <button type="submit" class="btn sm primary" data-testid="send" :disabled="!text.trim() || sending">Send</button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.layer { position: absolute; inset: 0; pointer-events: none; }
.layer.active { pointer-events: auto; cursor: crosshair; }
.pin { position: absolute; width: 16px; height: 16px; margin: -8px 0 0 -8px; border-radius: 50%; border: 2px solid #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.4); pointer-events: auto; cursor: default; }
.pin .tip { display: none; position: absolute; left: 20px; top: -4px; width: max-content; max-width: 220px; white-space: pre-wrap;
  background: rgba(17, 17, 17, 0.8); color: #fff; padding: var(--s1) var(--s2); border-radius: 6px; font-size: var(--fs-sec); z-index: 5; }
.pin:hover .tip { display: block; }
.pop { position: absolute; z-index: 6; width: 220px; margin: var(--s3) 0 0 var(--s3); padding: var(--s2); background: var(--surface); color: var(--text);
  border: 1px solid var(--border); border-radius: var(--r-card); box-shadow: var(--shadow); font-size: var(--fs-body); cursor: default; pointer-events: auto; }
.pop.flip { margin-left: -232px; }
.pop.up { margin-top: -120px; }
.pop textarea { width: 100%; box-sizing: border-box; resize: none; padding: 6px var(--s2); border: 1px solid var(--border-strong); border-radius: 6px;
  background: var(--bg); color: var(--text); }
.pop .row { display: flex; justify-content: flex-end; gap: var(--s2); margin-top: var(--s2); }
.err { margin: var(--s1) 0 0; color: var(--warn); font-size: var(--fs-sec); }
</style>
