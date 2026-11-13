import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import type { ActivityTurn, PlanItem } from "../types";
import WorkingCard from "./WorkingCard.vue";

const step = (id: number, label: string, state: "running" | "done" | "failed") =>
  ({ id, label, state, started: "2026-01-01T00:00:00.000Z", ended: null });
const turn = (extra: Partial<ActivityTurn> = {}): ActivityTurn => ({
  id: "t1", started: "2026-01-01T00:00:00.000Z", updated: "", ended: null, item: null,
  steps: [step(1, "Reading scene 03", "done"), step(2, "Checking the film", "failed"), step(3, "Editing scene 03", "running")],
  ...extra });

describe("WorkingCard", () => {
  it("shows spinner, elapsed and steps with tick, cross and spinner while working", () => {
    const w = mount(WorkingCard, { props: { turn: turn(), plan: [] } });
    expect(w.find('[data-testid="spinner"]').exists()).toBe(true);
    expect(w.find('[data-testid="elapsed"]').exists()).toBe(true);
    const rows = w.findAll('[data-testid="step"]');
    expect(rows.map((r) => r.attributes("data-state"))).toEqual(["done", "failed", "running"]);
    expect(rows[0].text()).toContain("✓");
    expect(rows[1].text()).toContain("✗");
    expect(rows[0].text()).toContain("Reading scene 03");
  });

  it("collapses to one line when the turn ended, and expands on click", async () => {
    const ended = turn({ ended: "2026-01-01T00:01:12.000Z",
      steps: [1, 2, 3, 4, 5, 6].map((i) => step(i, `Step ${i}`, "done")) });
    const w = mount(WorkingCard, { props: { turn: ended, plan: [] } });
    expect(w.find('[data-testid="spinner"]').exists()).toBe(false);
    expect(w.get('[data-testid="summary"]').text()).toContain("Worked 1m 12s · 6 steps");
    expect(w.findAll('[data-testid="step"]')).toHaveLength(0);
    await w.get('[data-testid="summary"]').trigger("click");
    expect(w.findAll('[data-testid="step"]')).toHaveLength(6);
    await w.get('[data-testid="summary"]').trigger("click");
    expect(w.findAll('[data-testid="step"]')).toHaveLength(0);
  });

  it("shows the plan checklist at the top, ticked live", async () => {
    const plan: PlanItem[] = [{ text: "one", done: true }, { text: "two", done: false }];
    const w = mount(WorkingCard, { props: { turn: turn(), plan } });
    const items = w.findAll('[data-testid="plan-item"]');
    expect(items.map((i) => i.attributes("data-done"))).toEqual(["true", "false"]);
    expect(w.html().indexOf('data-testid="plan"')).toBeLessThan(w.html().indexOf('data-testid="step"'));
    await w.setProps({ plan: [{ text: "one", done: true }, { text: "two", done: true }] });
    expect(w.findAll('[data-testid="plan-item"]').map((i) => i.attributes("data-done"))).toEqual(["true", "true"]);
  });

  it("works with a plan and no turn", () => {
    const w = mount(WorkingCard, { props: { turn: null, plan: [{ text: "one", done: false }] } });
    expect(w.findAll('[data-testid="plan-item"]')).toHaveLength(1);
    expect(w.find('[data-testid="summary"]').exists()).toBe(false);
  });
});
