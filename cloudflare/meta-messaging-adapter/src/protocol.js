/**
 * Mappatura tenant e normalizzazione degli eventi Messenger/Instagram.
 *
 * `META_TENANTS_JSON` è un segreto del Worker: le credenziali Meta non entrano mai nel
 * database applicativo. Forma attesa:
 *
 * {
 *   "4": {
 *     "page_id": "1234",          // pagina Facebook
 *     "instagram_id": "5678",     // account Instagram professionale
 *     "access_token": "…",        // page access token
 *     "channel_api_key": "…"      // chiave backend con scope channels:write
 *   }
 * }
 */

const OBJECT_PLATFORM = { page: "messenger", instagram: "instagram" };
// Solo gli allegati che sono davvero contenuto del cliente: `fallback` è l'anteprima di un
// link e `template` è una card, non un file da archiviare.
const MEDIA_ATTACHMENTS = new Set(["image", "video", "audio", "file"]);

export function platformOf(object) {
  return OBJECT_PLATFORM[String(object || "").toLowerCase()] || "";
}

export function tenantConfig(raw, clientId) {
  const tenants = JSON.parse(raw || "{}");
  return tenants[String(clientId)] || null;
}

/** Trova il tenant dall'id dell'entry: pagina per Messenger, account per Instagram. */
export function tenantFromEntry(raw, entryId, platform) {
  const tenants = JSON.parse(raw || "{}");
  const field = platform === "instagram" ? "instagram_id" : "page_id";
  for (const [clientId, config] of Object.entries(tenants)) {
    if (config?.[field] && String(config[field]) === String(entryId)) {
      return { clientId: Number(clientId), ...config };
    }
  }
  return null;
}

/** L'id della risorsa Graph su cui si invia: la pagina o l'account Instagram. */
export function sendingId(tenant, platform) {
  return String((platform === "instagram" ? tenant?.instagram_id : tenant?.page_id) || "");
}

/**
 * Riduce un evento del webhook alla forma che serve al backend.
 * Restituisce `null` per tutto ciò che non è un messaggio del cliente.
 */
export function normalizeEvent(event) {
  const senderId = String(event?.sender?.id || "");
  if (!senderId) return null;

  // Gli echo sono i nostri stessi invii che tornano indietro: inoltrarli creerebbe
  // messaggi duplicati attribuiti al cliente.
  if (event?.message?.is_echo) return null;

  if (event?.message) {
    const messageId = String(event.message.mid || "");
    if (!messageId) return null;
    const attachments = (event.message.attachments || [])
      .filter((item) => MEDIA_ATTACHMENTS.has(String(item?.type || "")) && item?.payload?.url)
      .map((item) => ({ type: String(item.type), url: String(item.payload.url) }));
    return { senderId, messageId, text: String(event.message.text || "").trim(), attachments };
  }

  if (event?.postback) {
    const label = String(event.postback.title || event.postback.payload || "").trim();
    if (!label) return null;
    // il postback non ha sempre un mid: l'id deve comunque restare stabile fra i retry
    const messageId = String(event.postback.mid || `postback:${senderId}:${event.timestamp || ""}`);
    return { senderId, messageId, text: label, attachments: [] };
  }

  return null; // consegne, letture, reazioni: nessun contenuto da archiviare
}

/**
 * Payload della Send API. `reply_to` non viene usato: Messenger non lo supporta e un campo
 * rifiutato dal provider trasformerebbe una risposta dell'operatore in una mancata consegna.
 */
export function graphPayload({ recipient_id: recipientId, text }) {
  if (!recipientId || !String(text || "").trim()) throw new Error("Missing recipient or text");
  return {
    recipient: { id: String(recipientId) },
    messaging_type: "RESPONSE",
    message: { text: String(text) },
  };
}
