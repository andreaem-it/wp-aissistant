import { describe, expect, it } from "vitest";

import { actionLabel, actorLabel, formatMoment } from "./activity";

describe("actionLabel", () => {
  it("translates the known actions", () => {
    expect(actionLabel("conversation.reply")).toBe("Risposta operatore");
    expect(actionLabel("note.create")).toBe("Nota interna aggiunta");
    expect(actionLabel("sla.breach")).toBe("SLA violato");
  });

  it("falls back to the raw action", () => {
    expect(actionLabel("qualcosa.di.nuovo")).toBe("qualcosa.di.nuovo");
  });
});

describe("actorLabel", () => {
  it("names the system for automated entries", () => {
    expect(actorLabel({ actor_type: "system", actor: "sla-monitor" })).toBe("Sistema");
    expect(actorLabel({ actor_type: "operator", actor: "op@acme.it" })).toBe("op@acme.it");
    expect(actorLabel(null)).toBe("");
  });
});

describe("formatMoment", () => {
  it("ignores empty or invalid values", () => {
    expect(formatMoment(null)).toBe("");
    expect(formatMoment("non-una-data")).toBe("");
  });

  it("formats a valid timestamp", () => {
    expect(formatMoment("2026-07-31T12:05:00Z")).toMatch(/31\/07/);
  });
});
