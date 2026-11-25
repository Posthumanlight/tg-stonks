// Typed endpoints. Same origin as the page: Vite proxies /api in dev, FastAPI serves
// both in production. Static data is revalidated by the browser's HTTP cache via ETag.
import type {
  BuilderView,
  CombatCreated,
  CombatSummaryView,
  CreateRoomRequest,
  CustomCombatRequest,
  GalaxyView,
  HealthView,
  LoginRequest,
  MyRoom,
  RegisterRequest,
  RoomJoined,
  RoomList,
  RoomReady,
  SideSetup,
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

export const combatApi = {
  /** The quick battle: created with the default armies, or the already active fight. */
  createDemo: (): Promise<CombatCreated> => request<CombatCreated>("POST", "/api/combats/demo"),
  /** Static builder data (ETag-revalidated). */
  getBuilder: (): Promise<BuilderView> => request<BuilderView>("GET", "/api/combats/builder"),
  /** A custom battle. 400 `setup.*` (detail: SetupErrorRef), 409 `combat.already_active`. */
  createCustom: (body: CustomCombatRequest): Promise<CombatCreated> =>
    request<CombatCreated>("POST", "/api/combats/custom", { body }),
  list: (): Promise<CombatSummaryView[]> => request<CombatSummaryView[]>("GET", "/api/combats"),
  abandon: (combatId: string): Promise<void> =>
    request<void>("POST", `/api/combats/${encodeURIComponent(combatId)}/abandon`),
};

const roomPath = (roomId: string, action: string): string =>
  `/api/rooms/${encodeURIComponent(roomId)}/${action}`;

/** Lobby rooms (docs/protocol.md "Lobby rooms"). Changes are pushed over the WebSocket. */
export const roomsApi = {
  /** 409 `room.already_in_room` / `combat.already_active`; 400 `room.bad_*`. */
  create: (body: CreateRoomRequest): Promise<RoomJoined> =>
    request<RoomJoined>("POST", "/api/rooms", { body }),
  search: (query: string, points: number | null): Promise<RoomList> => {
    const params = new URLSearchParams({ q: query });
    if (points !== null) params.set("points", String(points));
    return request<RoomList>("GET", `/api/rooms?${params.toString()}`);
  },
  mine: (): Promise<MyRoom> => request<MyRoom>("GET", "/api/rooms/mine"),
  /** Any room, public or private. 404 `room.not_found`, 429 when guessing. */
  joinByCode: (code: string): Promise<RoomJoined> =>
    request<RoomJoined>("POST", "/api/rooms/join", { body: { code } }),
  /** A public room from search. */
  join: (roomId: string): Promise<RoomJoined> => request<RoomJoined>("POST", roomPath(roomId, "join")),
  /** Lock in the army. 400 `setup.*` (detail: SetupErrorRef). `combat_id` when the battle began. */
  ready: (roomId: string, side: SideSetup): Promise<RoomReady> =>
    request<RoomReady>("POST", roomPath(roomId, "ready"), { body: side }),
  unready: (roomId: string): Promise<void> => request<void>("POST", roomPath(roomId, "unready")),
  leave: (roomId: string): Promise<void> => request<void>("POST", roomPath(roomId, "leave")),
  kick: (roomId: string): Promise<void> => request<void>("POST", roomPath(roomId, "kick")),
};
