// Entry of render.html: the export step drives this page frame by frame.
import { aspectFromSlug, chosenAspects, mainAspect } from "./runtime/aspect";
import { findOverflow, type OverflowHit } from "./runtime/overflow";
import { createPlayer } from "./runtime/player";
import type { Film, VoiceInfo } from "./types";

interface MoshfilmHandle {
  ready: Promise<void>;
  duration: number;
  errors: string[];
  size: { width: number; height: number };
  seek(t: number): Promise<void>;
  /** Content that does not fit the frame at the current time. */
  overflow(): OverflowHit[];
}

const raf = (): Promise<void> => new Promise((resolve) => requestAnimationFrame(() => resolve()));

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return (await res.json()) as T;
}

const container = document.getElementById("stage") as HTMLElement;
const handle: MoshfilmHandle = {
  ready: Promise.resolve(),
  duration: 0,
  errors: [],
  size: { width: 0, height: 0 },
  async seek() {
    throw new Error("render page is not ready");
  },
  overflow: () => [],
};

handle.ready = (async () => {
  try {
    const { film } = await fetchJson<{ film: Film }>("/api/film");
    const info = await fetchJson<VoiceInfo>("/api/voice");
    const voice = Object.fromEntries(Object.entries(info).map(([id, v]) => [id, v.duration]));
    const early: string[] = [];
    const slug = new URLSearchParams(location.search).get("aspect");
    let aspect = mainAspect(film);
    let shown = film;
    if (slug !== null) {
      const wanted = aspectFromSlug(slug);
      if (!wanted) early.push(`unknown aspect ${slug}`);
      else {
        aspect = wanted;
        // a shape the film has not chosen can still be drawn (the layout check tries shapes before they are chosen)
        if (!chosenAspects(film).includes(wanted)) shown = { ...film, second_aspect: wanted };
      }
    }
    const player = createPlayer(container, {
      film: shown, voice, scale: 1, aspect, sceneUrl: (s) => `/film/${s.file}`,
    });
    await player.load();
    handle.size = player.size;
    handle.overflow = () => findOverflow(container.firstElementChild as HTMLElement);
    handle.duration = player.duration;
    handle.errors = [...early, ...player.errors];
    handle.seek = async (t: number) => {
      player.seek(t);
      handle.errors = [...early, ...player.errors];
      await document.fonts.ready;
      await raf();
      await raf();
    };
    player.seek(0);
    handle.errors = [...early, ...player.errors];
  } catch (err) {
    handle.errors.push(err instanceof Error ? err.message : String(err));
  }
})();

(window as unknown as { moshfilm: MoshfilmHandle }).moshfilm = handle;
