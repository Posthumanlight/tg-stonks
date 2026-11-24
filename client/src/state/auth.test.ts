import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../net/http";
import type { TokenResponse } from "../protocol";

const api = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  refresh: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("../net/api", () => ({ authApi: api }));

const auth = await import("./auth");

const session = (token: string, expiresIn = 900): TokenResponse => ({
  access_token: token,
  expires_in: expiresIn,
  user: { user_id: 1, username: "alice", role: "player" },
});

beforeEach(() => {
  vi.useFakeTimers();
  Object.values(api).forEach((fn) => fn.mockReset());
});

afterEach(async () => {
  api.logout.mockResolvedValue(undefined);
  await auth.logout();
  vi.useRealTimers();
});

describe("auth state", () => {
  it("logs in and refreshes a minute before expiry", async () => {
    api.login.mockResolvedValue(session("t1"));
    api.refresh.mockResolvedValue(session("t2"));
    await auth.login("alice", "correct horse");
    expect(auth.getAccessToken()).toBe("t1");
    expect(auth.currentUser.value?.username).toBe("alice");

    await vi.advanceTimersByTimeAsync((900 - auth.REFRESH_MARGIN_S) * 1000 - 1);
    expect(api.refresh).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(api.refresh).toHaveBeenCalledTimes(1);
    expect(auth.getAccessToken()).toBe("t2");
  });

  it("shares one refresh between concurrent callers", async () => {
    api.refresh.mockResolvedValue(session("t"));
    const [a, b] = await Promise.all([auth.refreshSession(), auth.refreshSession()]);
    expect(a && b).toBe(true);
    expect(api.refresh).toHaveBeenCalledTimes(1);
  });

  it("retries once when another tab won the refresh race", async () => {
    api.refresh
      .mockRejectedValueOnce(new ApiError(409, "auth.refresh_race"))
      .mockResolvedValueOnce(session("t"));
    const result = auth.refreshSession();
    await vi.advanceTimersByTimeAsync(500);
    expect(await result).toBe(true);
    expect(api.refresh).toHaveBeenCalledTimes(2);
  });

  it("drops the session on 401 but keeps it when offline", async () => {
    api.login.mockResolvedValue(session("t1"));
    await auth.login("alice", "correct horse");

    api.refresh.mockRejectedValueOnce(new ApiError(0, "network.error"));
    expect(await auth.refreshSession()).toBe(false);
    expect(auth.currentUser.value).not.toBeNull();

    api.refresh.mockRejectedValueOnce(new ApiError(401, "auth.invalid_refresh"));
    expect(await auth.refreshSession()).toBe(false);
    expect(auth.currentUser.value).toBeNull();
    expect(auth.getAccessToken()).toBeNull();
  });

  it("registers then signs in", async () => {
    api.register.mockResolvedValue({ user_id: 1, username: "alice", role: "player" });
    api.login.mockResolvedValue(session("t"));
    await auth.register("alice", "correct horse");
    expect(api.login).toHaveBeenCalledWith({ username: "alice", password: "correct horse" });
    expect(auth.getAccessToken()).toBe("t");
  });
});
