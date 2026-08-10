export function filterTickets(items, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return items;
  return items.filter(({ ticket, conversation }) =>
    String(ticket.id).includes(normalized) ||
    ticket.reason?.toLowerCase().includes(normalized) ||
    conversation.visitor_email?.toLowerCase().includes(normalized));
}
