import { onScopeDispose, watch, type Ref } from "vue";
import type { Playhead } from "./usePlayhead";

export interface VoiceClip {
  url: string;
  /** Timeline second where the clip starts. */
  start: number;
  /** Playback speed-up (>= 1): the clip is `duration / speed` seconds wide on the timeline. */
  speed: number;
  /** Length of the audio file itself, in seconds. */
  duration: number;
}
export interface MusicBed {
  url: string;
  volume: number;
}

/** A generated sound effect placed on the timeline (SFX are played at their own volume and never ducked). */
export interface SfxPlay {
  id: string;
  url: string;
  /** Timeline second where it starts. */
  start: number;
  /** Length of the audio file itself, in seconds. */
  duration: number;
  volume: number;
  /** Timeline second the sound is cut at (its scene's end): it fades out over the 80 ms before and stops. */
  end?: number;
}

/** Music level while a voice clip is playing (preview approximation of the export's sidechain ducking). */
const DUCK = 0.4;
/** Only re-seek a playing element when it drifted further than this from where the playhead says it should be. */
const DRIFT = 0.3;
/** A sound effect is triggered anywhere in this window after its start, even a 20 ms tick. */
const SFX_WINDOW = 0.25;
/** A playhead move bigger than this in one tick is a seek, not playback. */
const JUMP = 0.4;
/** Fade-out before a scene end (mirrors timing.SFX_SCENE_FADE). */
const SCENE_FADE = 0.08;

/** Which clip covers timeline time `t` (clip = [start, start + duration/speed)), and where in the audio file that is. */
export function activeClip(clips: VoiceClip[], t: number): { index: number; offset: number } | null {
  for (let i = 0; i < clips.length; i++) {
    const c = clips[i];
    if (t >= c.start && t < c.start + c.duration / c.speed) return { index: i, offset: (t - c.start) * c.speed };
  }
  return null;
}

function start(a: HTMLAudioElement): void {
  try {
    void a.play()?.catch(() => { /* browser blocked autoplay: the next click on Play retries */ });
  } catch {
    /* media not available */
  }
}

/**
 * Keeps one audio element per voice clip, plus the music bed and the sound effects, in step with the shared
 * playhead: play/pause/seek follow it, each clip plays at its own speed, music dips under the voice.
 * A sound effect element is kept per `id + url` and rebuilt only when that changes.
 */
export function useAudioSync(head: Playhead, clips: Ref<VoiceClip[]>, music: Ref<MusicBed | null>,
  sfx?: Ref<SfxPlay[]>) {
  let voiceEls: HTMLAudioElement[] = [];
  let musicEl: HTMLAudioElement | null = null;
  let musicUrl: string | null = null;
  const sfxEls = new Map<string, { el: HTMLAudioElement; play: SfxPlay; started: boolean }>();
  let prevT = 0;

  function buildSfx(): void {
    const wanted = new Map((sfx?.value ?? []).map((p) => [p.id + "\n" + p.url, p]));
    for (const [key, entry] of sfxEls) {
      if (!wanted.has(key)) {
        entry.el.pause();
        sfxEls.delete(key);
      }
    }
    for (const [key, play] of wanted) {
      const have = sfxEls.get(key);
      if (have) have.play = play;
      else {
        const el = new Audio(play.url);
        el.preload = "auto";
        sfxEls.set(key, { el, play, started: false });
      }
    }
  }

  function buildVoices(): void {
    voiceEls.forEach((a) => a.pause());
    voiceEls = clips.value.map((c) => {
      const a = new Audio(c.url);
      a.preload = "auto";
      return a;
    });
  }

  function buildMusic(): void {
    const m = music.value;
    if (!m) {
      musicEl?.pause();
      musicEl = null;
      musicUrl = null;
      return;
    }
    if (m.url !== musicUrl) {
      musicEl?.pause();
      musicEl = new Audio(m.url);
      musicEl.loop = false;
      musicUrl = m.url;
    }
  }

  function place(a: HTMLAudioElement, t: number, rate: number): void {
    if (!head.playing.value || !Number.isFinite(a.currentTime) || Math.abs(a.currentTime - t) > DRIFT || a.paused) {
      a.currentTime = t;
    }
    a.playbackRate = rate;
    (a as HTMLAudioElement & { preservesPitch: boolean }).preservesPitch = true;
  }

  function sync(): void {
    const t = head.time.value;
    const hit = activeClip(clips.value, t);
    voiceEls.forEach((a, i) => {
      if (hit?.index === i) return;
      if (head.playing.value || !a.paused) a.pause();
    });
    if (hit) {
      const a = voiceEls[hit.index];
      const wasPlaying = !a.paused;
      place(a, hit.offset, clips.value[hit.index].speed);
      if (head.playing.value && !wasPlaying) start(a);
      if (!head.playing.value) a.pause();
    }
    const playing = head.playing.value;
    const jumped = Math.abs(t - prevT) > JUMP || t < prevT - 0.05; // a seek, not a normal tick
    for (const entry of sfxEls.values()) {
      const { el, play } = entry;
      const win = Math.max(play.duration, SFX_WINDOW); // short sounds need room: play() starts late and ticks are coarse
      const limit = play.end ?? Infinity;
      const inWin = t >= play.start && t < Math.min(play.start + win, limit);
      const crossed = playing && !jumped && prevT < play.start && t >= play.start; // a coarse tick skipped over it
      const fade = play.end === undefined ? 1 : Math.min(1, Math.max(0, (play.end - t) / SCENE_FADE));
      el.volume = Math.min(1, Math.max(0, play.volume * fade));
      if (playing && play.end !== undefined && t >= play.end && (entry.started || !el.paused)) { // cut at the scene end
        el.pause();
        continue;
      }
      if (!playing) {
        if (entry.started || !el.paused) el.pause();
        entry.started = false;
        if (inWin) el.currentTime = t - play.start < play.duration ? t - play.start : 0;
        continue;
      }
      if (jumped || t < play.start) { // seeking or going back stops it; running past its window does not
        if (entry.started || !el.paused) el.pause();
        entry.started = false;
      }
      if ((inWin || (crossed && t < limit)) && !entry.started) {
        const offset = t - play.start;
        el.currentTime = offset < play.duration ? offset : 0; // a late tick plays the sound from its start
        entry.started = true;
        start(el);
      }
    }
    prevT = t;
    if (musicEl && music.value) {
      musicEl.volume = Math.min(1, Math.max(0, music.value.volume * (hit ? DUCK : 1)));
      const wasPlaying = !musicEl.paused;
      const ended = musicEl.duration > 0 && t >= musicEl.duration;
      if (ended) {
        musicEl.pause();
      } else {
        place(musicEl, t, 1);
        if (head.playing.value && !wasPlaying) start(musicEl);
      }
      if (!head.playing.value) musicEl.pause();
    }
  }

  buildVoices();
  buildMusic();
  buildSfx();
  const stops = [
    ...(sfx ? [watch(sfx, () => { buildSfx(); sync(); }, { flush: "sync", deep: true })] : []),
    watch(clips, () => { buildVoices(); sync(); }, { flush: "sync", deep: true }),
    watch(music, () => { buildMusic(); sync(); }, { flush: "sync", deep: true }),
    watch([head.time, head.playing], sync, { flush: "sync" }),
  ];

  function dispose(): void {
    stops.forEach((s) => s());
    voiceEls.forEach((a) => a.pause());
    musicEl?.pause();
    sfxEls.forEach((e) => e.el.pause());
  }
  onScopeDispose(dispose);

  return { dispose, musicElement: () => musicEl };
}
