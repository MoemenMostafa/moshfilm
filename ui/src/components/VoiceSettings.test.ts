import { beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";
import type { Film } from "../types";
import { FilmKey, type FilmStore } from "../composables/useFilm";

vi.mock("../api", async (orig) => {
  const real = await orig<typeof import("../api")>();
  return { ...real, synthesizeVoice: vi.fn(async () => ({ started: true, running: true })) };
});
import * as api from "../api";
import VoiceSettings from "./VoiceSettings.vue";

const film = { voice: { name: "en-US-AndrewNeural", rate: "+8%" } } as unknown as Film;

function mountIt() {
  const edit = vi.fn(async () => {});
  const voiceStatus = ref<{ text: string; error: boolean; busy: boolean } | null>(null);
  const store = { film: ref(film), edit, voiceStatus } as unknown as FilmStore;
  const w = mount(VoiceSettings, { global: { provide: { [FilmKey as symbol]: store } } });
  return { w, edit, voiceStatus };
}

describe("VoiceSettings", () => {
  beforeEach(() => vi.mocked(api.synthesizeVoice).mockClear());

  it("offers the six voices and five rates, current ones selected", () => {
    const { w } = mountIt();
    const voices = w.findAll("[data-voice-name] option").map((o) => o.attributes("value"));
    expect(voices).toEqual(["en-US-AndrewNeural", "en-US-AriaNeural", "en-US-GuyNeural", "en-US-JennyNeural",
      "en-GB-RyanNeural", "en-GB-SoniaNeural"]);
    expect(w.findAll("[data-voice-rate] option").map((o) => o.attributes("value")))
      .toEqual(["-10%", "+0%", "+8%", "+15%", "+20%"]);
    expect((w.get("[data-voice-rate]").element as HTMLSelectElement).value).toBe("+8%");
  });

  it("changing rate sends set_voice_settings", async () => {
    const { w, edit } = mountIt();
    await w.get("[data-voice-rate]").setValue("+15%");
    expect(edit).toHaveBeenCalledWith([{ op: "set_voice_settings", name: "en-US-AndrewNeural", rate: "+15%" }]);
  });

  it("changing voice keeps the rate", async () => {
    const { w, edit } = mountIt();
    await w.get("[data-voice-name]").setValue("en-GB-SoniaNeural");
    expect(edit).toHaveBeenCalledWith([{ op: "set_voice_settings", name: "en-GB-SoniaNeural", rate: "+8%" }]);
  });

  it("Make voice calls synthesize and shows progress and errors verbatim", async () => {
    const { w, voiceStatus } = mountIt();
    await w.get("[data-make-voice]").trigger("click");
    expect(api.synthesizeVoice).toHaveBeenCalledTimes(1);
    voiceStatus.value = { text: "voice 1/3: s1", error: false, busy: true };
    await flushPromises();
    expect(w.get("[data-voice-status]").text()).toBe("voice 1/3: s1");
    voiceStatus.value = { text: "No audio was received", error: true, busy: false };
    await flushPromises();
    expect(w.get("[data-voice-status]").text()).toBe("No audio was received");
    expect(w.get("[data-voice-status]").classes()).toContain("error");
    voiceStatus.value = { text: "Voice ready", error: false, busy: false };
    await flushPromises();
    expect(w.get("[data-voice-status]").text()).toBe("Voice ready");
  });

  it("shows a failed request's message", async () => {
    vi.mocked(api.synthesizeVoice).mockRejectedValueOnce(new Error("boom"));
    const { w } = mountIt();
    await w.get("[data-make-voice]").trigger("click");
    await flushPromises();
    expect(w.get("[data-voice-status]").text()).toBe("boom");
  });
});
