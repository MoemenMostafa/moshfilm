import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { installShortcuts, isTypingTarget } from "./useShortcuts";

function key(target: Element | Window, init: KeyboardEventInit): KeyboardEvent {
  const ev = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  (target instanceof Window ? window : target).dispatchEvent(ev);
  return ev;
}

describe("shortcuts", () => {
  let handlers: { undo: Mock<() => void>; redo: Mock<() => void>; remove: Mock<() => void> };
  let stop: () => void;

  function setup(mac: boolean) {
    handlers = { undo: vi.fn<() => void>(), redo: vi.fn<() => void>(), remove: vi.fn<() => void>() };
    stop = installShortcuts(handlers, mac);
  }
  beforeEach(() => document.body.replaceChildren());
  afterEach(() => stop?.());

  it("Cmd+Z undoes and Shift+Cmd+Z redoes on a Mac, and the browser's own undo is blocked", () => {
    setup(true);
    expect(key(document.body, { key: "z", metaKey: true }).defaultPrevented).toBe(true);
    key(document.body, { key: "Z", metaKey: true, shiftKey: true });
    expect(handlers.undo).toHaveBeenCalledTimes(1);
    expect(handlers.redo).toHaveBeenCalledTimes(1);
  });

  it("uses Ctrl elsewhere (and Ctrl+Y for redo), and ignores Ctrl on a Mac", () => {
    setup(false);
    key(document.body, { key: "z", ctrlKey: true });
    key(document.body, { key: "z", ctrlKey: true, shiftKey: true });
    key(document.body, { key: "y", ctrlKey: true });
    key(document.body, { key: "z", metaKey: true });
    expect(handlers.undo).toHaveBeenCalledTimes(1);
    expect(handlers.redo).toHaveBeenCalledTimes(2);
    stop();
    setup(true);
    key(document.body, { key: "z", ctrlKey: true });
    expect(handlers.undo).not.toHaveBeenCalled();
  });

  it("Delete and Backspace remove the selection; with a modifier they do not", () => {
    setup(true);
    key(document.body, { key: "Delete" });
    key(document.body, { key: "Backspace" });
    key(document.body, { key: "Backspace", metaKey: true });
    key(document.body, { key: "Delete", shiftKey: true });
    expect(handlers.remove).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["input", () => Object.assign(document.createElement("input"), { type: "text" })],
    ["input without a type", () => document.createElement("input")],
    ["textarea", () => document.createElement("textarea")],
    ["select", () => document.createElement("select")],
    ["contenteditable", () => {
      const d = document.createElement("div");
      d.setAttribute("contenteditable", "true");
      return d;
    }],
  ])("does nothing while typing in %s", (_name, make) => {
    setup(true);
    const el = make();
    document.body.append(el);
    for (const init of [{ key: "z", metaKey: true }, { key: "z", metaKey: true, shiftKey: true },
      { key: "Delete" }, { key: "Backspace" }]) {
      expect(key(el, init).defaultPrevented).toBe(false);
    }
    expect(handlers.undo).not.toHaveBeenCalled();
    expect(handlers.redo).not.toHaveBeenCalled();
    expect(handlers.remove).not.toHaveBeenCalled();
  });

  it.each([
    ["a range slider", () => Object.assign(document.createElement("input"), { type: "range" })],
    ["a checkbox", () => Object.assign(document.createElement("input"), { type: "checkbox" })],
    ["a file input", () => Object.assign(document.createElement("input"), { type: "file" })],
    ["an ARIA slider", () => {
      const d = document.createElement("div");
      d.setAttribute("role", "slider");
      return d;
    }],
  ])("%s keeps its own keys: no undo, redo or remove, and no preventDefault", (_n, make) => {
    setup(true);
    const el = make();
    document.body.append(el);
    for (const init of [{ key: "z", metaKey: true }, { key: "z", metaKey: true, shiftKey: true },
      { key: "Delete" }, { key: "Backspace" }]) {
      expect(key(el, init).defaultPrevented).toBe(false);
    }
    expect(handlers.undo).not.toHaveBeenCalled();
    expect(handlers.redo).not.toHaveBeenCalled();
    expect(handlers.remove).not.toHaveBeenCalled();
    expect(isTypingTarget(el)).toBe(true);
  });

  it("a focused button blocks Delete and Backspace but not undo or redo", () => {
    setup(false);
    const btn = document.createElement("button");
    document.body.append(btn);
    expect(key(btn, { key: "Delete" }).defaultPrevented).toBe(false);
    expect(key(btn, { key: "Backspace" }).defaultPrevented).toBe(false);
    expect(handlers.remove).not.toHaveBeenCalled();
    key(btn, { key: "z", ctrlKey: true });
    key(btn, { key: "z", ctrlKey: true, shiftKey: true });
    key(btn, { key: "y", ctrlKey: true });
    expect(handlers.undo).toHaveBeenCalledTimes(1);
    expect(handlers.redo).toHaveBeenCalledTimes(2);
  });

  it("stop() removes the listener", () => {
    setup(true);
    stop();
    key(document.body, { key: "z", metaKey: true });
    expect(handlers.undo).not.toHaveBeenCalled();
  });
});
