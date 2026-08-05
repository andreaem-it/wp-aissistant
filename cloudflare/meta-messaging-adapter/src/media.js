/**
 * Download degli allegati Messenger/Instagram.
 *
 * A differenza di WhatsApp qui l'URL è già firmato dal CDN Meta e non richiede il token: lo
 * scarichiamo **senza** Authorization, così il segreto del tenant non può uscire nemmeno per
 * errore. L'host viene comunque validato: un URL fuori dal CDN Meta non viene chiamato.
 */

// Sottoinsieme della whitelist del backend: ciò che non passa qui non arriva a farsi rifiutare.
export const ALLOWED_TYPES = new Set([
  "image/jpeg", "image/png", "image/webp", "application/pdf",
  "text/plain", "audio/mpeg", "audio/ogg", "video/mp4",
]);
export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 10 * 1024 * 1024;

const ALLOWED_HOSTS = [".fbcdn.net", ".facebook.com", ".fbsbx.com", ".cdninstagram.com"];
const EXTENSIONS = {
  "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf",
  "text/plain": ".txt", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "video/mp4": ".mp4",
};

export function isMetaMediaUrl(value) {
  let url;
  try {
    url = new URL(String(value || ""));
  } catch {
    return false;
  }
  if (url.protocol !== "https:") return false;
  const host = url.hostname.toLowerCase();
  return ALLOWED_HOSTS.some((suffix) => host === suffix.slice(1) || host.endsWith(suffix));
}

export function toBase64(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

export function mediaFilename(attachment, contentType, index) {
  const fromUrl = (() => {
    try {
      const name = new URL(attachment.url).pathname.split("/").pop() || "";
      return /\.[a-z0-9]{2,5}$/i.test(name) ? name : "";
    } catch {
      return "";
    }
  })();
  if (fromUrl) return fromUrl.slice(0, 180);
  return `${attachment.type || "allegato"}-${index + 1}${EXTENSIONS[contentType] || ""}`;
}

/** Scarica un allegato. `null` quando non è utilizzabile: il messaggio deve arrivare comunque. */
export async function fetchAttachment(attachment, index, { fetchImpl = fetch } = {}) {
  if (!isMetaMediaUrl(attachment?.url)) return null;
  const response = await fetchImpl(attachment.url);
  if (!response.ok) return null;
  const contentType = String(response.headers.get("content-type") || "").toLowerCase().split(";", 1)[0].trim();
  if (!ALLOWED_TYPES.has(contentType)) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_FILE_BYTES) return null;
  return { filename: mediaFilename(attachment, contentType, index), content_type: contentType, data: toBase64(bytes) };
}

/**
 * Prepara gli allegati di un messaggio troncando ai limiti del backend: un payload fuori
 * limite verrebbe rifiutato per intero, e il messaggio del cliente andrebbe perso.
 */
export async function collectAttachments(attachments, options = {}) {
  const collected = [];
  let skipped = 0;
  let total = 0;
  for (const [index, attachment] of (attachments || []).entries()) {
    if (collected.length >= MAX_FILES) {
      skipped += 1;
      continue;
    }
    let media = null;
    try {
      media = await fetchAttachment(attachment, index, options);
    } catch {
      media = null;
    }
    if (!media) {
      skipped += 1;
      continue;
    }
    const size = Math.ceil((media.data.length * 3) / 4);
    if (total + size > MAX_TOTAL_BYTES) {
      skipped += 1;
      continue;
    }
    total += size;
    collected.push(media);
  }
  return { attachments: collected, skipped };
}

export function skippedNote(skipped) {
  if (!skipped) return "";
  return skipped === 1 ? "[1 allegato non inoltrato]" : `[${skipped} allegati non inoltrati]`;
}
