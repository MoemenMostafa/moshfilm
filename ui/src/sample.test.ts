// The bundled sample film "Binary search": its data matches a real binary search, and every
// scene builds and renders in a DOM without throwing, deterministically.
import { describe, expect, it } from "vitest";
import { mulberry32, type SceneContext, type SceneModule } from "./runtime/scene-api";

const MODULES = import.meta.glob("../../src/moshfilm/samples/binary-search/scenes/*.js");

interface Step {
  index: number;
  value: number;
  result: "too big" | "too small" | "found";
}
interface LockersModule {
  LOCKERS: number[];
  TARGET: number;
  STEPS: Step[];
}

// A glob import keeps vue-tsc away from the untyped .js files.
const load = async <T>(name: string): Promise<T> => {
  const importer = MODULES[`../../src/moshfilm/samples/binary-search/scenes/${name}`];
  if (!importer) throw new Error(`sample file missing: ${name}`);
  return (await importer()) as T;
};

function referenceSearch(items: number[], target: number): Step[] {
  const steps: Step[] = [];
  let lo = 0;
  let hi = 15;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const value = items[mid];
    if (value === target) {
      steps.push({ index: mid, value, result: "found" });
      break;
    }
    if (value > target) {
      steps.push({ index: mid, value, result: "too big" });
      hi = mid - 1;
    } else {
      steps.push({ index: mid, value, result: "too small" });
      lo = mid + 1;
    }
  }
  return steps;
}

describe("sample film: Binary search", () => {
  it("STEPS matches a real binary search over LOCKERS for TARGET", async () => {
    const { LOCKERS, TARGET, STEPS } = await load<LockersModule>("lockers.js");
    expect(LOCKERS).toEqual([4, 9, 15, 22, 37, 41, 48, 52, 60, 66, 71, 79, 83, 88, 94, 99]);
    expect(TARGET).toBe(37);
    expect(STEPS).toEqual(referenceSearch(LOCKERS, TARGET));
    expect(STEPS.map((s) => s.index)).toEqual([7, 3, 5, 4]);
  });

  // every shape the film can have, at the default short side (the main one first)
  const SIZES: Array<[string, number, number]> = [["16:9", 1280, 720], ["9:16", 720, 1280], ["1:1", 720, 720], ["4:5", 720, 900]];
  for (const id of ["s1", "s2", "s3", "s4", "s5", "s6"]) {
    for (const [shape, width, height] of SIZES) {
      it(`${id} in ${shape} renders at any time without throwing, the same picture for the same t`, async () => {
        const scene = (await load<{ default: SceneModule }>(`${id}.js`)).default;
        const root = document.createElement("div");
        const ctx: SceneContext = { width, height, length: 9, random: mulberry32(1) };
        scene.setup(root, ctx);
        const snapshot = (t: number): string => {
          ctx.random = mulberry32(1);
          scene.render(t, ctx);
          return root.innerHTML;
        };
        const times = [0, 0.4, 1.3, 2.7, 4.1, 5.5, 6.9, 8.2, 8.95, 9];
        const forward = times.map(snapshot);
        const backward = [...times].reverse().map(snapshot).reverse();
        expect(backward).toEqual(forward);
        expect(root.querySelector("svg")).not.toBeNull();
        expect(root.innerHTML).not.toMatch(/NaN|undefined/);
      });
    }
  }
});
