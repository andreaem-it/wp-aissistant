import test from "node:test";
import assert from "node:assert/strict";
import worker, { sameString } from "../src/index.js";

test("constant-time token comparison handles lengths", () => {
  assert.equal(sameString("secret", "secret"), true); assert.equal(sameString("secret", "wrong"), false);
});
test("health is public and objects fail closed", async () => {
  assert.equal((await worker.fetch(new Request("https://x/health"), {})).status, 200);
  assert.equal((await worker.fetch(new Request("https://x/objects/a"), { STORAGE_TOKEN: "secret" })).status, 401);
});

test("authorized objects support a private upload/download/delete lifecycle", async () => {
  const objects = new Map();
  const bucket = {
    async put(key, body, options) {
      objects.set(key, {
        bytes: new Uint8Array(await new Response(body).arrayBuffer()),
        contentType: options.httpMetadata.contentType,
      });
    },
    async get(key) {
      const object = objects.get(key);
      if (!object) return null;
      return {
        body: object.bytes,
        httpEtag: '"test"',
        writeHttpMetadata(headers) { headers.set("content-type", object.contentType); },
      };
    },
    async delete(key) { objects.delete(key); },
  };
  const env = { STORAGE_TOKEN: "secret", ATTACHMENTS: bucket };
  const headers = { Authorization: "Bearer secret" };
  const put = await worker.fetch(new Request("https://x/objects/tenant/1/file.txt", {
    method: "PUT",
    headers: { ...headers, "Content-Type": "text/plain", "Content-Length": "5" },
    body: "hello",
  }), env);
  assert.equal(put.status, 200);
  const get = await worker.fetch(new Request("https://x/objects/tenant/1/file.txt", { headers }), env);
  assert.equal(get.status, 200);
  assert.equal(await get.text(), "hello");
  assert.equal(get.headers.get("content-type"), "text/plain");
  assert.equal((await worker.fetch(new Request("https://x/objects/tenant/1/file.txt", { method: "DELETE", headers }), env)).status, 200);
  assert.equal((await worker.fetch(new Request("https://x/objects/tenant/1/file.txt", { headers }), env)).status, 404);
});
