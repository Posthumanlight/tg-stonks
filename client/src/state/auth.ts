// The signed-in session. The access token lives in memory only (never localStorage);
// the refresh token is an httpOnly cookie this code never sees
// (docs/architecture.md "Authentication").
import { signal } from "@preact/signals";

import { authApi } from "../net/api";
import { ApiError, setTokenProvider } from "../net/http";
import type { TokenResponse, UserView } from "../protocol";

/** Refresh this long before the access token expires. */
export const REFRESH_MARGIN_S = 60;
const MIN_REFRESH_DELAY_S = 5;
const RETRY_AFTER_FAILURE_S = 10;
const RACE_RETRY_MS = 500;

export const currentUser = signal<UserView | null>(null);

let accessToken: string | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let inflight: Promise<boolean> | null = null;
const tokenListeners = new Set<(token: string) => void>();

export function getAccessToken(): string | null {
  return accessToken;
}

/** Called with each new access token (login or refresh), e.g. to update the WebSocket. */
export function onTokenChange(listener: (token: string) => void): () => void {
  tokenListeners.add(listener);
  return () => tokenListeners.delete(listener);
}

function schedule(delayS: number): void {
  clearTimeout(timer);
  timer = setTimeout(() => void refreshSession(), delayS * 1000);
}

function apply(session: TokenResponse): void {
  accessToken = session.access_token;
  currentUser.value = session.user;
  schedule(Math.max(MIN_REFRESH_DELAY_S, session.expires_in - REFRESH_MARGIN_S));
  for (const listener of [...tokenListeners]) listener(session.access_token);
}

function clear(): void {
  clearTimeout(timer);
  accessToken = null;
  currentUser.value = null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function doRefresh(): Promise<boolean> {
  for (let attempt = 0; ; attempt++) {
    try {
      apply(await authApi.refresh());
      return true;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.reasonKey === "auth.refresh_race" && attempt === 0) {
        await sleep(RACE_RETRY_MS); // another tab rotated first; its cookie is ours now
        continue;
      }
      if (error.status === 401 || error.status === 403 || error.status === 409) {
        clear(); // the session is gone
      } else {
        schedule(RETRY_AFTER_FAILURE_S); // offline or server trouble: keep the session
      }
      return false;
    }
  }
}

/** Get a fresh access token. Concurrent callers share one request. */
export function refreshSession(): Promise<boolean> {
  inflight ??= doRefresh().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** On page load: resume the session from the refresh cookie, if any. */
export async function bootstrapAuth(): Promise<boolean> {
  return refreshSession();
}

export async function login(username: string, password: string): Promise<void> {
  apply(await authApi.login({ username, password }));
}

export async function register(username: string, password: string): Promise<void> {
  await authApi.register({ username, password });
  await login(username, password);
}

export async function logout(): Promise<void> {
  try {
    await authApi.logout();
  } finally {
    clear();
  }
}

setTokenProvider({ token: getAccessToken, refresh: refreshSession });
