import test from "node:test";
import assert from "node:assert/strict";
import {
  MAX_FILE_BYTES, collectAttachments, skippedNote, toBase64,
} from "../src/attachments.js";

function part({ filename = "foto.jpg", mimeType = "image/jpeg", size = 64, disposition = "attachment" } = {}) {
  return { filename, mimeType, disposition, content: new Uint8Array(size).fill(7).buffer };
}

test("inoltra gli allegati ammessi con nome e tipo normalizzati", () => {
  const { attachments, skipped } = collectAttachments({
    attachments: [part(), part({ filename: "", mimeType: "APPLICATION/PDF; charset=binary" })],
  });
  assert.equal(skipped, 0);
  assert.deepEqual(attachments.map((item) => [item.filename, item.content_type]), [
    ["foto.jpg", "image/jpeg"],
    ["allegato-2.pdf", "application/pdf"],
  ]);
  assert.equal(attachments[0].data, toBase64(new Uint8Array(64).fill(7)));
});

test("scarta i formati non ammessi e li dichiara", () => {
  const { attachments, skipped } = collectAttachments({
    attachments: [part({ filename: "logo.svg", mimeType: "image/svg+xml" }), part({ mimeType: "application/x-msdownload" })],
  });
  assert.deepEqual(attachments, []);
  assert.equal(skipped, 2);
  assert.equal(skippedNote(skipped), "[2 allegati non inoltrati]");
  assert.equal(skippedNote(1), "[1 allegato non inoltrato]");
  assert.equal(skippedNote(0), "");
});

test("ignora in silenzio loghi di firma e pixel inline", () => {
  const { attachments, skipped } = collectAttachments({
    attachments: [part({ filename: "logo.png", mimeType: "image/png", size: 900, disposition: "inline" })],
  });
  // non è una perdita da segnalare: è decorazione
  assert.deepEqual(attachments, []);
  assert.equal(skipped, 0);
});

test("una foto incollata nel corpo viene inoltrata", () => {
  const { attachments } = collectAttachments({
    attachments: [part({ filename: "schermata.png", mimeType: "image/png", size: 40 * 1024, disposition: "inline" })],
  });
  assert.equal(attachments.length, 1);
});

test("rispetta i limiti del backend invece di far rifiutare l'intera email", () => {
  const many = collectAttachments({ attachments: Array.from({ length: 7 }, () => part()) });
  assert.equal(many.attachments.length, 5);
  assert.equal(many.skipped, 2);

  const huge = collectAttachments({ attachments: [part({ size: MAX_FILE_BYTES + 1 })] });
  assert.deepEqual(huge, { attachments: [], skipped: 1 });

  const overTotal = collectAttachments({
    attachments: [part({ size: 6 * 1024 * 1024 }), part({ size: 6 * 1024 * 1024 })],
  });
  assert.equal(overTotal.attachments.length, 1);
  assert.equal(overTotal.skipped, 1);
});

test("un contenuto illeggibile non passa mai per buono", () => {
  const { attachments, skipped } = collectAttachments({
    attachments: [{ filename: "x.jpg", mimeType: "image/jpeg", disposition: "attachment", content: "non sono byte" }],
  });
  assert.deepEqual(attachments, []);
  assert.equal(skipped, 1);
});
