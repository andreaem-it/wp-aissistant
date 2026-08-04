import PostalMime from "postal-mime";
import { normalizeMessageId, rootThreadId, shouldIgnore } from "./threading.js";
import { collectAttachments, skippedNote } from "./attachments.js";

const MAX_RAW_BYTES = 10 * 1024 * 1024;

export default {
  async email(message, env) {
    if (shouldIgnore(message.headers, message.from, env.SUPPORT_ADDRESS)) return;
    const contentLength = Number(message.headers.get("content-length") || 0);
    if (contentLength > MAX_RAW_BYTES) return message.setReject("552 Email troppo grande");
    const raw = await new Response(message.raw).arrayBuffer();
    if (raw.byteLength > MAX_RAW_BYTES) return message.setReject("552 Email troppo grande");
    const parsed = await PostalMime.parse(raw);
    const messageId = normalizeMessageId(message.headers.get("message-id") || parsed.messageId || "");
    if (!messageId) return message.setReject("550 Message-ID mancante");
    const { attachments, skipped } = collectAttachments(parsed);
    // un'email con la sola foto del prodotto difettoso è legittima: si rifiuta solo il vuoto
    const text = [(parsed.text || "").trim(), skippedNote(skipped)].filter(Boolean).join("\n");
    if (!text && !attachments.length) return message.setReject("550 Corpo testuale mancante");
    const inReplyTo = normalizeMessageId(message.headers.get("in-reply-to") || parsed.inReplyTo || "");
    const references = message.headers.get("references") || "";
    const response = await fetch(`${env.BACKEND_URL.replace(/\/$/, "")}/channels/email/inbound`, {
      method: "POST",
      headers: {Authorization: `Bearer ${env.CHANNEL_API_KEY}`, "Content-Type": "application/json"},
      body: JSON.stringify({from_email:message.from,from_name:parsed.from?.name||"",subject:parsed.subject||"",text,message_id:messageId,thread_id:rootThreadId(messageId,inReplyTo,references),in_reply_to:inReplyTo,...(attachments.length?{attachments}:{})}),
    });
    if (!response.ok) throw new Error(`Backend email adapter ${response.status}: ${(await response.text()).slice(0, 300)}`);
  },
};
