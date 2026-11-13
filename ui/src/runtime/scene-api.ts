// The contract between scene files and the player. A scene file is an ES module whose
// default export is a SceneModule. `render` must be a pure function of `t`.

export interface SceneContext {
  width: number;
  height: number;
  length: number; // scene length in seconds
  random: () => number; // seeded; reset before every render call
}

export interface SceneModule {
  setup(root: HTMLElement, ctx: SceneContext): void;
  render(t: number, ctx: SceneContext): void;
}

/** Small seeded random generator: same seed, same sequence. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** FNV-1a 32-bit hash of the scene id, used as that scene's random seed. */
export function seedFor(sceneId: string): number {
  let h = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(sceneId)) {
    h ^= byte;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}
