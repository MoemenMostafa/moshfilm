import { describe, expect, it, vi } from "vitest";
import { createPlayer } from "./player";
import type { SceneModule } from "./scene-api";
import type { Film, Scene } from "../types";

function scene(id: string, over: Partial<Scene> = {}): Scene {
  return { id, title: `Title ${id}`, file: `scenes/${id}.js`, length: 5, pinned: true,
    status: "ready", voice: { text: "", offset: 0.3, pinned: false }, ...over };
}
function film(scenes: Scene[], texts: Film["texts"] = []): Film {
  return { version: 1, title: "t", width: 1280, height: 720, fps: 30, pace: 1,
    order_pinned: false, voice: { name: "v", rate: "+0%" }, music: null, scenes, texts };
}
function fake(over: Partial<SceneModule> = {}): SceneModule & { render: ReturnType<typeof vi.fn> } {
  return { setup: vi.fn(), render: vi.fn(), ...over } as any;
}
async function make(f: Film, mods: Record<string, SceneModule>) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const player = createPlayer(container, {
    film: f, voice: {}, sceneUrl: (s) => `/film/${s.file}`,
    importScene: async (url) => {
      const id = url.split("/").pop()!.replace(/\.js.*$/, "");
      return mods[id];
    },
  });
  await player.load();
  return { player, container };
}

describe("player", () => {
  it("seek picks scene and passes local time", async () => {
    const s1 = fake(), s2 = fake();
    const { player } = await make(film([scene("s1"), scene("s2")]), { s1, s2 });
    s1.render.mockClear();
    s2.render.mockClear();
    player.seek(6);
    expect(s2.render).toHaveBeenCalled();
    expect(s2.render.mock.calls.at(-1)![0]).toBeCloseTo(1, 3);
    expect(s1.render).not.toHaveBeenCalled();
  });

  it("random is identical for repeated seeks", async () => {
    const seen: number[][] = [];
    const s1 = fake({ render: (_t, ctx) => { seen.push([ctx.random(), ctx.random()]); } });
    const { player } = await make(film([scene("s1")]), { s1 });
    player.seek(1); player.seek(2); player.seek(1);
    expect(seen[0]).toEqual(seen[2]);
    expect(seen[0]).toEqual(seen[1]);
  });

  it("planned scene shows placeholder", async () => {
    const { player, container } = await make(
      film([scene("s1", { status: "planned", file: null }), scene("s2", { status: "building", file: null })]), {});
    player.seek(1);
    expect(container.textContent).toContain("Planned: Title s1");
    player.seek(6);
    expect(container.textContent).toContain("Building: Title s2");
  });

  it("player shows error card for a throwing scene", async () => {
    const s1 = fake({ render: () => { throw new Error("boom"); } });
    const s2 = fake();
    const { player, container } = await make(film([scene("s1"), scene("s2")]), { s1, s2 });
    player.seek(1);
    expect(container.textContent).toContain("Scene s1 failed: boom");
    player.seek(6);
    expect(s2.render).toHaveBeenCalled();
    expect(container.querySelector('[data-scene="s2"]')!.textContent).not.toContain("failed");
  });

  it("a scene that fails to import shows an error card and others keep working", async () => {
    const s2 = fake();
    const container = document.createElement("div");
    const player = createPlayer(container, {
      film: film([scene("s1"), scene("s2")]), voice: {}, sceneUrl: (s) => `/film/${s.file}`,
      importScene: async (url) => { if (url.includes("s1")) throw new SyntaxError("bad"); return s2; },
    });
    await player.load();
    player.seek(1);
    expect(container.textContent).toContain("Scene s1 failed: bad");
    player.seek(6);
    expect(s2.render).toHaveBeenCalled();
  });

  it("text clip visible only inside its window", async () => {
    const f = film([scene("s1")], [{ id: "t1", scene: "s1", text: "hello", start: 1, end: 2,
      pinned: false, style: "caption", x: null, y: null }]);
    const { player, container } = await make(f, { s1: fake() });
    const clip = () => container.querySelector<HTMLElement>('[data-text="t1"]')!;
    player.seek(0.5);
    expect(clip().style.display).toBe("none");
    player.seek(1.5);
    expect(clip().style.display).not.toBe("none");
    expect(clip().textContent).toBe("hello");
    player.seek(2.5);
    expect(clip().style.display).toBe("none");
  });

  it("an edited caption shows its new words after update, without a reload", async () => {
    const clip = (text: string) => ({ id: "t1", scene: "s1", text, start: 0, end: 2,
      pinned: false, text_pinned: true, style: "caption" as const, x: null, y: null });
    const { player, container } = await make(film([scene("s1")], [clip("before")]), { s1: fake() });
    player.seek(1);
    expect(container.querySelector('[data-text="t1"]')!.textContent).toBe("before");
    await player.update(film([scene("s1")], [clip("after the edit")]), {});
    player.seek(1);
    expect(container.querySelector('[data-text="t1"]')!.textContent).toBe("after the edit");
  });

  it("overlapping loads of one scene leave a single setup result in the root", async () => {
    for (const order of ["in-order", "reversed"]) {
      const pending: Array<() => void> = [];
      const setup = vi.fn((root: HTMLElement) => {
        const el = document.createElement("div");
        el.dataset.drawn = "1";
        root.appendChild(el);
      });
      const mod = fake({ setup });
      const container = document.createElement("div");
      const player = createPlayer(container, {
        film: film([scene("s1")]), voice: {}, sceneUrl: (s) => `/film/${s.file}`,
        importScene: (url) => url.includes("v=")
          ? new Promise<SceneModule>((resolve) => { pending.push(() => resolve(mod)); })
          : Promise.resolve(mod),
      });
      await player.load();
      const a = player.reloadScene("s1", 1);
      const b = player.reloadScene("s1", 2);
      const release = order === "in-order" ? pending : [...pending].reverse();
      release.forEach((fn) => fn());
      await Promise.all([a, b]);
      const root = container.querySelector('[data-scene="s1"]')!;
      expect(root.querySelectorAll("[data-drawn]").length, order).toBe(1);
      expect(setup).toHaveBeenCalledTimes(2); // initial load + the one surviving reload
    }
  });

  it("a load overlapping an update sets each scene up once", async () => {
    const s1 = fake(), s2 = fake();
    const f = film([scene("s1"), scene("s2")]);
    const container = document.createElement("div");
    const player = createPlayer(container, {
      film: f, voice: {}, sceneUrl: (s) => `/film/${s.file}`,
      importScene: async (url) => {
        await new Promise((r) => setTimeout(r, 5));
        return url.includes("s1") ? s1 : s2;
      },
    });
    const first = player.load();
    const second = player.update(film([scene("s1"), scene("s2")]), { s1: 1 });
    await Promise.all([first, second]);
    expect(s1.setup).toHaveBeenCalledTimes(1);
    expect(s2.setup).toHaveBeenCalledTimes(1);
    expect(container.querySelectorAll("[data-scene]").length).toBe(2);
  });

  it("a changed scene file is re-imported under a new URL, and later reloads keep that version", async () => {
    const urls: string[] = [];
    const f = film([scene("s1")]);
    const container = document.createElement("div");
    const player = createPlayer(container, {
      film: f, voice: {}, sceneUrl: (s) => `/film/${s.file}`,
      importScene: async (url) => { urls.push(url); return fake(); },
    });
    await player.load();
    await player.reloadScene("s1", 111);
    // status flips planned -> ready: the scene loads again, and must not fall back to the cached un-versioned module
    await player.update(film([scene("s1", { status: "building" })]), {});
    await player.update(film([scene("s1", { status: "ready" })]), {});
    expect(urls).toEqual(["/film/scenes/s1.js", "/film/scenes/s1.js?v=111", "/film/scenes/s1.js?v=111"]);
  });

  it("versionOf supplies the version for a first load", async () => {
    const urls: string[] = [];
    const container = document.createElement("div");
    const player = createPlayer(container, {
      film: film([scene("s1")]), voice: {}, sceneUrl: (s) => `/film/${s.file}`, versionOf: () => 7,
      importScene: async (url) => { urls.push(url); return fake(); },
    });
    await player.load();
    expect(urls).toEqual(["/film/scenes/s1.js?v=7"]);
  });

  it("reloading a scene shows its new drawing and replaces the old one", async () => {
    const draw = (label: string) => fake({ setup: (root: HTMLElement) => { root.textContent = label; } });
    const mods: Record<string, SceneModule> = { s1: draw("old") };
    const container = document.createElement("div");
    const player = createPlayer(container, {
      film: film([scene("s1")]), voice: {}, sceneUrl: (s) => `/film/${s.file}`,
      importScene: async (url) => (url.includes("v=2") ? draw("new") : mods.s1),
    });
    await player.load();
    expect(container.querySelector('[data-scene="s1"]')!.textContent).toBe("old");
    await player.reloadScene("s1", 2);
    expect(container.querySelector('[data-scene="s1"]')!.textContent).toBe("new");
  });
});


describe("shapes", () => {
  const wide = (over: Partial<Film> = {}): Film => ({ ...film([scene("s1")]), version: 2, aspect: "16:9",
    second_aspect: "9:16", ...over });
  const clipAt = (x: number | null, style: "caption" | "title" = "caption") => ({ id: "t1", scene: "s1", text: "hello",
    start: 0, end: 4, pinned: false, style, x, y: null });

  async function makeAt(f: Film, mod: SceneModule, aspect?: "9:16" | "16:9") {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const player = createPlayer(container, {
      film: f, voice: {}, aspect, sceneUrl: (s) => `/film/${s.file}`, importScene: async () => mod,
    });
    await player.load();
    return { player, container };
  }

  it("passes the chosen shape's size to setup and render", async () => {
    const seen: number[][] = [];
    const mod = fake({ setup: (_r, ctx) => { seen.push([ctx.width, ctx.height]); },
      render: (_t, ctx) => { seen.push([ctx.width, ctx.height]); } });
    const { player, container } = await makeAt(wide(), mod, "9:16");
    player.seek(1);
    expect(seen.length).toBeGreaterThanOrEqual(2); // setup, then render
    expect(new Set(seen.map((x) => x.join("x")))).toEqual(new Set(["720x1280"]));
    expect(player.size).toEqual({ width: 720, height: 1280 });
    expect((container.firstElementChild as HTMLElement).style.width).toBe("720px");
  });

  it("re-runs setup when the canvas size changes", async () => {
    const sizes: number[][] = [];
    const mod = fake({ setup: vi.fn((root: HTMLElement, ctx) => {
      sizes.push([ctx.width, ctx.height]);
      const d = document.createElement("div");
      d.dataset.drawn = "1";
      root.appendChild(d);
    }) });
    const { player, container } = await makeAt(wide(), mod);
    await player.setAspect("9:16");
    expect(sizes).toEqual([[1280, 720], [720, 1280]]);
    expect(container.querySelectorAll("[data-drawn]").length).toBe(1);
    // the main shape itself changes: 9:16 main keeps the short side
    await player.update(wide({ aspect: "9:16", second_aspect: "16:9", width: 720, height: 1280 }), {});
    await player.setAspect("16:9");
    expect(sizes.at(-1)).toEqual([1280, 720]);
    await player.update(wide({ aspect: "1:1", second_aspect: null, width: 720, height: 720 }), {});
    expect(sizes.at(-1)).toEqual([720, 720]);
    expect(container.querySelectorAll("[data-drawn]").length).toBe(1);
  });

  it("falls back to main when the chosen shape is removed", async () => {
    const { player } = await makeAt(wide(), fake(), "9:16");
    expect(player.size).toEqual({ width: 720, height: 1280 });
    await player.update(wide({ second_aspect: null }), {});
    expect(player.size).toEqual({ width: 1280, height: 720 });
  });

  it("caption near an edge wraps inside a derived shape", async () => {
    const f = { ...wide(), texts: [clipAt(0.95), { ...clipAt(null), id: "t2" }] };
    const { player, container } = await makeAt(f, fake(), "9:16");
    player.seek(1);
    const el = (id: string) => container.querySelector<HTMLElement>(`[data-text="${id}"]`)!;
    expect(el("t1").style.maxWidth).toBe("min(90%, 6%)");
    expect(el("t2").style.maxWidth).toBe("min(90%, 96%)");
    expect(el("t1").style.fontSize).toBe("32px");
  });

  it("the main shape wraps a caption at x 0.95 exactly as before shapes existed", async () => {
    const f = { ...wide(), texts: [clipAt(0.95)] };
    const { player, container } = await makeAt(f, fake());
    player.seek(1);
    const el = container.querySelector<HTMLElement>('[data-text="t1"]')!;
    expect(el.style.maxWidth).toBe("90%");
    expect(el.style.fontSize).toBe("32px");
  });

  it("an old 1080p or tiny film keeps 32 px captions (64 for titles)", async () => {
    for (const [w, h] of [[1920, 1080], [320, 180]]) {
      const f = { ...film([scene("s1")], [clipAt(null), { ...clipAt(null, "title"), id: "t2" }]), width: w, height: h };
      const { player, container } = await makeAt(f, fake());
      player.seek(1);
      expect(container.querySelector<HTMLElement>('[data-text="t1"]')!.style.fontSize).toBe("32px");
      expect(container.querySelector<HTMLElement>('[data-text="t2"]')!.style.fontSize).toBe("64px");
    }
  });
});
