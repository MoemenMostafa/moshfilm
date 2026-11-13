// TypeScript mirror of aspects.py; both are pinned by tests/fixtures/aspect_cases.json.
import type { Aspect, Film } from "../types";

export const ALL_ASPECTS: Aspect[] = ["16:9", "9:16", "1:1", "4:5"];

export function mainAspect(film: Film): Aspect {
  return film.aspect ?? "16:9";
}

/** Main shape first, then the second one when the film has it. */
export function chosenAspects(film: Film): Aspect[] {
  const main = mainAspect(film);
  return film.second_aspect && film.second_aspect !== main ? [main, film.second_aspect] : [main];
}

function ratio(a: Aspect): [number, number] {
  const [w, h] = a.split(":").map(Number);
  return [w, h];
}

/** The main shape keeps the stored size; any other keeps the short side and derives the long one. */
export function canvasSize(film: Film, aspect: Aspect): { width: number; height: number } {
  if (aspect === mainAspect(film)) return { width: film.width, height: film.height };
  const [a, b] = ratio(aspect);
  const short = Math.min(film.width, film.height);
  // Math.floor(x + 0.5) rounds halves up, the same as aspects.py
  const long = 2 * Math.floor((short * Math.max(a, b)) / Math.min(a, b) / 2 + 0.5);
  if (a === b) return { width: short, height: short };
  return a > b ? { width: long, height: short } : { width: short, height: long };
}

export function aspectSlug(a: Aspect): string {
  return a.replace(":", "x");
}

export function aspectFromSlug(s: string): Aspect | null {
  return ALL_ASPECTS.find((a) => aspectSlug(a) === s) ?? null;
}
