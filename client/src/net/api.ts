// Typed HTTP calls. Same origin as the page: Vite proxies /api in dev, FastAPI serves
// both in production. Static data is revalidated by the browser's HTTP cache via ETag.
import type { GalaxyView, HealthView } from "../protocol";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { Accept: "application/json" }, signal });
  } catch (cause) {
    throw new ApiError(0, `network error on ${path}: ${String(cause)}`);
  }
  if (!response.ok) {
    throw new ApiError(response.status, `${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const getHealth = (signal?: AbortSignal): Promise<HealthView> =>
  getJson<HealthView>("/api/health", signal);

export const getGalaxy = (signal?: AbortSignal): Promise<GalaxyView> =>
  getJson<GalaxyView>("/api/world/galaxy", signal);
