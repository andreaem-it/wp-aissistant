/**
 * Allegati MIME nel formato `attachments` del backend.
 *
 * I limiti replicano quelli del backend perché un payload fuori limite verrebbe rifiutato
 * **per intero**: meglio inoltrare quello che sta nei limiti e dichiarare cosa è rimasto fuori
 * che perdere l'email del cliente.
 */

export const ALLOWED_TYPES = new Set([
  "image/jpeg", "image/png", "image/webp", "application/pdf",
  "text/plain", "audio/mpeg", "audio/ogg", "video/mp4",
]);
export const MAX_FILES = 5;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 10 * 1024 * 1024;
// Loghi di firma e pixel di tracciamento sono inline e minuscoli: occuperebbero gli slot
// buoni senza dire niente all'operatore, quindi li scartiamo senza segnalarli.
export const MIN_INLINE_BYTES = 8 * 1024;

const EXTENSIONS = {
  "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf",
  "text/plain": ".txt", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "video/mp4": ".mp4",
};

export function toBase64(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}

function bytesOf(content) {
  if (content instanceof Uint8Array) return content;
  if (content instanceof ArrayBuffer) return new Uint8Array(content);
  if (ArrayBuffer.isView(content)) return new Uint8Array(content.buffer, content.byteOffset, content.byteLength);
  return null;
}

/** Restituisce gli allegati da inoltrare e quanti ne sono stati lasciati indietro. */
export function collectAttachments(parsed) {
  const attachments = [];
  let skipped = 0;
  let total = 0;
  for (const [index, item] of (parsed?.attachments || []).entries()) {
    const contentType = String(item?.mimeType || "").toLowerCase().split(";", 1)[0].trim();
    const bytes = bytesOf(item?.content);
    const decorative = item?.disposition === "inline" && bytes && bytes.length < MIN_INLINE_BYTES;
    if (decorative) continue;
    if (!bytes || !bytes.length || !ALLOWED_TYPES.has(contentType) || bytes.length > MAX_FILE_BYTES) {
      skipped += 1;
      continue;
    }
    if (attachments.length >= MAX_FILES || total + bytes.length > MAX_TOTAL_BYTES) {
      skipped += 1;
      continue;
    }
    total += bytes.length;
    attachments.push({
      filename: String(item.filename || "").trim().slice(0, 180) || `allegato-${index + 1}${EXTENSIONS[contentType] || ""}`,
      content_type: contentType,
      data: toBase64(bytes),
    });
  }
  return { attachments, skipped };
}

/** Nota da aggiungere al corpo quando qualcosa non è stato inoltrato. */
export function skippedNote(skipped) {
  if (!skipped) return "";
  return skipped === 1 ? "[1 allegato non inoltrato]" : `[${skipped} allegati non inoltrati]`;
}
