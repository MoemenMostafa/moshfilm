import type { Activity, Aspect, EditOp, ExportStatus, Film, FrameRef, HistoryInfo, Proposal, QueueItem, QueueSnapshot, SoundCatalog, SoundInfo, VoiceInfo } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body && typeof body.error === "string") message = body.error;
    } catch {
      /* not JSON: keep the status line */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

const post = <T>(url: string, body: unknown): Promise<T> =>
  call<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const upload = <T>(url: string, form: FormData): Promise<T> => call<T>(url, { method: "POST", body: form });

export const getFilm = (): Promise<{ film: Film; folder: string }> => call("/api/film");
export const edit = (ops: EditOp[]): Promise<{ film: Film }> => post("/api/film/edit", { ops });
export const getProposals = (): Promise<{ proposals: Proposal[] }> => call("/api/proposals");
export const approve = (id: string, includePinned = false): Promise<Proposal> =>
  post(`/api/proposals/${encodeURIComponent(id)}/approve`, { include_pinned: includePinned });
export const reject = (id: string): Promise<Proposal> =>
  post(`/api/proposals/${encodeURIComponent(id)}/reject`, {});
export const getQueue = (): Promise<QueueSnapshot> => call("/api/queue");
export const postComment = (time: number, point: { x: number; y: number } | null, text: string,
  aspect?: Aspect): Promise<QueueItem> =>
  post("/api/comments", aspect ? { time, point, text, aspect } : { time, point, text });
export const getActivity = (): Promise<Activity> => call("/api/activity");
export function postChat(text: string, file?: File, at?: FrameRef): Promise<QueueItem> {
  const form = new FormData();
  form.append("text", text);
  if (at) form.append("at", JSON.stringify(at));
  if (file) form.append("file", file);
  return upload("/api/chat", form);
}
export const getVoice = (): Promise<VoiceInfo> => call("/api/voice");
export const synthesizeVoice = (): Promise<{ started: boolean; running: boolean }> =>
  post("/api/voice/synthesize", {});
export const getSound = (): Promise<SoundInfo> => call("/api/sound");
export const getSoundCatalog = (): Promise<SoundCatalog> => call("/api/sound/presets");
export const presetUrl = (name: string): string => `/api/sound/preset/${encodeURIComponent(name)}.wav`;
export function uploadMusic(file: File): Promise<{ film: Film }> {
  const form = new FormData();
  form.append("file", file);
  return upload("/api/music", form);
}

export type HistoryReply = HistoryInfo & { film: Film; changed: boolean };
export const getHistory = (): Promise<HistoryInfo> => call("/api/history");
export const undo = (): Promise<HistoryReply> => post("/api/history/undo", {});
export const redo = (): Promise<HistoryReply> => post("/api/history/redo", {});
export const jumpHistory = (id: number): Promise<HistoryReply> => post("/api/history/jump", { id });
export const getExport = (): Promise<ExportStatus> => call("/api/export");
export const startExport = (format: "mp4" | "gif"): Promise<ExportStatus> => post("/api/export", { format });
export const revealExport = (name: string): Promise<{ ok: boolean }> => post("/api/export/reveal", { name });
export const exportFileUrl = (name: string): string => `/api/export/file/${encodeURIComponent(name)}`;
