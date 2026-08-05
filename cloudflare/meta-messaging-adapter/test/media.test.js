import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_FILE_BYTES, collectAttachments, fetchAttachment, isMetaMediaUrl, mediaFilename, skippedNote, toBase64,
} from "../src/media.js";

function cdn({ type = "image/jpeg", bytes = new Uint8Array([1, 2, 3]), status = 200 } = {}) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url: String(url), auth: init?.headers?.Authorization });
    return new Response(bytes, { status, headers: { "Content-Type": type } });
  };
  return { calls, fetchImpl };
}

const IMAGE = { type: "image", url: "https://scontent.xx.fbcdn.net/v/foto.jpg" };

test("accetta solo URL del CDN Meta in HTTPS", () => {
  assert.equal(isMetaMediaUrl("https://scontent.xx.fbcdn.net/v/foto.jpg"), true);
  assert.equal(isMetaMediaUrl("https://lookaside.fbsbx.com/file"), true);
  assert.equal(isMetaMediaUrl("https://scontent.cdninstagram.com/foto.jpg"), true);
  assert.equal(isMetaMediaUrl("http://scontent.xx.fbcdn.net/v/foto.jpg"), false);
  assert.equal(isMetaMediaUrl("https://attacker.example/foto.jpg"), false);
  assert.equal(isMetaMediaUrl("https://fbcdn.net.attacker.example/foto.jpg"), false);
});

test("scarica l'allegato senza mai allegare il token del tenant", async () => {
  const { calls, fetchImpl } = cdn();
  const media = await fetchAttachment(IMAGE, 0, { fetchImpl });
  assert.deepEqual(media, {
    filename: "foto.jpg", content_type: "image/jpeg", data: toBase64(new Uint8Array([1, 2, 3])),
  });
  // l'URL è già firmato dal CDN: mandare il token sarebbe un rischio senza alcun beneficio
  assert.deepEqual(calls.map((call) => call.auth), [undefined]);
});

test("un URL fuori dal CDN Meta non viene nemmeno chiamato", async () => {
  const { calls, fetchImpl } = cdn();
  assert.equal(await fetchAttachment({ type: "image", url: "https://attacker.example/x.jpg" }, 0, { fetchImpl }), null);
  assert.deepEqual(calls, []);
});

test("scarta i formati che il backend rifiuterebbe", async () => {
  const svg = cdn({ type: "image/svg+xml" });
  assert.equal(await fetchAttachment(IMAGE, 0, { fetchImpl: svg.fetchImpl }), null);
  const huge = cdn({ bytes: new Uint8Array(MAX_FILE_BYTES + 1) });
  assert.equal(await fetchAttachment(IMAGE, 0, { fetchImpl: huge.fetchImpl }), null);
  const missing = cdn({ status: 404 });
  assert.equal(await fetchAttachment(IMAGE, 0, { fetchImpl: missing.fetchImpl }), null);
  const empty = cdn({ bytes: new Uint8Array(0) });
  assert.equal(await fetchAttachment(IMAGE, 0, { fetchImpl: empty.fetchImpl }), null);
});

test("deriva il nome dal path e ricade su un nome generato", () => {
  assert.equal(mediaFilename(IMAGE, "image/jpeg", 0), "foto.jpg");
  assert.equal(mediaFilename({ type: "audio", url: "https://scontent.xx.fbcdn.net/v/stream" }, "audio/mpeg", 2), "audio-3.mp3");
  assert.equal(mediaFilename({ type: "file", url: "non-una-url" }, "application/pdf", 0), "file-1.pdf");
});

test("tronca ai limiti del backend e dichiara cosa non passa", async () => {
  const { fetchImpl } = cdn();
  const many = Array.from({ length: 7 }, () => IMAGE);
  const result = await collectAttachments(many, { fetchImpl });
  assert.equal(result.attachments.length, 5);
  assert.equal(result.skipped, 2);
  assert.equal(skippedNote(result.skipped), "[2 allegati non inoltrati]");
  assert.equal(skippedNote(1), "[1 allegato non inoltrato]");
  assert.equal(skippedNote(0), "");
});

test("una rete che cade non fa perdere il messaggio", async () => {
  const failing = async () => {
    throw new Error("network down");
  };
  assert.deepEqual(await collectAttachments([IMAGE], { fetchImpl: failing }), { attachments: [], skipped: 1 });
  assert.deepEqual(await collectAttachments([], {}), { attachments: [], skipped: 0 });
});
