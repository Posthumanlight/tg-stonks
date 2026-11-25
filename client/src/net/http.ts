// The one HTTP wrapper every API call goes through: JSON in/out, Bearer auth, a single
// refresh-and-retry on 401, and typed errors carrying the server's i18n reason key.
//
// The token source is injected (setTokenProvider) so this module doesn't depend on the
// auth state — the auth state depends on it.

export class ApiError extends Error {
  constructor(
    readonly status: number, // 0 = network failure
    readonly reasonKey: string,
    readonly retryAfterS?: number,
    /** The body's `detail`: a developer message, or e.g. a SetupErrorRef. */
    readonly detail?: unknown,
  ) {
    super(reasonKey);
    this.name = "ApiError";
  }
}

export interface TokenProvider {
  token(): string | null;
  /** Get a fresh access token; resolves false when the session is gone. */
  refresh(): Promise<boolean>;
}

let provider: TokenProvider | null = null;

export function setTokenProvider(next: TokenProvider | null): void {
  provider = next;
}

export interface RequestOptions {
  body?: unknown;
  /** Attach the Bearer token and refresh on 401 (default true). */
  auth?: boolean;
  signal?: AbortSignal;
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

async function send(method: Method, path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const token = options.auth === false ? null : (provider?.token() ?? null);
  if (token) headers["Authorization"] = `Bearer ${token}`;
  try {
    return await fetch(path, {
      method,
      headers,
      body: options.body === undefined ? null : JSON.stringify(options.body),
      credentials: "same-origin",
      signal: options.signal ?? null,
    });
  } catch {
    throw new ApiError(0, "network.error");
  }
}

async function toError(response: Response): Promise<ApiError> {
  let reasonKey = `http.${response.status}`;
  let detail: unknown;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "reason_key" in body) {
      reasonKey = String((body as { reason_key: unknown }).reason_key);
      detail = (body as { detail?: unknown }).detail;
    }
  } catch {
    // not JSON: keep the generic key
  }
  const header = response.headers.get("Retry-After");
  const retryAfter = header === null ? NaN : Number(header);
  return new ApiError(
    response.status,
    reasonKey,
    Number.isFinite(retryAfter) ? retryAfter : undefined,
    detail,
  );
}

export async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  let response = await send(method, path, options);
  if (response.status === 401 && options.auth !== false && provider) {
    if (await provider.refresh()) {
      response = await send(method, path, options);
    }
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
