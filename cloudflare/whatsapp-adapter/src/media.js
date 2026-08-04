/**
 * Download dei media WhatsApp e conversione nel formato `attachments` del backend.
 *
 * Il token del tenant è un segreto: viene inviato solo all'host Graph e agli host CDN di Meta,
 * mai a un dominio che arrivasse dalla risposta dell'API senza controllo.
 */

// Deve restare un sottoinsieme della whitelist del backend: quello che non passa qui non
// arriva nemmeno a farsi rifiutare.
export const ALLOWED_TYPES = new Set([
  "image/jpeg", "image/png", "image/webp", "application/pdf",
  "text/plain", "audio/mpeg", "audio/ogg", "video/mp4",
]);
export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 10 * 1024 * 1024;

const MEDIA_TYPES = new Set(["audio", "document", "image", "sticker", "video"]);
const ALLOWED_HOSTS = [".fbcdn.net", ".facebook.com", ".fbsbx.com", ".whatsapp.net"];

/** Il download URL arriva dall'API: prima di allegarci il token verifichiamo dove punta. */
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

export function mediaDescriptor(message) {
  if (!MEDIA_TYPES.has(message?.type)) return null;
  const media = message[message.type];
  if (!media?.id) return null;
  return {
    id: String(media.id),
    filename: String(media.filename || "").trim(),
    caption: String(media.caption || "").trim(),
    kind: message.type,
  };
}

const EXTENSIONS = {
  "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf",
  "text/plain": ".txt", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "video/mp4": ".mp4",
};

export function mediaFilename(descriptor, contentType) {
  if (descriptor.filename) return descriptor.filename.slice(0, 180);
  return `${descriptor.kind}-${descriptor.id}`.slice(0, 170) + (EXTENSIONS[contentType] || "");
}

export function toBase64(bytes) {
  let binary = "";
  // btoa vuole una stringa: la costruiamo a blocchi per non superare il limite di argomenti
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

/**
 * Scarica un media risolvendo prima i metadati, poi i byte.
 * Restituisce `null` quando il media non è utilizzabile: il messaggio deve comunque arrivare.
 */
export async function fetchMedia(descriptor, { token, graphVersion, fetchImpl = fetch }) {
  const metaResponse = await fetchImpl(
    `https://graph.facebook.com/${graphVersion}/${encodeURIComponent(descriptor.id)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!metaResponse.ok) return null;
  const info = await metaResponse.json();
  const contentType = String(info?.mime_type || "").toLowerCase().split(";", 1)[0].trim();
  if (!ALLOWED_TYPES.has(contentType)) return null;
  if (Number(info?.file_size || 0) > MAX_FILE_BYTES) return null;
  if (!isMetaMediaUrl(info?.url)) return null;

  const fileResponse = await fetchImpl(info.url, { headers: { Authorization: `Bearer ${token}` } });
  if (!fileResponse.ok) return null;
  const bytes = new Uint8Array(await fileResponse.arrayBuffer());
  if (!bytes.length || bytes.length > MAX_FILE_BYTES) return null;
  return { filename: mediaFilename(descriptor, contentType), content_type: contentType, data: toBase64(bytes) };
}

/**
 * Prepara gli allegati di un messaggio WhatsApp.
 * `skipped` conta i media persi: l'operatore deve sapere che qualcosa non è arrivato.
 */
export async function collectAttachments(messages, options) {
  const attachments = [];
  let skipped = 0;
  let total = 0;
  for (const descriptor of messages) {
    if (attachments.length >= MAX_FILES) {
      skipped += 1;
      continue;
    }
    let media = null;
    try {
      media = await fetchMedia(descriptor, options);
    } catch {
      media = null;
    }
    if (!media) {
      skipped += 1;
      continue;
    }
    // la lunghezza base64 sovrastima i byte del 33%: bastano per stare sotto il limite del backend
    total += Math.ceil((media.data.length * 3) / 4);
    if (total > MAX_TOTAL_BYTES) {
      skipped += 1;
      total -= Math.ceil((media.data.length * 3) / 4);
      continue;
    }
    attachments.push(media);
  }
  return { attachments, skipped };
}
