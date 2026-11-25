// The one WebSocket connection (docs/protocol.md "WebSocket"): handshake, request/ack by
// id, typed push handlers, keepalive, and reconnect with backoff. It knows nothing about
// combat: subscribers re-subscribe from `onWelcome`, which fires after every (re)connect.
//
// The socket and the token source are injected so tests can drive it with a fake socket.
import {
  type AckMessage,
  type CombatEventsMessage,
  type CombatSnapshotMessage,
  type ErrorMessage,
  PROTOCOL_VERSION,
  type PongMessage,
  type RoomClosedMessage,
  type RoomStartedMessage,
  type RoomStateMessage,
  type WelcomeMessage,
} from "../protocol";

export type ServerMessage =
  | WelcomeMessage
  | AckMessage
  | ErrorMessage
  | PongMessage
  | CombatSnapshotMessage
  | CombatEventsMessage
  | RoomStateMessage
  | RoomStartedMessage
  | RoomClosedMessage;
export type ServerType = ServerMessage["type"];
type MessageOf<T extends ServerType> = Extract<ServerMessage, { type: T }>;

/** Request types that carry a payload, and the payload each one takes. */
export interface RequestPayloads {
  "auth.refresh": { access_token: string };
  "combat.subscribe": { combat_id: string; last_seq?: number | null };
  "combat.unsubscribe": { combat_id: string };
  "combat.action": { combat_id: string; intent: unknown };
  "room.subscribe": { room_id: string };
  "room.unsubscribe": { room_id: string };
}

export type ConnectionStatus =
  | "idle" // never started, or stopped by close()
  | "connecting" // socket opening or handshake in flight
  | "open" // welcomed: requests are accepted
  | "reconnecting" // lost; the next attempt is scheduled
  | "outdated" // protocol version mismatch: the page must reload
  | "signed_out"; // the session is gone (refresh failed)

/** Server close codes (docs/protocol.md "Close codes"). */
export const CloseCode = {
  NORMAL: 1000,
  GOING_AWAY: 1001,
  SERVER_ERROR: 1011,
  BAD_MESSAGE: 4400,
  UNAUTHORIZED: 4401,
  HANDSHAKE_TIMEOUT: 4408,
  OUTDATED: 4426,
  RATE_LIMITED: 4429,
} as const;

/** A request the server answered with `error`, or that never got an answer. */
export class WsError extends Error {
  constructor(readonly reasonKey: string) {
    super(reasonKey);
    this.name = "WsError";
  }
}

/** The subset of the browser WebSocket this client uses. */
export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

export interface WsClientOptions {
  url: string;
  /** The current access token, or null when signed out. */
  token(): string | null;
  /** Get a fresh access token; resolves false when the session is gone. */
  refresh(): Promise<boolean>;
  createSocket?: (url: string) => SocketLike;
  requestTimeoutMs?: number;
  pingIntervalMs?: number;
  /** Reconnect delays (ms); the last one repeats. Each gets up to +25 % jitter. */
  backoffMs?: readonly number[];
  random?: () => number;
}

const OPEN = 1;
const DEFAULT_BACKOFF_MS = [500, 1000, 2000, 4000, 8000, 15000];

interface Pending {
  resolve(): void;
  reject(error: WsError): void;
  timer: ReturnType<typeof setTimeout>;
}

export class WsClient {
  private socket: SocketLike | null = null;
  private wanted = false;
  private welcomed = false;
  private attempt = 0;
  private nextId = 1;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  private pingTimer: ReturnType<typeof setInterval> | undefined;
  private readonly pending = new Map<string, Pending>();
  private readonly handlers = new Map<ServerType, Set<(message: ServerMessage) => void>>();
  private readonly welcomeHandlers = new Set<() => void>();
  private readonly statusHandlers = new Set<(status: ConnectionStatus) => void>();
  private currentStatus: ConnectionStatus = "idle";

  constructor(private readonly options: WsClientOptions) {}

  get status(): ConnectionStatus {
    return this.currentStatus;
  }

  /** Start (or keep) the connection. Idempotent. */
  connect(): void {
    this.wanted = true;
    if (this.socket || this.reconnectTimer !== undefined) return;
    this.open();
  }

  /** Stop for good: no reconnects, pending requests fail. */
  close(): void {
    this.wanted = false;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
    const socket = this.socket;
    this.teardown("ws.disconnected");
    socket?.close(CloseCode.NORMAL);
    this.setStatus("idle");
  }

  /** Listen for one server message type. Returns an unsubscribe function. */
  on<T extends ServerType>(type: T, handler: (message: MessageOf<T>) => void): () => void {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    const wrapped = handler as (message: ServerMessage) => void;
    set.add(wrapped);
    return () => set.delete(wrapped);
  }

  /** Called after every successful handshake (first connect and each reconnect). */
  onWelcome(handler: () => void): () => void {
    this.welcomeHandlers.add(handler);
    return () => this.welcomeHandlers.delete(handler);
  }

  onStatus(handler: (status: ConnectionStatus) => void): () => void {
    this.statusHandlers.add(handler);
    return () => this.statusHandlers.delete(handler);
  }

  /** Send a request; resolves on `ack`, rejects with the server's reason key. */
  request<T extends keyof RequestPayloads>(type: T, payload: RequestPayloads[T]): Promise<void> {
    if (!this.welcomed || !this.socket) {
      return Promise.reject(new WsError("ws.disconnected"));
    }
    const id = `c-${this.nextId++}`;
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new WsError("ws.timeout"));
      }, this.options.requestTimeoutMs ?? 10_000);
      this.pending.set(id, { resolve, reject, timer });
      this.send({ type, id, payload });
    });
  }

  /** Hand the connection a new access token (call whenever the auth store refreshes). */
  updateToken(accessToken: string): void {
    if (this.welcomed) {
      this.request("auth.refresh", { access_token: accessToken }).catch(() => {
        // A rejected refresh ends in 4401, which the close handler deals with.
      });
    }
  }

  // --- connection lifecycle ---------------------------------------------------------

  private open(): void {
    const token = this.options.token();
    if (!token) {
      void this.reauthenticate();
      return;
    }
    this.setStatus("connecting");
    const create = this.options.createSocket ?? ((url) => new WebSocket(url) as SocketLike);
    const socket = create(this.options.url);
    this.socket = socket;
    socket.onopen = () => {
      this.send({
        type: "hello",
        payload: { protocol_version: PROTOCOL_VERSION, access_token: token },
      });
    };
    socket.onmessage = (event) => this.receive(event.data);
    socket.onclose = (event) => {
      if (this.socket === socket) this.closed(event.code);
    };
    socket.onerror = () => {
      // Always followed by onclose, which does the work.
    };
  }

  private closed(code: number): void {
    this.teardown("ws.disconnected");
    if (!this.wanted) return;
    switch (code) {
      case CloseCode.OUTDATED:
        this.wanted = false;
        this.setStatus("outdated");
        return;
      case CloseCode.UNAUTHORIZED:
        void this.reauthenticate();
        return;
      default:
        this.scheduleReconnect();
    }
  }

  /** The token was rejected or missing: refresh it, then reconnect right away. */
  private async reauthenticate(): Promise<void> {
    this.setStatus("connecting");
    const ok = await this.options.refresh();
    if (!this.wanted) return;
    if (ok && this.options.token()) {
      this.open();
    } else {
      this.wanted = false;
      this.setStatus("signed_out");
    }
  }

  private scheduleReconnect(): void {
    const backoff = this.options.backoffMs ?? DEFAULT_BACKOFF_MS;
    const base = backoff[Math.min(this.attempt, backoff.length - 1)] ?? 1000;
    const jitter = base * 0.25 * (this.options.random ?? Math.random)();
    this.attempt += 1;
    this.setStatus("reconnecting");
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      if (this.wanted) this.open();
    }, base + jitter);
  }

  /** Forget the socket and fail everything waiting on it. */
  private teardown(reasonKey: string): void {
    clearInterval(this.pingTimer);
    this.pingTimer = undefined;
    if (this.socket) {
      this.socket.onopen = this.socket.onmessage = this.socket.onclose = null;
      this.socket = null;
    }
    this.welcomed = false;
    for (const [id, request] of this.pending) {
      clearTimeout(request.timer);
      request.reject(new WsError(reasonKey));
      this.pending.delete(id);
    }
  }

  // --- messages ---------------------------------------------------------------------

  private send(message: object): void {
    if (this.socket?.readyState === OPEN) this.socket.send(JSON.stringify(message));
  }

  private receive(data: unknown): void {
    let message: ServerMessage;
    try {
      message = JSON.parse(String(data)) as ServerMessage;
    } catch {
      return; // the server never sends non-JSON; ignore rather than crash the UI
    }
    switch (message.type) {
      case "welcome":
        this.welcomed = true;
        this.attempt = 0;
        this.pingTimer = setInterval(
          () => this.send({ type: "ping" }),
          this.options.pingIntervalMs ?? 25_000,
        );
        this.setStatus("open");
        for (const handler of [...this.welcomeHandlers]) handler();
        break;
      case "ack":
        this.settle(message.id, null);
        break;
      case "error":
        if (message.id) this.settle(message.id, message.payload.reason_key);
        break;
    }
    for (const handler of [...(this.handlers.get(message.type) ?? [])]) handler(message);
  }

  private settle(id: string, reasonKey: string | null): void {
    const request = this.pending.get(id);
    if (!request) return;
    this.pending.delete(id);
    clearTimeout(request.timer);
    if (reasonKey === null) request.resolve();
    else request.reject(new WsError(reasonKey));
  }

  private setStatus(status: ConnectionStatus): void {
    if (status === this.currentStatus) return;
    this.currentStatus = status;
    for (const handler of [...this.statusHandlers]) handler(status);
  }
}

/** `ws(s)://<this origin>/ws` — same origin as the page (Vite proxies it in dev). */
export function defaultWsUrl(location: { protocol: string; host: string }): string {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`;
}
