import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import type { Film, Proposal } from "../types";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, approve: vi.fn(async () => ({})), reject: vi.fn(async () => ({})) };
});
import * as api from "../api";
import ProposalCard from "./ProposalCard.vue";

const film = { scenes: [{ id: "s3", title: "Found it", length: 9, voice: { text: "", offset: 0.3 } }], texts: [] } as unknown as Film;

const base = { created: "", needs_approval: false, held: [], error: null, summary: "" };
const list: Proposal = { ...base, id: "p1", status: "awaiting_approval", needs_approval: true,
  summary: "Six scenes", changes: [
    { op: "add_scene", scene: { id: "a", title: "Open the middle", length: 5, voice: { text: "Start in the middle." } } },
    { op: "add_scene", scene: { id: "b", title: "Halve", length: 6.5, voice: { text: "Cut it in half." } } },
  ] };
const partial: Proposal = { ...base, id: "p2", status: "partial", held: [0],
  changes: [{ op: "set_scene", id: "s3", length: 4 }] };

beforeEach(() => vi.clearAllMocks());

describe("ProposalCard", () => {
  it("scene list OK approves without pinned", async () => {
    const w = mount(ProposalCard, { props: { proposal: list, film } });
    expect(w.text()).toContain("Open the middle");
    expect(w.text()).toContain("Start in the middle.");
    expect(w.text()).toContain("6.5s");
    await w.get('[data-action="approve"]').trigger("click");
    expect(api.approve).toHaveBeenCalledWith("p1", false);
  });

  it("scene list Reject rejects and Change… asks the panel to prefill", async () => {
    const w = mount(ProposalCard, { props: { proposal: list, film } });
    await w.get('[data-action="change"]').trigger("click");
    expect(w.emitted("change")).toHaveLength(1);
    await w.get('[data-action="reject"]').trigger("click");
    expect(api.reject).toHaveBeenCalledWith("p1");
  });

  it("partial card lists held changes in words and Apply approves with pinned", async () => {
    const w = mount(ProposalCard, { props: { proposal: partial, film } });
    expect(w.text()).toContain("Claude wants to change things you set:");
    expect(w.text()).toContain('scene "Found it" length 9.0s → 4.0s');
    await w.get('[data-action="apply"]').trigger("click");
    expect(api.approve).toHaveBeenCalledWith("p2", true);
  });

  it("a held change that brings back a removed scene says why", () => {
    const p: Proposal = { ...base, id: "p9", status: "partial", held: [0],
      held_reasons: { "0": "same title as a scene you removed" },
      changes: [{ op: "add_scene", scene: { id: "s9", title: "Middle", length: 5 } }] };
    const w = mount(ProposalCard, { props: { proposal: p, film } });
    expect(w.text()).toContain("(held: same title as a scene you removed)");
  });

  it("an approval card without add_scene changes still lists what it does", () => {
    const p: Proposal = { ...base, id: "p5", status: "awaiting_approval", needs_approval: true, changes: [
      { op: "set_scene", id: "s3", length: 4 },
      { op: "set_voice", id: "s3", text: "Fresh words." },
      { op: "add_text", text: { id: "t9", scene: "s3", text: "Caption", start: 1, end: 3 } },
      { op: "remove_scene", id: "s3" },
    ] };
    const w = mount(ProposalCard, { props: { proposal: p, film } });
    const items = w.findAll('[data-testid="other-changes"] li').map((li) => li.text());
    expect(items).toEqual([
      'scene "Found it" length 9.0s → 4.0s',
      'scene "Found it" line "Fresh words."',
      'text "Caption" is added to scene "Found it", 1.0s to 3.0s',
      'scene "Found it" is removed',
    ]);
  });

  it("describes sound and music changes", () => {
    const p: Proposal = { ...base, id: "p6", status: "awaiting_approval", needs_approval: true, changes: [
      { op: "add_sfx", sfx: { id: "fx1", scene: "s3", preset: "ding", at: 1.2 } },
      { op: "set_sfx", id: "fx3", volume: 0.3 },
      { op: "remove_sfx", id: "fx3" },
      { op: "set_music", bed: { mood: "calm", tempo: 80, key: "C", scale: "major", palette: "keys", seed: 1 }, volume: 0.5 },
      { op: "set_music", bed: null },
    ] };
    const w = mount(ProposalCard, { props: { proposal: p, film } });
    expect(w.findAll('[data-testid="other-changes"] li').map((li) => li.text())).toEqual([
      'Add sound "ding" to scene 01 at 1.2 s',
      "Change sound fx3",
      "Remove sound fx3",
      "Music: calm, 80 bpm, C major",
      "Remove music",
    ]);
  });

  it("a scene-list card does not repeat its add_scene rows as a list", () => {
    const w = mount(ProposalCard, { props: { proposal: list, film } });
    expect(w.find('[data-testid="other-changes"]').exists()).toBe(false);
  });

  it("Keep mine rejects", async () => {
    const w = mount(ProposalCard, { props: { proposal: partial, film } });
    await w.get('[data-action="keep"]').trigger("click");
    expect(api.reject).toHaveBeenCalledWith("p2");
  });

  it("invalid proposal shows its error; a failed approve shows the problem", async () => {
    const bad: Proposal = { ...base, id: "p3", status: "invalid", error: "scene x is unknown", changes: [] };
    expect(mount(ProposalCard, { props: { proposal: bad, film } }).get('[data-testid="proposal-error"]').text())
      .toBe("scene x is unknown");
    vi.mocked(api.approve).mockRejectedValueOnce(new Error("already applied"));
    const w = mount(ProposalCard, { props: { proposal: list, film } });
    await w.get('[data-action="approve"]').trigger("click");
    await flushPromises();
    expect(w.get('[role="alert"]').text()).toBe("already applied");
  });

  it("scene list buttons run primary, secondary, ghost: Build it, Change…, Reject", () => {
    const w = mount(ProposalCard, { props: { proposal: list, film } });
    const buttons = w.findAll(".buttons button");
    expect(buttons.map((b) => b.attributes("data-action"))).toEqual(["approve", "change", "reject"]);
    expect(buttons.map((b) => b.text())).toEqual(["Build it", "Change…", "Reject"]);
    expect(buttons[0].classes()).toContain("primary");
    expect(buttons[1].classes()).not.toContain("primary");
    expect(buttons[1].classes()).not.toContain("ghost");
    expect(buttons[2].classes()).toContain("ghost");
  });

  it("partial card has Apply as primary then Keep mine, and its own tint hook", () => {
    const w = mount(ProposalCard, { props: { proposal: partial, film } });
    const buttons = w.findAll(".buttons button");
    expect(buttons.map((b) => b.attributes("data-action"))).toEqual(["apply", "keep"]);
    expect(buttons[0].classes()).toContain("primary");
    expect(w.get(".card").attributes("data-status")).toBe("partial");
  });
});
