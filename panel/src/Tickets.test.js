import { describe, expect, it } from "vitest";
import { filterTickets } from "./ticketFilters.js";

const items = [
  { ticket: { id: 42, reason: "Richiesta rimborso" }, conversation: { visitor_email: "mario@example.it" } },
  { ticket: { id: 51, reason: "Informazioni spedizione" }, conversation: { visitor_email: "anna@example.it" } },
];

describe("filterTickets", () => {
  it("cerca per numero, motivo ed email senza distinguere maiuscole", () => {
    expect(filterTickets(items, "42")).toEqual([items[0]]);
    expect(filterTickets(items, "RIMBORSO")).toEqual([items[0]]);
    expect(filterTickets(items, "anna@EXAMPLE.it")).toEqual([items[1]]);
  });

  it("mantiene l'elenco completo quando la ricerca è vuota", () => {
    expect(filterTickets(items, "   ")).toBe(items);
  });
});
