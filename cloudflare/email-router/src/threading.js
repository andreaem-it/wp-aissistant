export function normalizeMessageId(value = "") {
  return value.replace(/[\r\n]/g, " ").trim().slice(0, 500);
}

export function rootThreadId(messageId, inReplyTo = "", references = "") {
  const referenceIds = references.match(/<[^>]+>/g) || [];
  return normalizeMessageId(referenceIds[0] || inReplyTo || messageId);
}

export function shouldIgnore(headers, sender, supportAddress) {
  const autoSubmitted = (headers.get("auto-submitted") || "").toLowerCase();
  const precedence = (headers.get("precedence") || "").toLowerCase();
  return sender.trim().toLowerCase() === supportAddress.trim().toLowerCase()
    || (autoSubmitted && autoSubmitted !== "no") || ["bulk", "junk", "list"].includes(precedence);
}
