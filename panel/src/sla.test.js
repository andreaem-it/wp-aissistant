import { describe, expect, it } from "vitest";

import { describeSla, describeTarget, formatDuration } from "./sla";

const NOW = Date.parse("2026-07-31T10:00:00Z");

describe("formatDuration", () => {
  it("uses minutes, hours and days", () => {
    expect(formatDuration(12)).toBe("12 min");
    expect(formatDuration(90)).toBe("1 h 30 min");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(1500)).toBe("1 g 1 h");
  });

  it("never renders a negative duration", () => {
    expect(formatDuration(-5)).toBe("0 min");
  });
});

describe("describeTarget", () => {
  it("counts down to a pending deadline", () => {
    const target = { due_at: "2026-07-31T10:30:00Z", met_at: null };
    expect(describeTarget("Prima risposta", target, NOW)).toBe("Prima risposta: entro 30 min");
  });

  it("reports how long a missed deadline is overdue", () => {
    const target = { due_at: "2026-07-31T09:00:00Z", met_at: null };
    expect(describeTarget("Prima risposta", target, NOW)).toBe("Prima risposta: scaduta da 1 h");
  });

  it("marks a target met in time and one met late", () => {
    expect(
      describeTarget("Risoluzione", { due_at: "2026-07-31T10:30:00Z", met_at: "2026-07-31T10:10:00Z" }, NOW),
    ).toBe("Risoluzione: nei tempi");
    expect(
      describeTarget("Risoluzione", { due_at: "2026-07-31T09:00:00Z", met_at: "2026-07-31T09:45:00Z" }, NOW),
    ).toBe("Risoluzione: in ritardo di 45 min");
  });

  it("ignores a target without a deadline", () => {
    expect(describeTarget("Prima risposta", { due_at: null, met_at: null }, NOW)).toBeNull();
    expect(describeTarget("Prima risposta", null, NOW)).toBeNull();
  });
});

describe("describeSla", () => {
  it("returns nothing when the conversation has no SLA", () => {
    expect(describeSla(null)).toEqual([]);
  });

  it("describes both targets", () => {
    const sla = {
      state: "in_scadenza",
      first_response: { due_at: "2026-07-31T10:15:00Z", met_at: null },
      resolution: { due_at: "2026-07-31T14:00:00Z", met_at: null },
    };
    expect(describeSla(sla, NOW)).toEqual([
      "Prima risposta: entro 15 min",
      "Risoluzione: entro 4 h",
    ]);
  });
});
