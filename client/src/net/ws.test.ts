import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PROTOCOL_VERSION } from "../protocol";
import { CloseCode, type SocketLike, WsClient, WsError, defaultWsUrl } from "./ws";

class FakeSocket implements SocketLike {
  readyState = 0;
  sent: Array<{ type: string; id?: string; payload?: Record<string, unknown> }> = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  closedWith: number | undefined;

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }
  close(code?: number): void {
    this.closedWith = code;
  }
  // --- server side ---
  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }
  push(message: object): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
  welcome(): void {
    this.push({ type: "welcome", payload: { user_id: 1, role: "player", protocol_version: 2 } });
  }
  drop(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }
  last() {
    return this.sent[this.sent.length - 1];
  }
}

function setup(overrides: { token?: () => string | null; refresh?: () => Promise<boolean> } = {}) {
  const sockets: FakeSocket[] = [];
  const refresh = vi.fn(overrides.refresh ?? (async () => true));
  const client = new WsClient({
    url: "ws://test/ws",
    token: overrides.token ?? (() => "tok"),
    refresh,
    createSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    backoffMs: [100, 200],
    random: () => 0,
    requestTimeoutMs: 1000,
    pingIntervalMs: 5000,
  });
  const connect = () => {
    client.connect();
    const socket = sockets[sockets.length - 1]!;
    socket.open();
    socket.welcome();
    return socket;
  };
  return { client, sockets, refresh, connect };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("WsClient handshake", () => {
  it("sends hello with the token and protocol version, then opens on welcome", () => {
    const { client, sockets } = setup();
    const statuses: string[] = [];
    client.onStatus((s) => statuses.push(s));
    client.connect();
    const socket = sockets[0]!;
    socket.open();
    expect(socket.sent[0]).toEqual({
      type: "hello",
      payload: { protocol_version: PROTOCOL_VERSION, access_token: "tok" },
    });
    expect(client.status).toBe("connecting");
    socket.welcome();
    expect(client.status).toBe("open");
    expect(statuses).toEqual(["connecting", "open"]);
  });

  it("connect() is idempotent", () => {
    const { client, sockets } = setup();
    client.connect();
    client.connect();
    expect(sockets).toHaveLength(1);
  });

  it("pings periodically once open", () => {
    const { connect } = setup();
    const socket = connect();
    vi.advanceTimersByTime(5000);
    expect(socket.last()).toEqual({ type: "ping" });
  });
});

describe("WsClient requests", () => {
  it("resolves on ack and rejects with the error reason key", async () => {
    const { client, connect } = setup();
    const socket = connect();
    const ok = client.request("combat.subscribe", { combat_id: "c1" });
    const sent = socket.last()!;
    expect(sent.type).toBe("combat.subscribe");
    socket.push({ type: "ack", id: sent.id });
    await expect(ok).resolves.toBeUndefined();

    const bad = client.request("combat.action", { combat_id: "c1", intent: { type: "wait" } });
    socket.push({
      type: "error",
      id: socket.last()!.id,
      payload: { reason_key: "wait.forbidden" },
    });
    await expect(bad).rejects.toEqual(new WsError("wait.forbidden"));
  });

  it("times out unanswered requests", async () => {
    const { client, connect } = setup();
    connect();
    const pending = client.request("combat.subscribe", { combat_id: "c1" });
    vi.advanceTimersByTime(1000);
    await expect(pending).rejects.toMatchObject({ reasonKey: "ws.timeout" });
  });

  it("rejects immediately while not connected", async () => {
    const { client } = setup();
    await expect(client.request("combat.subscribe", { combat_id: "c1" })).rejects.toMatchObject({
      reasonKey: "ws.disconnected",
    });
  });

  it("fails pending requests when the connection drops", async () => {
    const { client, connect } = setup();
    const socket = connect();
    const pending = client.request("combat.subscribe", { combat_id: "c1" });
    socket.drop(1006);
    await expect(pending).rejects.toMatchObject({ reasonKey: "ws.disconnected" });
  });

  it("dispatches pushes to typed handlers", () => {
    const { client, connect } = setup();
    const seen: string[] = [];
    client.on("combat.events", (m) => seen.push(m.payload.combat_id));
    const socket = connect();
    socket.push({ type: "combat.events", payload: { combat_id: "c9" } });
    expect(seen).toEqual(["c9"]);
  });
});

describe("WsClient reconnect", () => {
  it("reconnects with backoff and fires onWelcome again", () => {
    const { client, sockets, connect } = setup();
    let welcomes = 0;
    client.onWelcome(() => welcomes++);
    connect();
    sockets[0]!.drop(1006);
    expect(client.status).toBe("reconnecting");
    vi.advanceTimersByTime(99);
    expect(sockets).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
    sockets[1]!.open();
    sockets[1]!.welcome();
    expect(welcomes).toBe(2);
    expect(client.status).toBe("open");
  });

  it("grows the delay on repeated failures and resets it after a welcome", () => {
    const { sockets, connect } = setup();
    connect();
    sockets[0]!.drop(1006);
    vi.advanceTimersByTime(100);
    sockets[1]!.drop(1006); // failed before welcome: next delay is 200
    vi.advanceTimersByTime(199);
    expect(sockets).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(sockets).toHaveLength(3);
    sockets[2]!.open();
    sockets[2]!.welcome();
    sockets[2]!.drop(1006); // back to the first delay
    vi.advanceTimersByTime(100);
    expect(sockets).toHaveLength(4);
  });

  it("refreshes the token on 4401, then reconnects at once", async () => {
    let token = "old";
    const { sockets, refresh, connect } = setup({
      token: () => token,
      refresh: async () => {
        token = "new";
        return true;
      },
    });
    connect();
    sockets[0]!.drop(CloseCode.UNAUTHORIZED);
    await vi.waitFor(() => expect(sockets).toHaveLength(2));
    expect(refresh).toHaveBeenCalledOnce();
    sockets[1]!.open();
    expect(sockets[1]!.sent[0]?.payload?.["access_token"]).toBe("new");
  });

  it("gives up as signed_out when the refresh fails", async () => {
    const { client, sockets, connect } = setup({ refresh: async () => false });
    connect();
    sockets[0]!.drop(CloseCode.UNAUTHORIZED);
    await vi.waitFor(() => expect(client.status).toBe("signed_out"));
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });

  it("stops on a version mismatch", () => {
    const { client, sockets, connect } = setup();
    connect();
    sockets[0]!.drop(CloseCode.OUTDATED);
    expect(client.status).toBe("outdated");
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });

  it("close() stops reconnecting and closes normally", () => {
    const { client, sockets, connect } = setup();
    const socket = connect();
    client.close();
    expect(socket.closedWith).toBe(CloseCode.NORMAL);
    expect(client.status).toBe("idle");
    vi.advanceTimersByTime(60_000);
    expect(sockets).toHaveLength(1);
  });
});

describe("WsClient token updates", () => {
  it("sends auth.refresh with the new token when open", () => {
    const { client, connect } = setup();
    const socket = connect();
    client.updateToken("fresh");
    expect(socket.last()).toMatchObject({
      type: "auth.refresh",
      payload: { access_token: "fresh" },
    });
  });
});

describe("defaultWsUrl", () => {
  it("matches the page's scheme and host", () => {
    expect(defaultWsUrl({ protocol: "https:", host: "example.org" })).toBe("wss://example.org/ws");
    expect(defaultWsUrl({ protocol: "http:", host: "localhost:5173" })).toBe("ws://localhost:5173/ws");
  });
});
