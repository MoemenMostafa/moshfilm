import { inject, provide, ref, watch, type InjectionKey, type Ref } from "vue";

export interface Playhead {
  time: Ref<number>;
  playing: Ref<boolean>;
  play(): void;
  pause(): void;
  toggle(): void;
  seek(t: number): void;
}

/** One playhead for the whole editor: App creates it and provides it (preview, timeline, panel share it). */
export const PlayheadKey: InjectionKey<Playhead> = Symbol("playhead");

export function usePlayhead(duration: Ref<number>): Playhead {
  const time = ref(0);
  const playing = ref(false);
  let handle: number | null = null;
  let last = 0;

  const clamp = (t: number): number => Math.min(Math.max(t, 0), Math.max(duration.value, 0));

  function cancel(): void {
    if (handle !== null) cancelAnimationFrame(handle);
    handle = null;
  }

  function tick(stamp: number): void {
    handle = null;
    if (!playing.value) return;
    const next = time.value + (stamp - last) / 1000;
    last = stamp;
    if (next >= duration.value) {
      time.value = clamp(duration.value);
      playing.value = false;
      return;
    }
    time.value = next;
    handle = requestAnimationFrame(tick);
  }

  function pause(): void {
    playing.value = false;
    cancel();
  }

  function play(): void {
    if (playing.value || duration.value <= 0) return;
    if (time.value >= duration.value) time.value = 0;
    playing.value = true;
    last = performance.now();
    cancel();
    handle = requestAnimationFrame(tick);
  }

  watch(duration, () => {
    if (time.value > duration.value) time.value = clamp(time.value);
  }, { flush: "sync" });

  return {
    time,
    playing,
    play,
    pause,
    toggle: () => (playing.value ? pause() : play()),
    seek: (t) => { time.value = clamp(t); },
  };
}

export const providePlayhead = (p: Playhead): void => provide(PlayheadKey, p);

export function useSharedPlayhead(): Playhead {
  const p = inject(PlayheadKey);
  if (!p) throw new Error("no playhead provided: call providePlayhead in App");
  return p;
}
