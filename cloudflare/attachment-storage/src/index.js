const MAX_BYTES = 10 * 1024 * 1024;
const encoder = new TextEncoder();

export function sameString(left, right) {
  const a = encoder.encode(left || ""); const b = encoder.encode(right || "");
  let mismatch = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) mismatch |= (a[i] || 0) ^ (b[i] || 0);
  return mismatch === 0;
}

function objectKey(request) {
  const encoded = new URL(request.url).pathname.replace(/^\/objects\//, "");
  if (!encoded) return "";
  try {
    const decoded = decodeURIComponent(encoded);
    return decoded.split("/").includes("..") ? "" : decoded;
  } catch { return ""; }
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname === "/health") return Response.json({ ok: true });
    if (!sameString(request.headers.get("authorization"), `Bearer ${env.STORAGE_TOKEN}`)) return new Response("Unauthorized", { status: 401 });
    const key = objectKey(request);
    if (!key) return new Response("Invalid key", { status: 400 });
    if (request.method === "PUT") {
      const length = Number(request.headers.get("content-length") || 0);
      if (length <= 0 || length > MAX_BYTES) return new Response("Invalid size", { status: 413 });
      await env.ATTACHMENTS.put(key, request.body, { httpMetadata: { contentType: request.headers.get("content-type") || "application/octet-stream" } });
      return Response.json({ ok: true });
    }
    if (request.method === "GET") {
      const object = await env.ATTACHMENTS.get(key);
      if (!object) return new Response("Not found", { status: 404 });
      const headers = new Headers(); object.writeHttpMetadata(headers); headers.set("etag", object.httpEtag);
      return new Response(object.body, { headers });
    }
    if (request.method === "DELETE") { await env.ATTACHMENTS.delete(key); return Response.json({ ok: true }); }
    return new Response("Method not allowed", { status: 405 });
  },
};
