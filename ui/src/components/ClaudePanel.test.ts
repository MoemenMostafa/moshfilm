import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import type { Activity, Film, Message, Proposal, QueueItem, QueueSnapshot } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";
import { layout } from "../runtime/timing";
import { PlayheadKey } from "../composables/usePlayhead";
import { aspectViewState } from "../composables/useAspectView";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, postChat: vi.fn(async () => ({})), approve: vi.fn(async () => ({})), reject: vi.fn(async () => ({})) };
});
import * as api from "../api";
import ClaudePanel from "./ClaudePanel.vue";

const film = { title: "t", texts: [], scenes: [
  { id: "s1", title: "Open the middle", length: 5, voice: { text: "", offset: 0.3 } }] } as unknown as Film;

const item = (id: string, created: string, extra: Partial<QueueItem> = {}): QueueItem => ({ id, kind: "chat", text: `text ${id}`, created,
  state: "queued", time: null, scene: null, scene_time: null, point: null, attachment: null,
  delivered_at: null, resolved_at: null, ...extra });
const msg = (id: string, created: string, reply_to: string | null): Message =>
  ({ id, role: "claude" as const, text: `msg ${id}`, reply_to, created });

function mountPanel(q: Partial<QueueSnapshot> = {}, proposals: Proposal[] = [], f: Film = film, act: Partial<Activity> = {}) {
  const activity = ref<Activity>({ turn: null, plan: [], ...act });
  const queue = ref<QueueSnapshot>({ items: [], messages: [], status: null, connected: false, ...q });
  const refreshQueue = vi.fn(async () => {});
  const store = { film: ref(f), folder: ref("/my films/demo"), queue, activity, slots: ref(layout(f, {})), proposals: ref(proposals),
    focusItem: ref<string | null>(null), refreshQueue } as unknown as FilmStore;
  const time = ref(0);
  const head = { time, playing: ref(false), play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), seek: vi.fn() };
  const w = mount(ClaudePanel, { global: { provide: { [FilmKey as symbol]: store, [PlayheadKey as symbol]: head } } });
  return { w, head, store, refreshQueue, time };
}

beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

describe("ClaudePanel", () => {
  it("shows start command when not connected", () => {
    const { w } = mountPanel({ items: [item("q1", "2026-01-01T00:00:01")] });
    expect(w.text()).toContain("Claude not connected");
    expect(w.get('[data-testid="start-box"]').text()).toContain("Start Claude Code for this film:");
    expect(w.text()).toContain('cd "/my films/demo" && claude "Use the moshfilm skill to work on this film"');
    expect(w.text()).toContain("delivered when Claude connects");
  });

  it("hides command when connected and shows status", () => {
    const { w } = mountPanel({ connected: true, status: "building scene 4 of 6" });
    expect(w.text()).toContain("Claude connected");
    expect(w.find('[data-testid="start-box"]').exists()).toBe(false);
    expect(w.get('[data-testid="status"]').text()).toBe("Claude: building scene 4 of 6");
  });

  it("hides the status line when null", () => {
    expect(mountPanel({ connected: true }).w.find('[data-testid="status"]').exists()).toBe(false);
  });

  it("thread merges items and replies by time", () => {
    const { w } = mountPanel({ connected: true,
      items: [item("q2", "2026-01-01T00:00:20", { state: "resolved" }), item("q1", "2026-01-01T00:00:10", { state: "delivered" })],
      messages: [msg("m2", "2026-01-01T00:00:25", "q2"), msg("m1", "2026-01-01T00:00:15", "q1"),
        msg("m3", "2026-01-01T00:00:30", null)] });
    const order = w.findAll("[data-item], [data-message]").map((e) => e.attributes("data-item") ?? e.attributes("data-message"));
    expect(order).toEqual(["q1", "m1", "q2", "m2", "m3"]);
    expect(w.get('[data-item="q1"] .state').text()).toBe("delivered");
    expect(w.get('[data-item="q2"] .state').text()).toBe("resolved");
  });

  it("comment item click seeks", async () => {
    const { w, head } = mountPanel({ items: [item("q1", "2026-01-01T00:00:10",
      { kind: "comment", time: 12.3, scene: "s1", text: "too fast" })] });
    const el = w.get('[data-item="q1"]');
    expect(el.text()).toContain('💬 at 0:12.3 · scene "Open the middle"');
    await el.trigger("click");
    expect(head.seek).toHaveBeenCalledWith(12.3);
  });

  it("Enter sends chat, Shift+Enter does not", async () => {
    const { w, refreshQueue } = mountPanel();
    const ta = w.get("textarea");
    await ta.setValue("make it about bees");
    await ta.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(api.postChat).not.toHaveBeenCalled();
    await ta.trigger("keydown", { key: "Enter" });
    await flushPromises();
    expect(api.postChat).toHaveBeenCalledWith("make it about bees", undefined, undefined);
    expect((ta.element as HTMLTextAreaElement).value).toBe("");
    expect(refreshQueue).toHaveBeenCalled();
  });

  it("attached file goes with the message", async () => {
    const { w } = mountPanel();
    const f = new File(["x"], "notes.md");
    const input = w.get('[data-testid="picker"]');
    Object.defineProperty(input.element, "files", { value: [f] });
    await input.trigger("change");
    expect(w.text()).toContain("notes.md");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(api.postChat).toHaveBeenCalledWith("", f, undefined);
  });

  it("empty film shows the starter prompt", () => {
    const empty = { ...film, scenes: [] } as Film;
    expect(mountPanel({}, [], empty).w.text())
      .toContain("What should the film be about? Give a topic, paste a script, or attach a document.");
    expect(mountPanel({ items: [item("q1", "2026-01-01T00:00:10")] }).w.text()).not.toContain("What should the film");
  });

  it("scene list card shows in the panel; Change… prefills the composer", async () => {
    const p: Proposal = { id: "p1", created: "", summary: "", needs_approval: true, status: "awaiting_approval",
      held: [], error: null, changes: [{ op: "add_scene", scene: { id: "a", title: "A", length: 4 } }] };
    const { w } = mountPanel({}, [p, { ...p, id: "p0", status: "applied" }]);
    expect(w.findAll("[data-proposal]")).toHaveLength(1);
    await w.get('[data-action="change"]').trigger("click");
    expect((w.get("textarea").element as HTMLTextAreaElement).value).toBe("About the scene list: ");
  });

  it("focusItem highlights and clears", async () => {
    const { w, store } = mountPanel({ items: [item("q1", "2026-01-01T00:00:10")] });
    store.focusItem.value = "q1";
    await flushPromises();
    expect(w.get('[data-item="q1"]').classes()).toContain("hot");
    expect(store.focusItem.value).toBeNull();
  });

  describe("attach frame", () => {
    const send = async (w: ReturnType<typeof mountPanel>["w"], text = "look") => {
      await w.get("textarea").setValue(text);
      await w.get("form").trigger("submit");
      await flushPromises();
    };

    it("toggle is off by default and nothing is attached", async () => {
      const { w, time } = mountPanel();
      time.value = 2;
      const btn = w.get('[data-action="attach-frame"]');
      expect(btn.attributes("aria-pressed")).toBe("false");
      expect(btn.text()).toContain("Attach frame");
      await send(w);
      expect(api.postChat).toHaveBeenCalledWith("look", undefined, undefined);
    });

    it("when on, sends the playhead with scene and title, and remembers the choice per film", async () => {
      const { w, time } = mountPanel();
      await w.get('[data-action="attach-frame"]').trigger("click");
      expect(w.get('[data-action="attach-frame"]').attributes("aria-pressed")).toBe("true");
      time.value = 2.5;
      await send(w);
      expect(api.postChat).toHaveBeenCalledWith("look", undefined,
        { time: 2.5, scene: "s1", sceneTitle: "Open the middle" });
      expect(localStorage.getItem("moshfilm.attachFrame:/my films/demo")).toBe("1");
      expect(mountPanel().w.get('[data-action="attach-frame"]').attributes("aria-pressed")).toBe("true");
    });

    it("works when localStorage throws", async () => {
      const real = Storage.prototype.getItem;
      Storage.prototype.getItem = () => { throw new Error("blocked"); };
      try {
        const { w } = mountPanel();
        expect(w.get('[data-action="attach-frame"]').attributes("aria-pressed")).toBe("false");
      } finally {
        Storage.prototype.getItem = real;
      }
    });

    it("shows a chip on a message with a frame; clicking it seeks and does not select the item", async () => {
      const { w, head } = mountPanel({ items: [item("q1", "2026-01-01T00:00:10",
        { at: { time: 2.5, scene: "s1", sceneTitle: "Open the middle" } })] });
      const chip = w.get('[data-testid="at-chip"]');
      expect(chip.text()).toBe("⏸ 0:02.5 · 01 Open the middle");
      await chip.trigger("click");
      expect(head.seek).toHaveBeenCalledWith(2.5);
    });

    it("no chip without a frame", () => {
      expect(mountPanel({ items: [item("q1", "2026-01-01T00:00:10")] }).w.find('[data-testid="at-chip"]').exists()).toBe(false);
    });
  });

  describe("working card placement", () => {
    const turn = (extra = {}) => ({ id: "t", started: "2026-01-01T00:00:00.000Z", updated: "", ended: null, item: null,
      steps: [{ id: 1, label: "Reading scene 01", state: "done" as const, started: "", ended: null }], ...extra });

    it("sits under the item the turn was started for, after its replies", () => {
      const { w } = mountPanel({ items: [item("q1", "2026-01-01T00:00:10", { state: "delivered" }),
        item("q2", "2026-01-01T00:00:20", { state: "queued" })],
        messages: [msg("m1", "2026-01-01T00:00:15", "q1")] }, [], film, { turn: turn({ item: "q1" }) });
      const entries = w.findAll(".entry");
      expect(entries[0].find('[data-testid="working-card"]').exists()).toBe(true);
      expect(entries[1].find('[data-testid="working-card"]').exists()).toBe(false);
      expect(w.findAll('[data-testid="working-card"]')).toHaveLength(1);
    });

    it("while working with no stored item it follows the latest delivered item", () => {
      const { w } = mountPanel({ items: [item("q1", "2026-01-01T00:00:10", { state: "resolved" }),
        item("q2", "2026-01-01T00:00:20", { state: "delivered" })] }, [], film, { turn: turn() });
      expect(w.findAll(".entry")[1].find('[data-testid="working-card"]').exists()).toBe(true);
    });

    it("is a standalone card when there is no item", () => {
      const { w } = mountPanel({}, [], film, { turn: turn() });
      expect(w.findAll('[data-testid="working-card"]')).toHaveLength(1);
      expect(w.find(".entry [data-testid=working-card]").exists()).toBe(false);
    });

    it("is absent with no turn and no plan", () => {
      expect(mountPanel().w.find('[data-testid="working-card"]').exists()).toBe(false);
    });
  });

  describe("look and feel hooks", () => {
    it("the status pill reads Connected / Not connected next to the title", () => {
      const on = mountPanel({ connected: true }).w.get('[data-testid="status-pill"]');
      expect(on.text()).toBe("connected");
      expect(on.classes()).toContain("ok");
      const off = mountPanel().w.get('[data-testid="status-pill"]');
      expect(off.text()).toBe("not connected");
      expect(off.classes()).not.toContain("ok");
    });

    it("your message is a bubble with its delivery state; Claude's reply is a separate neutral bubble", () => {
      const { w } = mountPanel({ connected: true, items: [item("q1", "2026-01-01T00:00:10", { state: "delivered" })],
        messages: [msg("m1", "2026-01-01T00:00:15", "q1")] });
      expect(w.get('[data-item="q1"]').classes()).toContain("item");
      expect(w.get('[data-item="q1"] .state').attributes("data-state")).toBe("delivered");
      expect(w.get('[data-message="m1"]').classes()).toContain("claude-msg");
    });

    it("attach is icon-only with an accessible name; send and attach frame keep their hooks", () => {
      const { w } = mountPanel();
      const attach = w.get('[data-action="attach"]');
      expect(attach.text()).toBe("");
      expect(attach.attributes("aria-label")).toBe("Attach file");
      expect(attach.find("svg").exists()).toBe(true);
      const labels = w.findAll(".composer .row button").map((b) => b.attributes("data-action"));
      expect(labels).toEqual(["attach", "attach-frame", "send"]);
      expect(w.get('[data-action="send"]').classes()).toContain("primary");
    });
  });
});

describe("ClaudePanel shapes", () => {
  it("attached frame carries the shape", async () => {
    const two = { ...film, aspect: "16:9", second_aspect: "9:16", width: 1280, height: 720 } as unknown as Film;
    const { w } = mountPanel({}, [], two);
    aspectViewState.value = "second";
    await w.get('[data-action="attach-frame"]').trigger("click");
    await w.get("textarea").setValue("look");
    await w.get("form").trigger("submit");
    await flushPromises();
    expect(api.postChat).toHaveBeenCalledWith("look", undefined,
      { time: 0, scene: "s1", sceneTitle: "Open the middle", aspect: "9:16" });
    aspectViewState.value = "main";
  });
});
