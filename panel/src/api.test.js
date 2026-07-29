// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, clearToken, getEmail, getToken, setEmail, setToken } from "./api";

describe("operator API client", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("stores and clears the operator identity", () => {
    setToken("session-token");
    setEmail("operator@example.test");
    expect(getToken()).toBe("session-token");
    expect(getEmail()).toBe("operator@example.test");

    clearToken();
    expect(getToken()).toBe("");
  });

  it("does not send an Authorization header during login", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ token: "new-token" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(api.login("op@example.test", "secret")).resolves.toEqual({
      token: "new-token",
    });
    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBeUndefined();
    expect(JSON.parse(options.body)).toEqual({
      email: "op@example.test",
      password: "secret",
    });
  });

  it("attaches the bearer token to authenticated calls", async () => {
    setToken("session-token");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ email: "op@example.test" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await api.me();
    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBe("Bearer session-token");
  });
});
