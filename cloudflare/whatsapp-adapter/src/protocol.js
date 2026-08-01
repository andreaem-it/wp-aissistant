const MEDIA_LABELS = {
  audio: "Messaggio audio",
  document: "Documento allegato",
  image: "Immagine allegata",
  sticker: "Sticker allegato",
  video: "Video allegato",
};

export function tenantConfig(raw, clientId) {
  const tenants = JSON.parse(raw || "{}");
  return tenants[String(clientId)] || null;
}

export function tenantFromPhone(raw, phoneNumberId) {
  const tenants = JSON.parse(raw || "{}");
  for (const [clientId, config] of Object.entries(tenants)) {
    if (String(config.phone_number_id) === String(phoneNumberId)) return { clientId: Number(clientId), ...config };
  }
  return null;
}

export function inboundText(message) {
  if (message.type === "text") return (message.text?.body || "").trim();
  if (message.type === "button") return (message.button?.text || message.button?.payload || "").trim();
  if (message.type === "interactive") {
    const reply = message.interactive?.button_reply || message.interactive?.list_reply;
    return (reply?.title || reply?.id || "").trim();
  }
  const media = message[message.type];
  if (MEDIA_LABELS[message.type] && media?.id) {
    const caption = (media.caption || media.filename || "").trim();
    return caption ? `[${MEDIA_LABELS[message.type]}: ${caption}]` : `[${MEDIA_LABELS[message.type]}]`;
  }
  return "";
}

export function graphPayload(payload) {
  if (payload.type === "text") {
    return {
      messaging_product: "whatsapp",
      recipient_type: "individual",
      to: payload.to,
      type: "text",
      text: { preview_url: false, body: payload.text },
      ...(payload.reply_to_message_id ? { context: { message_id: payload.reply_to_message_id } } : {}),
    };
  }
  if (payload.type === "template") {
    const parameters = (payload.parameters || []).map((text) => ({ type: "text", text }));
    return {
      messaging_product: "whatsapp",
      to: payload.to,
      type: "template",
      template: {
        name: payload.template,
        language: { code: payload.language },
        ...(parameters.length ? { components: [{ type: "body", parameters }] } : {}),
      },
    };
  }
  throw new Error("Unsupported outbound type");
}
