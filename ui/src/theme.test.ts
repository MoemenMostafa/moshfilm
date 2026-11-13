import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import ThemeSwitch from "./components/ThemeSwitch.vue";
import { THEME_KEY, applyTheme, initTheme, loadTheme, useTheme } from "./theme";

const root = document.documentElement;

beforeEach(() => { localStorage.clear(); root.removeAttribute("data-theme"); initTheme(); });
afterEach(() => { vi.restoreAllMocks(); });

describe("theme", () => {
  it("defaults to System: no data-theme and nothing stored", () => {
    expect(loadTheme()).toBe("system");
    expect(root.hasAttribute("data-theme")).toBe(false);
    const w = mount(ThemeSwitch);
    expect(w.get('[data-theme-option="system"]').attributes("aria-pressed")).toBe("true");
    expect(w.get('[data-theme-option="dark"]').attributes("aria-pressed")).toBe("false");
  });

  it("choosing Dark sets data-theme, stores it, and System clears both", async () => {
    const w = mount(ThemeSwitch);
    await w.get('[data-theme-option="dark"]').trigger("click");
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(w.get('[data-theme-option="dark"]').attributes("aria-pressed")).toBe("true");
    await w.get('[data-theme-option="light"]').trigger("click");
    expect(root.getAttribute("data-theme")).toBe("light");
    await w.get('[data-theme-option="system"]').trigger("click");
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
  });

  it("a stored choice wins on the next start", () => {
    localStorage.setItem(THEME_KEY, "light");
    expect(initTheme()).toBe("light");
    expect(root.getAttribute("data-theme")).toBe("light");
    const w = mount(ThemeSwitch);
    expect(w.get('[data-theme-option="light"]').attributes("aria-pressed")).toBe("true");
  });

  it("ignores junk in storage", () => {
    localStorage.setItem(THEME_KEY, "purple");
    expect(loadTheme()).toBe("system");
  });

  it("still switches for this visit when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(loadTheme()).toBe("system");
    useTheme().set("dark");
    expect(root.getAttribute("data-theme")).toBe("dark");
    applyTheme("system");
  });
});
