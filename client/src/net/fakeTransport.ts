// A WebSocket transport double for store tests (combat, rooms): records requests, lets
// the test answer them, push server messages and fire the welcome. Test-only.
import { vi } from "vitest";

import type { ConnectionStatus, RequestPayloads, ServerMessage, WsClient } from "./ws";

/** The transport surface the stores use (each store picks its own subset). */
export type FakeTransport = Pick<WsClient, "connect" | "close" | "request" | "on" | "onWelcome" | "onStatus" | "status">;

type Handler = (message: ServerMessage) => void;

/** A transport double: records requests, lets the test answer them and push messages. */
export function fakeTransport(status: ConnectionStatus = "open") {
  const handlers = new Map<string, Handler[]>();
  const welcome: Array<() => void> = [];
  const requests: Array<{ type: string; payload: unknown }> = [];
  let answer: (type: string) => Promise<void> = async () => {};
  const transport = {
    status,
    connect: vi.fn(),
    close: vi.fn(),
    request: vi.fn(<T extends keyof RequestPayloads>(type: T, payload: RequestPayloads[T]) => {
      requests.push({ type, payload });
      return answer(type);
    }),
    on: vi.fn((type: string, handler: Handler) => {
      handlers.set(type, [...(handlers.get(type) ?? []), handler]);
      return () => {};
    }),
    onWelcome: vi.fn((handler: () => void) => {
      welcome.push(handler);
      return () => {};
    }),
    onStatus: vi.fn(() => () => {}),
  };
  return {
    transport: transport as unknown as FakeTransport,
    raw: transport,
    requests,
    answerWith(fn: (type: string) => Promise<void>) {
      answer = fn;
    },
    push(message: ServerMessage) {
      for (const handler of handlers.get(message.type) ?? []) handler(message);
    },
    welcome() {
      for (const handler of welcome) handler();
    },
  };
}

