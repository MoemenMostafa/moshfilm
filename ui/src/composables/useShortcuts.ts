// Keyboard shortcuts for editing: undo, redo and remove. They never fire while the person is typing.

export interface ShortcutHandlers {
  undo(): void;
  redo(): void;
  remove(): void;
}

/** True when the keys belong to the focused control: any input, select, textarea, slider or editable box. */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== "function") return false;
  return !!el.closest("input, select, textarea, [role='slider'], [contenteditable]:not([contenteditable='false'])");
}

/** A focused button owns Delete, Backspace, Space and Enter, but not undo/redo (those work right after a click). */
export function isButtonTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && typeof el.closest === "function" && !!el.closest("button");
}

export function isMac(): boolean {
  return typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform || navigator.userAgent || "");
}

/** Command on a Mac, Ctrl elsewhere. Returns a function that removes the listener. */
export function installShortcuts(handlers: ShortcutHandlers, mac: boolean = isMac()): () => void {
  function onKey(e: KeyboardEvent): void {
    if (e.defaultPrevented || e.isComposing || isTypingTarget(e.target)) return;
    const onButton = isButtonTarget(e.target);
    const mod = mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
    const key = e.key.toLowerCase();
    if (mod && !e.altKey && key === "z") {
      e.preventDefault(); // otherwise the browser would undo in a page that has no text box
      (e.shiftKey ? handlers.redo : handlers.undo)();
    } else if (mod && !mac && !e.altKey && !e.shiftKey && key === "y") {
      e.preventDefault();
      handlers.redo();
    } else if (!onButton && (e.key === "Delete" || e.key === "Backspace") && !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      e.preventDefault(); // Backspace must not navigate back
      handlers.remove();
    }
  }
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}
