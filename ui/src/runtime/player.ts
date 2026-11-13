// The scene player shared by the editor preview and the export render page.
import type { Aspect, Film, Scene } from "../types";
import { canvasSize, chosenAspects, mainAspect } from "./aspect";
import { mulberry32, seedFor, type SceneContext, type SceneModule } from "./scene-api";
import { layout, locate, textWindow, totalLength, type SceneSlot } from "./timing";

export interface PlayerOptions {
  film: Film;
  voice: Record<string, number>;
  sceneUrl: (s: Scene) => string;
  importScene?: (url: string) => Promise<SceneModule>;
  /** Latest known version of a scene's file; appended to its URL so a changed file is never served from the module cache. */
  versionOf?: (s: Scene) => number | undefined;
  /** "fit" scales the stage to its container (default); 1 keeps it at 1:1 for export. */
  scale?: "fit" | 1;
  /** The shape to draw (default: the film's main shape). */
  aspect?: Aspect;
}

export interface Player {
  load(): Promise<void>;
  seek(t: number): void;
  update(film: Film, voice: Record<string, number>): Promise<void>;
  reloadScene(id: string, version: number): Promise<void>;
  /** Draw another of the film's shapes; every scene's `setup` runs again at the new size. */
  setAspect(a: Aspect): Promise<void>;
  /** Canvas size of the shape being drawn. */
  readonly size: { width: number; height: number };
  readonly duration: number;
  readonly slots: SceneSlot[];
  /** Messages of scenes that failed to load or render (used by the export page). */
  readonly errors: string[];
  destroy(): void;
}

interface Entry {
  scene: Scene;
  root: HTMLElement;
  ctx: SceneContext;
  mod: SceneModule | null;
  error: string | null;
  loadedKey: string;
  /** Version of the file last loaded; later loads of the same scene reuse it. */
  version?: number;
  /** Bumped by every load; a load whose token is stale drops its result. */
  token: number;
}

const defaultImport = (url: string): Promise<SceneModule> =>
  import(/* @vite-ignore */ url).then((m) => m.default as SceneModule);

const cardStyle =
  "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;" +
  "padding:48px;box-sizing:border-box;text-align:center;font:600 32px system-ui,sans-serif;";

export function createPlayer(container: HTMLElement, opts: PlayerOptions): Player {
  const doImport = opts.importScene ?? defaultImport;
  let film = opts.film;
  let voice = opts.voice;
  let aspect: Aspect = opts.aspect ?? mainAspect(film);
  /** The shape being drawn: the requested one while the film still has it, else the main one. */
  const current = (): Aspect => (chosenAspects(film).includes(aspect) ? aspect : mainAspect(film));
  const size = () => canvasSize(film, current());
  let slots = layout(film, voice);
  let time = 0;
  const entries = new Map<string, Entry>();
  const errorMessages = new Map<string, string>();

  const stage = document.createElement("div");
  stage.style.cssText = "position:relative;overflow:hidden;background:#fff;transform-origin:0 0;";
  const sceneLayer = document.createElement("div");
  sceneLayer.style.cssText = "position:absolute;inset:0;";
  const textLayer = document.createElement("div");
  textLayer.style.cssText = "position:absolute;inset:0;pointer-events:none;";
  stage.append(sceneLayer, textLayer);
  container.appendChild(stage);

  function fit(): void {
    const { width, height } = size();
    stage.style.width = `${width}px`;
    stage.style.height = `${height}px`;
    let k = 1;
    if (opts.scale !== 1 && container.clientWidth > 0 && container.clientHeight > 0) {
      k = Math.min(container.clientWidth / width, container.clientHeight / height);
    }
    stage.style.transform = `scale(${k})`;
  }
  const resizer = typeof ResizeObserver !== "undefined" && opts.scale !== 1
    ? new ResizeObserver(fit) : null;
  resizer?.observe(container);

  function card(root: HTMLElement, text: string, error: boolean): void {
    root.replaceChildren();
    const el = document.createElement("div");
    el.dataset.card = error ? "error" : "placeholder";
    el.style.cssText = cardStyle + (error ? "background:#fde8e8;color:#9b1c1c;" : "background:#eef0f4;color:#4b5563;");
    el.textContent = text;
    root.appendChild(el);
  }

  function fail(e: Entry, err: unknown): void {
    const message = err instanceof Error ? err.message : String(err);
    e.error = message;
    errorMessages.set(e.scene.id, `Scene ${e.scene.id} failed: ${message}`);
    card(e.root, `Scene ${e.scene.id} failed: ${message}`, true);
  }

  function keyOf(s: Scene): string {
    const { width, height } = size();
    return `${s.status}|${s.file ?? ""}|${width}x${height}`;
  }

  function placeholder(s: Scene): string | null {
    if (s.status === "building") return `Building: ${s.title}`;
    if (s.status === "planned" || !s.file) return `Planned: ${s.title}`;
    return null;
  }

  async function loadEntry(e: Entry, explicit?: number): Promise<void> {
    const token = ++e.token;
    if (explicit !== undefined) e.version = explicit;
    const version = explicit ?? opts.versionOf?.(e.scene) ?? e.version;
    e.mod = null;
    e.error = null;
    errorMessages.delete(e.scene.id);
    e.root.replaceChildren();
    const text = placeholder(e.scene);
    if (text) {
      card(e.root, text, false);
      return;
    }
    try {
      let url = opts.sceneUrl(e.scene);
      if (version !== undefined) url += `${url.includes("?") ? "&" : "?"}v=${version}`;
      const mod = await doImport(url);
      if (token !== e.token) return;
      if (!mod || typeof mod.setup !== "function" || typeof mod.render !== "function") {
        throw new Error("scene must export default { setup, render }");
      }
      mod.setup(e.root, e.ctx);
      e.mod = mod;
    } catch (err) {
      if (token === e.token) fail(e, err);
    }
  }

  function syncEntries(): Entry[] {
    const wanted = new Set(film.scenes.map((s) => s.id));
    for (const [id, e] of entries) {
      if (!wanted.has(id)) {
        e.root.remove();
        entries.delete(id);
        errorMessages.delete(id);
      }
    }
    const fresh: Entry[] = [];
    const { width, height } = size();
    for (const [i, scene] of film.scenes.entries()) {
      let e = entries.get(scene.id);
      const length = slots[i].length;
      if (!e) {
        const root = document.createElement("div");
        root.dataset.scene = scene.id;
        root.style.cssText = "position:absolute;inset:0;display:none;overflow:hidden;";
        e = { scene, root, mod: null, error: null, loadedKey: "", token: 0,
          ctx: { width, height, length, random: mulberry32(seedFor(scene.id)) } };
        entries.set(scene.id, e);
      }
      e.scene = scene;
      e.ctx.width = width;
      e.ctx.height = height;
      e.ctx.length = length;
      sceneLayer.appendChild(e.root); // keeps DOM order equal to film order
      if (e.loadedKey !== keyOf(scene)) {
        e.loadedKey = keyOf(scene);
        fresh.push(e);
      }
    }
    return fresh;
  }

  function renderTexts(t: number): void {
    const { width, height } = size();
    // type scales with the short side relative to the film's own: 1 in the main shape and in every derived shape
    // (they all keep the stored short side), so a film made before shapes existed draws its captions as it did
    const unit = Math.min(width, height) / Math.min(film.width, film.height);
    const derived = current() !== mainAspect(film);
    const present = new Set<string>();
    for (const clip of film.texts) {
      let window: [number, number];
      try {
        window = textWindow(clip, slots);
      } catch {
        continue; // a clip pointing to a missing scene is shown by the film check, not here
      }
      present.add(clip.id);
      let el = textLayer.querySelector<HTMLElement>(`[data-text="${CSS.escape(clip.id)}"]`);
      if (!el) {
        el = document.createElement("div");
        el.dataset.text = clip.id;
        textLayer.appendChild(el);
      }
      const title = clip.style === "title";
      const x = (clip.x ?? 0.5) * 100;
      const y = (clip.y ?? (title ? 0.5 : 0.9)) * 100;
      // near an edge the caption wraps instead of leaving the frame
      // only a derived shape limits the width near an edge; the main shape wraps exactly as it always did
      const room = Math.max(0, +(2 * Math.min(x, 100 - x) - 4).toFixed(2));
      const maxWidth = derived ? `min(90%, ${room}%)` : "90%";
      el.style.cssText =
        `position:absolute;left:${x}%;top:${y}%;transform:translate(-50%,-50%);` +
        `width:max-content;max-width:${maxWidth};text-align:center;color:#111;font-family:system-ui,sans-serif;` +
        `font-weight:${title ? 700 : 500};font-size:${(title ? 64 : 32) * unit}px;` +
        `text-shadow:0 0 6px #fff,0 0 12px #fff;` +
        `display:${t >= window[0] && t < window[1] ? "block" : "none"};`;
      el.textContent = clip.text;
    }
    for (const el of Array.from(textLayer.children) as HTMLElement[]) {
      if (!present.has(el.dataset.text ?? "")) el.remove();
    }
  }

  function seek(t: number): void {
    time = t;
    const at = locate(slots, t);
    for (const e of entries.values()) e.root.style.display = at && e.scene.id === at.sceneId ? "block" : "none";
    if (at) {
      const e = entries.get(at.sceneId);
      if (e && e.mod && !e.error) {
        e.ctx.random = mulberry32(seedFor(e.scene.id));
        try {
          e.mod.render(at.sceneTime, e.ctx);
        } catch (err) {
          fail(e, err);
        }
      }
    }
    renderTexts(t);
  }

  const player: Player = {
    async load() {
      fit();
      const fresh = syncEntries();
      await Promise.all(fresh.map((e) => loadEntry(e)));
      seek(time);
    },
    seek,
    async update(nextFilm, nextVoice) {
      film = nextFilm;
      voice = nextVoice;
      slots = layout(film, voice);
      fit();
      const fresh = syncEntries();
      await Promise.all(fresh.map((e) => loadEntry(e)));
      seek(Math.min(time, totalLength(slots)));
    },
    async setAspect(a) {
      aspect = a;
      fit();
      const fresh = syncEntries();
      await Promise.all(fresh.map((e) => loadEntry(e)));
      seek(time);
    },
    get size() {
      return size();
    },
    async reloadScene(id, version) {
      const e = entries.get(id);
      if (!e) return;
      await loadEntry(e, version);
      seek(time);
    },
    get duration() {
      return totalLength(slots);
    },
    get slots() {
      return slots;
    },
    get errors() {
      return Array.from(errorMessages.values());
    },
    destroy() {
      resizer?.disconnect();
      stage.remove();
      entries.clear();
    },
  };
  return player;
}
