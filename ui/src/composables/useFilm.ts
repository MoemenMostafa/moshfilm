import { computed, inject, provide, ref, type InjectionKey } from "vue";
import * as api from "../api";
import { subscribe } from "../events";
import { layout, OVERFLOW_COPY } from "../runtime/timing";
import type { Activity, EditOp, Film, HistoryInfo, Proposal, QueueSnapshot, SoundCatalog, SoundInfo, VoiceInfo } from "../types";
import { createSelection } from "./useSelection";

const emptyHistory = (): HistoryInfo => ({ steps: [], cursor: -1, can_undo: false, can_redo: false });
const emptyQueue = (): QueueSnapshot => ({ items: [], messages: [], status: null, connected: false });

export function createFilmStore() {
  const film = ref<Film | null>(null);
  const folder = ref("");
  const voice = ref<VoiceInfo>({});
  /** Rendered bed and sound effects (URLs follow the film length and every sound's settings). */
  const sound = ref<SoundInfo>({ music: null, sfx: {} });
  /** The preset lists for the pickers; loaded once. */
  const catalog = ref<SoundCatalog | null>(null);
  const proposals = ref<Proposal[]>([]);
  const queue = ref<QueueSnapshot>(emptyQueue());
  /** Banner text while film.json cannot be read (server answers 409); null when fine. */
  const error = ref<string | null>(null);
  const activity = ref<Activity>({ turn: null, plan: [] });
  const history = ref<HistoryInfo>(emptyHistory());
  /** scene file -> version (its mtime), kept even before film.json names the file, so a late film update still reloads it. */
  const fileVersions = ref<Record<string, number>>({});
  /** scene id -> version, so the preview re-imports a changed scene file instead of reusing the old module. */
  const sceneVersions = computed<Record<string, number>>(() => {
    const out: Record<string, number> = {};
    for (const s of film.value?.scenes ?? []) {
      const v = s.file ? fileVersions.value[s.file] : undefined;
      if (v !== undefined) out[s.id] = v;
    }
    return out;
  });
  /** Thread item the timeline asked the panel to scroll to (comment marker -> panel thread). */
  const focusItem = ref<string | null>(null);
  /** Latest "Make voice" progress from the server's voice events (text shown verbatim); null before any. */
  const voiceStatus = ref<{ text: string; error: boolean; busy: boolean } | null>(null);

  const voiceDurations = computed(() =>
    Object.fromEntries(Object.entries(voice.value).map(([id, v]) => [id, v.duration])));
  const slots = computed(() => (film.value ? layout(film.value, voiceDurations.value) : []));

  function fail(e: unknown): void {
    if (e instanceof api.ApiError && e.status === 409) error.value = e.message;
    else console.error(e);
  }

  // Answers can arrive out of order (a slow bed render for an older length, a fast newer one): only the
  // latest request may write its result.
  let voiceRequest = 0;
  let soundRequest = 0;
  /** True while a sound refresh is in flight (the music bed may be rendering): Regenerate waits. */
  const soundBusy = ref(false);
  let soundPending = 0;

  async function refreshVoice(): Promise<void> {
    const id = ++voiceRequest;
    try {
      const v = await api.getVoice();
      if (id === voiceRequest) voice.value = v;
    } catch (e) {
      fail(e);
    }
  }

  async function refreshSound(): Promise<void> {
    const id = ++soundRequest;
    soundPending += 1;
    soundBusy.value = true;
    try {
      const info = await api.getSound();
      if (info && id === soundRequest) sound.value = info;
    } catch (e) {
      // 409 here means "the film changed while this bed was made": a newer refresh is on its way, not an error
      if (!(e instanceof api.ApiError && e.status === 409)) fail(e);
    } finally {
      soundPending -= 1;
      soundBusy.value = soundPending > 0;
    }
  }

  async function loadCatalog(): Promise<void> {
    try {
      catalog.value = (await api.getSoundCatalog()) ?? null;
    } catch (e) {
      fail(e);
    }
  }

  /** The voice lengths decide the film length, and the bed is as long as the film: they refresh together. */
  async function refreshVoiceAndSound(): Promise<void> {
    await refreshVoice();
    await refreshSound();
  }

  async function refreshFilm(): Promise<void> {
    try {
      const r = await api.getFilm();
      film.value = r.film;
      folder.value = r.folder;
      error.value = null;
    } catch (e) {
      fail(e);
      return;
    }
    await refreshVoiceAndSound(); // line lengths follow the film's text
  }

  async function refreshProposals(): Promise<void> {
    try {
      proposals.value = (await api.getProposals()).proposals;
    } catch (e) {
      fail(e);
    }
  }

  async function refreshQueue(): Promise<void> {
    try {
      queue.value = await api.getQueue();
    } catch (e) {
      fail(e);
    }
  }

  async function refreshActivity(): Promise<void> {
    try {
      activity.value = await api.getActivity();
    } catch (e) {
      fail(e);
    }
  }

  async function refreshHistory(): Promise<void> {
    try {
      const h = await api.getHistory();
      if (h) history.value = { steps: h.steps, cursor: h.cursor, can_undo: h.can_undo, can_redo: h.can_redo };
    } catch (e) {
      fail(e);
    }
  }

  async function edit(ops: EditOp[]): Promise<void> {
    try {
      film.value = (await api.edit(ops)).film;
      error.value = null;
    } catch (e) {
      fail(e);
      throw e;
    }
    await refreshVoiceAndSound();
    void refreshHistory();
  }

  /** Undo, redo or jump: the server answers with the film as it is now, so the view follows at once. */
  async function travel(call: () => Promise<api.HistoryReply>): Promise<void> {
    try {
      const r = await call();
      if (!r) return;
      film.value = r.film;
      history.value = { steps: r.steps, cursor: r.cursor, can_undo: r.can_undo, can_redo: r.can_redo };
      error.value = null;
    } catch (e) {
      fail(e);
      return;
    }
    await refreshVoiceAndSound();
  }
  const undo = (): Promise<void> => travel(api.undo);
  const redo = (): Promise<void> => travel(api.redo);
  const jumpHistory = (id: number): Promise<void> => travel(() => api.jumpHistory(id));

  const sel = createSelection(film, edit);

  void Promise.all([refreshFilm(), refreshProposals(), refreshQueue(), refreshActivity(), refreshHistory(), loadCatalog()]);

  const unsubscribe = subscribe({
    film: () => void refreshFilm(),
    proposals: () => void refreshProposals(),
    queue: () => {
      void refreshQueue();
      // the server ticks `queue` every few seconds: a turn that went quiet is reported as ended on the next read
      if (activity.value.turn && !activity.value.turn.ended) void refreshActivity();
    },
    activity: () => void refreshActivity(),
    history: () => void refreshHistory(),
    voice: (d: { state?: string; message?: string; overflow?: string[] }) => {
      if (d?.state === "progress") voiceStatus.value = { text: d.message ?? "Making voice…", error: false, busy: true };
      else if (d?.state === "error") voiceStatus.value = { text: d.message ?? "Voice failed", error: true, busy: false };
      else if (d?.state === "done") {
        const late: string[] = Array.isArray(d.overflow) ? d.overflow : [];
        voiceStatus.value = { text: late.length ? `${OVERFLOW_COPY} (${late.join(", ")})` : "Voice ready",
          error: late.length > 0, busy: false };
      }
      void refreshVoiceAndSound();
    },
    scene: (data: { file?: string; version?: number }) => {
      if (typeof data?.file === "string" && typeof data.version === "number") {
        fileVersions.value = { ...fileVersions.value, [data.file]: data.version };
      }
    },
  });

  return { film, folder, slots, voice, sound, soundBusy, catalog, refreshSound, voiceDurations, proposals, queue, error, sceneVersions, focusItem, voiceStatus,
    activity, history, edit, undo, redo, jumpHistory, refreshQueue, refreshActivity, unsubscribe,
    selection: sel.selection, pendingRemove: sel.pending, selectItem: sel.select, clearSelection: sel.clear,
    requestRemove: sel.requestRemove, confirmRemove: sel.confirm, cancelRemove: sel.cancel };
}

export type FilmStore = ReturnType<typeof createFilmStore>;
export const FilmKey: InjectionKey<FilmStore> = Symbol("film");

export const provideFilm = (store: FilmStore): void => provide(FilmKey, store);

export function useFilm(): FilmStore {
  const s = inject(FilmKey);
  if (!s) throw new Error("no film store provided: call provideFilm in App");
  return s;
}
