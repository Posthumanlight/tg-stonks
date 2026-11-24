// Typed endpoints. Same origin as the page: Vite proxies /api in dev, FastAPI serves
// both in production. Static data is revalidated by the browser's HTTP cache via ETag.
import type {
  GalaxyView,
  HealthView,
  LoginRequest,
  RegisterRequest,
  TokenResponse,
  UserView,
} from "../protocol";
import { request } from "./http";

export { ApiError } from "./http";

export const getHealth = (): Promise<HealthView> =>
  request<HealthView>("GET", "/api/health", { auth: false });

export const getGalaxy = (signal?: AbortSignal): Promise<GalaxyView> =>
  request<GalaxyView>("GET", "/api/world/galaxy", signal ? { signal } : {});

export const authApi = {
  register: (body: RegisterRequest): Promise<UserView> =>
    request<UserView>("POST", "/api/auth/register", { body, auth: false }),
  login: (body: LoginRequest): Promise<TokenResponse> =>
    request<TokenResponse>("POST", "/api/auth/login", { body, auth: false }),
  /** Uses the httpOnly refresh cookie; the client never sees it. */
  refresh: (): Promise<TokenResponse> =>
    request<TokenResponse>("POST", "/api/auth/refresh", { auth: false }),
  logout: (): Promise<void> => request<void>("POST", "/api/auth/logout", { auth: false }),
};
