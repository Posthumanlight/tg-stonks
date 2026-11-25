// Combat screen state as signals, fed by WebSocket pushes (docs/client.md "Combat").
// The server's `view` replaces local state wholesale and `legal` lists every option:
// there are no rules here (CLAUDE.md rule 1). Events only feed the log.
//
// Online battles: `board.players` says who holds each side; the player acts (and sees
// highlights) only on their own side's activations, against the server's deadline.
import { batch, computed, signal } from "@preact/signals";

import {
  type Intent,
  type Mode,
  MOVE_MODE,
  type Square,
  highlights,
  isSelfCast,
  keepMode,
  tapResult,
} from "../combat/interaction";
import type { WsClient } from "../net/ws";
import { WsError } from "../net/ws";
import type {
  AbilityOptionView,
  BoardView,
  CombatCreated,
  CombatEvent,
  CombatLegal,
  CombatSnapshot,
  CombatUpdate,
  CombatView,
} from "../protocol";

/** How many events the log keeps (older ones scroll away). */
export const LOG_LIMIT = 200;

export type CombatTransport = Pick<
  WsClient,
  "connect" | "close" | "request" | "on" | "onWelcome" | "onStatus" | "status"
>;

export interface CombatApi {
  createDemo(): Promise<CombatCreated>;
}

const reasonOf = (error: unknown): string =>
  error instanceof WsError ? error.reasonKey : "error.generic";

/** The signed-in user's id (read inside computeds, so it may be a signal read). */
export type CurrentUserId = () => number | null;

export function createCombatStore(transport: CombatTransport, api: CombatApi, me: CurrentUserId = () => null) {
  const combatId = signal<string | null>(null);
  const board = signal<BoardView | null>(null);
  const view = signal<CombatView | null>(null);
  const legal = signal<CombatLegal | null>(null);
  const log = signal<readonly CombatEvent[]>([]);
  const mode = signal<Mode>(MOVE_MODE);
  const inspected = signal<number | null>(null);
  const lastError = signal<string | null>(null);
  const connection = signal(transport.status);
  const busy = signal(false);
  /** When the active unit's timer runs out (epoch ms); null: untimed. */
  const deadline = signal<number | null>(null);

  /** The unit the side panel shows: the tapped one, else the active one. */
  const shownUnit = computed(() => {
    const units = view.value?.units ?? [];
    const uid = inspected.value ?? view.value?.active?.uid ?? null;
    return units.find((u) => u.uid === uid) ?? null;
  });
  const activeUnit = computed(() => {
    const current = view.value;
    return current?.units.find((u) => u.uid === current.active?.uid) ?? null;
  });
  /** Sides this user holds. Hotseat (or a record without seats): every side. */
  const mySides = computed<readonly number[] | null>(() => {
    const players = board.value?.players;
    if (!players) return null;
    const user = me();
    return players.filter((p) => p.user_id === user).map((p) => p.side);
  });
  /** Someone else holds a side: an online battle. */
  const online = computed(() => (board.value?.players ?? []).some((p) => p.user_id !== me()));
  const myTurn = computed(() => {
    const unit = activeUnit.value;
    const sides = mySides.value;
    return unit !== null && (sides === null || sides.includes(unit.side));
  });
  /** Player names per side in an online battle (labels); undefined in hotseat. */
  const sideNames = computed<readonly string[] | undefined>(() => {
    if (!online.value) return undefined;
    const names: string[] = [];
    for (const p of board.value?.players ?? []) names[p.side] = p.name;
    return names;
  });
  const marks = computed(() => highlights(myTurn.value ? legal.value : null, mode.value));

  function reset(): void {
    batch(() => {
      board.value = view.value = legal.value = null;
      deadline.value = null;
      log.value = [];
      mode.value = MOVE_MODE;
      inspected.value = lastError.value = null;
      busy.value = false;
    });
  }

  function applySnapshot(snapshot: CombatSnapshot): void {
    if (snapshot.view.combat_id !== combatId.peek()) return;
    batch(() => {
      board.value = snapshot.board;
      view.value = snapshot.view;
      legal.value = snapshot.legal;
      deadline.value = snapshot.deadline_ms ?? null;
      mode.value = keepMode(mode.peek(), snapshot.legal);
    });
  }

  function applyUpdate(update: CombatUpdate): void {
    const current = view.peek();
    if (update.combat_id !== combatId.peek() || !current) return;
    if (update.view.seq <= current.seq) return; // already have it (resync overlap)
    if (update.from_seq > current.seq) {
      void subscribe(); // missed something: ask for a catch-up or a snapshot
      return;
    }
    const fresh = update.events.filter((e) => e.seq >= current.seq);
    batch(() => {
      view.value = update.view;
      legal.value = update.legal;
      deadline.value = update.deadline_ms ?? null;
      log.value = [...log.peek(), ...fresh].slice(-LOG_LIMIT);
      mode.value = keepMode(mode.peek(), update.legal);
    });
  }

  async function subscribe(): Promise<void> {
    const id = combatId.peek();
    if (!id) return;
    try {
      await transport.request("combat.subscribe", {
        combat_id: id,
        last_seq: view.peek()?.seq ?? null,
      });
    } catch (error) {
      if (combatId.peek() === id) lastError.value = reasonOf(error);
    }
  }

  transport.on("combat.snapshot", (message) => applySnapshot(message.payload));
  transport.on("combat.events", (message) => applyUpdate(message.payload));
  transport.onWelcome(() => void subscribe()); // every (re)connect resubscribes
  transport.onStatus((status) => (connection.value = status));

  /** Connect to a fight by id (just created, or resumed from the lobby). */
  function open(id: string): void {
    reset();
    combatId.value = id;
    if (transport.status === "open") void subscribe();
    else transport.connect();
  }

  /** Create (or resume) the quick battle and connect to it. Throws the HTTP error. */
  async function openDemo(): Promise<void> {
    const { combat_id } = await api.createDemo();
    open(combat_id);
  }

  function leave(): void {
    const id = combatId.peek();
    if (id && transport.status === "open") {
      transport.request("combat.unsubscribe", { combat_id: id }).catch(() => {});
    }
    combatId.value = null;
    reset();
    transport.close();
  }

  async function act(intent: Intent): Promise<void> {
    const id = combatId.peek();
    if (!id || busy.peek()) return;
    batch(() => {
      busy.value = true;
      lastError.value = null;
    });
    try {
      await transport.request("combat.action", { combat_id: id, intent });
      mode.value = MOVE_MODE;
    } catch (error) {
      lastError.value = reasonOf(error);
    } finally {
      busy.value = false;
    }
  }

  function tap(square: Square): void {
    const options = myTurn.peek() ? legal.peek() : null; // the opponent's turn: look only
    const result = tapResult(square, options, mode.peek(), view.peek()?.units ?? []);
    switch (result.kind) {
      case "intent":
        void act(result.intent);
        break;
      case "inspect":
        inspected.value = result.unit;
        break;
      case "cancel":
        mode.value = MOVE_MODE;
        break;
      case "none":
        inspected.value = null;
        break;
    }
  }

  /** Weapon button: toggle attack mode for it. */
  function chooseWeapon(weapon: string): void {
    const current = mode.peek();
    mode.value =
      current.kind === "attack" && current.weapon === weapon
        ? MOVE_MODE
        : { kind: "attack", weapon };
  }

  /** Ability button: cast a self ability now, otherwise toggle targeting mode. */
  function chooseAbility(option: AbilityOptionView): void {
    const options = legal.peek();
    if (options && isSelfCast(option, options.unit)) {
      void act({ type: "ability", ability: option.ability });
      return;
    }
    const current = mode.peek();
    mode.value =
      current.kind === "ability" && current.ability === option.ability
        ? MOVE_MODE
        : { kind: "ability", ability: option.ability };
  }

  return {
    combatId,
    board,
    view,
    legal,
    log,
    mode,
    inspected,
    lastError,
    connection,
    busy,
    deadline,
    shownUnit,
    activeUnit,
    mySides,
    online,
    myTurn,
    sideNames,
    marks,
    open,
    openDemo,
    leave,
    act,
    tap,
    chooseWeapon,
    chooseAbility,
    /** Exposed for tests. */
    applySnapshot,
    applyUpdate,
  };
}

export type CombatStore = ReturnType<typeof createCombatStore>;
