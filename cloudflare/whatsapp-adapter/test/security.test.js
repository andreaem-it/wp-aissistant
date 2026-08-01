import test from "node:test";
import assert from "node:assert/strict";
import worker, { sameString, validMetaSignature } from "../src/index.js";

async function signature(body, secret) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, body);
  return `sha256=${[...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

test("compares secrets without early exit", () => {
  assert.equal(sameString("secret", "secret"), true);
  assert.equal(sameString("secret", "secrex"), false);
  assert.equal(sameString("short", "longer"), false);
});

test("validates the Meta webhook HMAC", async () => {
  const body = new TextEncoder().encode('{"entry":[]}');
  const signed = await signature(body, "app-secret");
  assert.equal(await validMetaSignature(body, signed, "app-secret"), true);
  assert.equal(await validMetaSignature(body, signed, "wrong-secret"), false);
  assert.equal(await validMetaSignature(body, "", "app-secret"), false);
});

test("verifies webhook subscription challenge", async () => {
  const env = { META_VERIFY_TOKEN: "verify-me" };
  const ok = await worker.fetch(
    new Request("https://worker.example/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=123"), env,
  );
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), "123");
  const denied = await worker.fetch(
    new Request("https://worker.example/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123"), env,
  );
  assert.equal(denied.status, 403);
});
