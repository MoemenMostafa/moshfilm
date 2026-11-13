import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";
import InlineEdit from "./InlineEdit.vue";

function mountIt(value = "old words") {
  return mount(InlineEdit, { props: { value }, attachTo: document.body });
}

describe("InlineEdit", () => {
  it("starts focused with the current text", () => {
    const w = mountIt();
    const input = w.get("[data-inline-edit]").element as HTMLInputElement;
    expect(input.value).toBe("old words");
    expect(document.activeElement).toBe(input);
    w.unmount();
  });

  it("Enter saves the new text", async () => {
    const w = mountIt();
    await w.get("[data-inline-edit]").setValue("new words");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Enter" });
    expect(w.emitted("save")).toEqual([["new words"]]);
    expect(w.emitted("cancel")).toBeUndefined();
    w.unmount();
  });

  it("blur saves too, but only once", async () => {
    const w = mountIt();
    await w.get("[data-inline-edit]").setValue("typed");
    await w.get("[data-inline-edit]").trigger("blur");
    await w.get("[data-inline-edit]").trigger("blur");
    expect(w.emitted("save")).toEqual([["typed"]]);
    w.unmount();
  });

  it("Enter then the blur that follows it saves once", async () => {
    const w = mountIt();
    await w.get("[data-inline-edit]").setValue("typed");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Enter" });
    await w.get("[data-inline-edit]").trigger("blur");
    expect(w.emitted("save")).toHaveLength(1);
    w.unmount();
  });

  it("Esc cancels, and the blur after it does not save", async () => {
    const w = mountIt();
    await w.get("[data-inline-edit]").setValue("typed but dropped");
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Escape" });
    await w.get("[data-inline-edit]").trigger("blur");
    expect(w.emitted("cancel")).toHaveLength(1);
    expect(w.emitted("save")).toBeUndefined();
    w.unmount();
  });

  it("unchanged or empty text is a cancel, not a save", async () => {
    const a = mountIt();
    await a.get("[data-inline-edit]").trigger("keydown", { key: "Enter" });
    expect(a.emitted("save")).toBeUndefined();
    expect(a.emitted("cancel")).toHaveLength(1);
    const b = mountIt();
    await b.get("[data-inline-edit]").setValue("   ");
    await b.get("[data-inline-edit]").trigger("blur");
    expect(b.emitted("save")).toBeUndefined();
    expect(b.emitted("cancel")).toHaveLength(1);
    a.unmount();
    b.unmount();
  });

  it("keys typed in the box do not leak to the timeline shortcuts", async () => {
    const w = mountIt();
    const seen: string[] = [];
    const spy = (e: Event) => seen.push((e as KeyboardEvent).key);
    document.body.addEventListener("keydown", spy);
    await w.get("[data-inline-edit]").trigger("keydown", { key: "Backspace" });
    document.body.removeEventListener("keydown", spy);
    expect(seen).toEqual([]);
    w.unmount();
  });
});
