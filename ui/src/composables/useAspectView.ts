// Which of the film's shapes the preview shows: the main one or the second. Shared by the preview, the comment
// layer and the chat panel, so a comment is made on (and pinned to) the shape you are looking at.
import { computed, ref, watch, type ComputedRef, type Ref } from "vue";
import { canvasSize, chosenAspects, mainAspect } from "../runtime/aspect";
import type { Aspect } from "../types";
import { useFilm } from "./useFilm";

type View = "main" | "second";
const viewState = ref<View>("main");
/** The shared state itself, for tests that reset it. */
export const aspectViewState = viewState;

export interface AspectView {
  view: Ref<View>;
  /** The shape being shown (always the main one when the film has no second shape). */
  aspect: ComputedRef<Aspect>;
  size: ComputedRef<{ width: number; height: number }>;
  hasSecond: ComputedRef<boolean>;
  set(v: View): void;
}

export function useAspectView(): AspectView {
  const store = useFilm();
  const hasSecond = computed(() => {
    const f = store.film.value;
    return !!f && chosenAspects(f).length > 1;
  });
  const aspect = computed<Aspect>(() => {
    const f = store.film.value;
    if (!f) return "16:9";
    const [main, second] = chosenAspects(f);
    return viewState.value === "second" && second ? second : mainAspect(f);
  });
  const size = computed(() => {
    const f = store.film.value;
    return f ? canvasSize(f, aspect.value) : { width: 1280, height: 720 };
  });
  // the second shape was removed while it was shown: drop back to main (and stay there if it comes back)
  watch(hasSecond, (has) => { if (!has) viewState.value = "main"; }, { flush: "sync" });
  function set(v: View): void {
    viewState.value = v === "second" && !hasSecond.value ? "main" : v;
  }
  return { view: viewState, aspect, size, hasSecond, set };
}
