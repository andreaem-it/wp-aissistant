import { describe, expect, it } from "vitest";

import {
  EMPTY_FILTERS,
  fromApiFilters,
  hasActiveFilters,
  matchesView,
  toApiFilters,
  toQueryParams,
} from "./inboxFilters";

describe("toApiFilters", () => {
  it("omits the empty selections", () => {
    expect(toApiFilters(EMPTY_FILTERS)).toEqual({});
  });

  it("maps the assignment select onto the two backend filters", () => {
    expect(toApiFilters({ ...EMPTY_FILTERS, assignment: "unassigned" })).toEqual({ unassigned: true });
    expect(toApiFilters({ ...EMPTY_FILTERS, assignment: "7" })).toEqual({ assigned_operator_id: 7 });
  });

  it("sends numeric ids and keeps the enum values", () => {
    expect(
      toApiFilters({ ...EMPTY_FILTERS, status: "escalated", priority: "urgent", department_id: "3", sla_state: "violato" }),
    ).toEqual({ status: "escalated", priority: "urgent", department_id: 3, sla_state: "violato" });
  });

  it("carries the conversation language", () => {
    expect(toApiFilters({ ...EMPTY_FILTERS, conversation_language: "en" })).toEqual({
      conversation_language: "en",
    });
  });

  it("carries tag and classification filters", () => {
    expect(toApiFilters({ ...EMPTY_FILTERS, tag_id: "5", intent: "reso", urgency: "alta" })).toEqual({
      tag_id: 5,
      intent: "reso",
      urgency: "alta",
    });
  });
});

describe("toQueryParams", () => {
  it("always carries an ordering", () => {
    expect(toQueryParams(EMPTY_FILTERS)).toEqual({ sort: "recent" });
    expect(toQueryParams({ ...EMPTY_FILTERS, sort: "sla" })).toEqual({ sort: "sla" });
  });
});

describe("fromApiFilters", () => {
  it("rebuilds the select state of a saved view", () => {
    expect(fromApiFilters({ status: "open", assigned_operator_id: 4, department_id: 2 }, "priority")).toEqual({
      status: "open",
      priority: "",
      assignment: "4",
      department_id: "2",
      sla_state: "",
      tag_id: "",
      intent: "",
      urgency: "",
      conversation_language: "",
      sort: "priority",
    });
  });

  it("falls back to the empty state", () => {
    expect(fromApiFilters(null, null)).toEqual(EMPTY_FILTERS);
    expect(fromApiFilters({ unassigned: true }, "recent").assignment).toBe("unassigned");
  });
});

describe("hasActiveFilters / matchesView", () => {
  it("detects whether anything is filtered", () => {
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_FILTERS, status: "open" })).toBe(true);
  });

  it("recognises the view currently applied", () => {
    const view = { filters: { status: "open" }, sort: "recent" };
    expect(matchesView({ ...EMPTY_FILTERS, status: "open" }, view)).toBe(true);
    expect(matchesView({ ...EMPTY_FILTERS, status: "closed" }, view)).toBe(false);
    expect(matchesView({ ...EMPTY_FILTERS, status: "open", sort: "sla" }, view)).toBe(false);
    expect(matchesView(EMPTY_FILTERS, null)).toBe(false);
  });
});
