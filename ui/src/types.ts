// TypeScript mirrors of the Python models (film.py, queue.py, proposals.py, edits.py).

export interface VoiceLine {
  text: string;
  offset: number;
  pinned: boolean;
  /** The person wrote or edited the words: proposals cannot overwrite them. */
  text_pinned?: boolean;
}

export interface Scene {
  id: string;
  title: string;
  file: string | null;
  length: number;
  pinned: boolean;
  status: "planned" | "building" | "ready";
  voice: VoiceLine;
}

export interface TextClip {
  id: string;
  scene: string;
  text: string;
  start: number;
  end: number | null;
  pinned: boolean;
  text_pinned?: boolean;
  style: "caption" | "title";
  x: number | null;
  y: number | null;
}

/** Something the person removed; proposals must not bring it back unasked. */
export interface Tombstone {
  kind: "scene" | "text" | "voice" | "sfx" | "music";
  id: string;
  scene: string | null;
  text: string;
  at: string;
}

export type Mood = "calm" | "bright" | "playful" | "tense" | "inspiring";
export type Palette = "keys" | "pluck" | "pad" | "chip";
export type SfxPreset = "whoosh" | "swoosh-up" | "door" | "ding" | "pop" | "tick" | "click" | "success"
  | "error" | "typewriter" | "riser" | "thud";

/** Parameters of a generated music bed; the audio is derived from them on the server. */
export interface MusicBed {
  mood: Mood;
  tempo: number;
  key: string;
  scale: "major" | "minor";
  palette: Palette;
  seed: number;
}

export interface Music {
  file: string | null;
  bed?: MusicBed | null;
  volume: number;
  /** The person picked or supplied it: proposals cannot replace it. */
  pinned?: boolean;
}

/** A generated sound effect pinned to a moment of a scene (`at` seconds after the scene starts). */
export interface SfxClip {
  id: string;
  scene: string;
  preset: SfxPreset;
  at: number;
  volume: number;
  pitch: number;
  stretch: number;
  seed: number;
  pinned: boolean;
}

/** Rendered sound the server holds for this film (`GET /api/sound`). */
export interface SoundInfo {
  music: { url: string; duration: number } | null;
  sfx: Record<string, { url: string; duration: number }>;
}

/** What the pickers offer (`GET /api/sound/presets`). */
export interface SoundCatalog {
  sfx: { name: SfxPreset; label: string; description: string; duration: number }[];
  moods: { name: Mood; label: string; tempo: number; scale: "major" | "minor"; palette: Palette }[];
  palettes: Palette[];
  keys: string[];
  scales: ("major" | "minor")[];
  tempo: [number, number];
}

/** The four film shapes (aspect ratios); mirrors aspects.py. */
export type Aspect = "16:9" | "9:16" | "1:1" | "4:5";

export interface Film {
  version: number;
  title: string;
  width: number;
  height: number;
  /** Missing means "16:9" (older files and test fixtures). */
  aspect?: Aspect;
  /** A second shape sharing the one timeline; missing or null means none. */
  second_aspect?: Aspect | null;
  fps: number;
  pace: number;
  order_pinned: boolean;
  voice: { name: string; rate: string };
  music: Music | null;
  scenes: Scene[];
  texts: TextClip[];
  /** Missing means none (older files and test fixtures). */
  sfx?: SfxClip[];
  removed_by_person?: Tombstone[];
}

export type Change = Record<string, unknown> & { op: string };

export interface Proposal {
  id: string;
  created: string;
  summary: string;
  needs_approval: boolean;
  status: "pending" | "applied" | "partial" | "awaiting_approval" | "rejected" | "invalid";
  changes: Change[];
  held: number[];
  /** Why a change was held when it is not just a pinned value (index as a string -> sentence). */
  held_reasons?: Record<string, string>;
  error: string | null;
}

export interface QueueItem {
  id: string;
  kind: "comment" | "chat" | "event";
  text: string;
  created: string;
  state: "queued" | "delivered" | "resolved";
  time: number | null;
  scene: string | null;
  scene_time: number | null;
  point: { x: number; y: number } | null;
  /** The shape a comment was made on (missing: the main shape); `point` is measured on that frame. */
  aspect?: Aspect | null;
  attachment: string | null;
  at?: FrameRef | null;
  delivered_at: string | null;
  resolved_at: string | null;
}

/** The frame a chat message points at (seconds in the whole film, and the scene there). */
export interface FrameRef {
  time: number;
  scene: string | null;
  sceneTitle: string | null;
  /** Only sent when the film has two shapes (missing: the main shape). */
  aspect?: Aspect | null;
}

export interface ActivityStep {
  id: number;
  label: string;
  state: "running" | "done" | "failed";
  started: string;
  ended: string | null;
  /** Scene id a Read/Edit/Write step targets. */
  scene?: string;
  action?: "read" | "edit";
}

export interface ActivityTurn {
  id: string;
  started: string;
  updated: string;
  ended: string | null;
  /** Chat or comment the card sits under (the latest delivered one when the turn began). */
  item: string | null;
  steps: ActivityStep[];
}

export interface PlanItem {
  text: string;
  done: boolean;
}

export interface Activity {
  turn: ActivityTurn | null;
  plan: PlanItem[];
}

export interface Message {
  id: string;
  role: "claude";
  text: string;
  reply_to: string | null;
  created: string;
}

export interface QueueSnapshot {
  items: QueueItem[];
  messages: Message[];
  status: string | null;
  connected: boolean;
}

export type EditOp = Record<string, unknown> & { op: string };

export type VoiceInfo = Record<string, { url: string; duration: number }>;

export interface HistoryStep {
  id: number;
  label: string;
  kind: "base" | "person" | "claude";
  time: string;
  /** The state the film is in now. */
  current: boolean;
  /** Undone steps that redo can bring back. */
  future: boolean;
}

export interface HistoryInfo {
  steps: HistoryStep[];
  cursor: number;
  can_undo: boolean;
  can_redo: boolean;
}

/** What the timeline has selected: a scene, text clip, voice line (by scene id) a sound clip or the music bed. */
export interface Selection {
  kind: "scene" | "text" | "voice" | "music" | "sfx";
  id: string;
}

/** Where a running export is (server `progress` in `GET /api/export`); null until the first report. */
export interface ExportProgress {
  stage: "audio" | "frames" | "encode";
  aspect: Aspect | null;
  aspect_index: number;
  aspect_count: number;
  /** Frames for "frames", seconds of film for "encode". */
  done: number;
  total: number;
  /** Overall, across every shape, 0 to 100. */
  percent: number;
  eta_seconds: number | null;
}

/** Progress of the editor's "Export movie" (server `GET /api/export`). */
export interface ExportStatus {
  state: "idle" | "running" | "done" | "error";
  format: "mp4" | "gif" | null;
  files: { name: string; aspect: Aspect; bytes: number }[];
  /** Layout-check warnings printed before the export, as text. */
  warnings: string[];
  /** The shape being rendered while running. */
  current: Aspect | null;
  /** Older servers leave this out. */
  progress?: ExportProgress | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}
