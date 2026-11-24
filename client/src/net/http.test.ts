import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, request, setTokenProvider } from "./http";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  setTokenProvider(null);
});

describe("request", () => {
  it("sends JSON with the Bearer token and parses the reply", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    setTokenProvider({ token: () => "tok", refresh: async () => true });

    expect(await request("POST", "/api/x", { body: { a: 1 } })).toEqual({ ok: 1 });
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init.headers.Authorization).toBe("Bearer tok");
    expect(init.body).toBe('{"a":1}');
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    let token = "old";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { reason_key: "auth.invalid_token" }))
      .mockResolvedValueOnce(json(200, { ok: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    const refresh = vi.fn(async () => {
      token = "new";
      return true;
    });
    setTokenProvider({ token: () => token, refresh });

    expect(await request("GET", "/api/x")).toEqual({ ok: 1 });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[1]![1].headers.Authorization).toBe("Bearer new");
  });

  it("gives up when the refresh fails, with the server's reason key", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { reason_key: "auth.invalid_token" })));
    setTokenProvider({ token: () => "t", refresh: async () => false });
    await expect(request("GET", "/api/x")).rejects.toMatchObject({
      status: 401,
      reasonKey: "auth.invalid_token",
    });
  });

  it("doesn't refresh for unauthenticated calls", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(401, { reason_key: "auth.invalid_credentials" })));
    const refresh = vi.fn(async () => true);
    setTokenProvider({ token: () => "t", refresh });
    await expect(request("POST", "/api/auth/login", { auth: false })).rejects.toBeInstanceOf(ApiError);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("maps network failures, 204s, Retry-After and non-JSON errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    await expect(request("GET", "/api/x")).rejects.toMatchObject({ status: 0, reasonKey: "network.error" });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await request("POST", "/api/x")).toBeUndefined();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(json(429, { reason_key: "auth.rate_limited" }, { "Retry-After": "7" })),
    );
    await expect(request("GET", "/api/x")).rejects.toMatchObject({ status: 429, retryAfterS: 7 });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 502 })));
    await expect(request("GET", "/api/x")).rejects.toMatchObject({ reasonKey: "http.502" });
  });
});
