import { useEffect, useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { ApiError, roomsApi } from "../../net/api";
import { builder } from "../../state/builder";
import { REFRESH_MS } from "../../state/roomsStore";
import { rooms } from "../../state/rooms";
import { goTo } from "../../state/screen";
import { enterRoom } from "./navigation";

const reasonOf = (failure: unknown): string => (failure instanceof ApiError ? failure.reasonKey : "error.generic");

/** "0 = unlimited" presets as labels. */
export const pointsText = (points: number): string =>
  points === 0 ? t("rooms.unlimited") : t("builder.points", { points });
export const timerText = (seconds: number): string =>
  seconds === 0 ? t("rooms.untimed") : t("rooms.seconds", { seconds });

/** Online games (docs/client.md "Lobby rooms"): create a room, or find an open one. */
export function RoomsScreen() {
  useEffect(() => {
    void builder.load(); // the presets live in the builder data
    void rooms.refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void rooms.refresh();
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <main class="screen-center">
      <section class="panel card stack rooms-panel">
        <header class="row">
          <button type="button" class="icon" onClick={() => goTo("lobby")} aria-label={t("nav.back_to_lobby")}>
            ‹
          </button>
          <h1>{t("rooms.title")}</h1>
        </header>
        <CreateRoom />
        <hr />
        <FindRooms />
      </section>
    </main>
  );
}

function CreateRoom() {
  const presets = builder.view.value?.rooms;
  const [name, setName] = useState("");
  const [isPrivate, setPrivate] = useState(false);
  const [points, setPoints] = useState<number | null>(null);
  const [timer, setTimer] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!presets) return <p class="muted">{t("builder.loading")}</p>;
  const chosenPoints = points ?? presets.points_presets[0] ?? 0;
  const chosenTimer = timer ?? presets.default_timer_s;

  const submit = async (e: Event) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const joined = await roomsApi.create({
        name: name.trim() || t("rooms.default_name"),
        private: isPrivate,
        points_limit: chosenPoints,
        timer_s: chosenTimer,
      });
      enterRoom(joined.room_id);
    } catch (failure) {
      setError(reasonOf(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="stack-tight" onSubmit={(e) => void submit(e)}>
      <h2>{t("rooms.create")}</h2>
      <label class="field">
        <span class="muted">{t("rooms.name")}</span>
        <input
          value={name}
          maxLength={40}
          placeholder={t("rooms.default_name")}
          onInput={(e) => setName((e.currentTarget as HTMLInputElement).value)}
        />
      </label>
      <div class="row wrap">
        <label class="field">
          <span class="muted">{t("rooms.points")}</span>
          <select
            value={String(chosenPoints)}
            onChange={(e) => setPoints(Number((e.currentTarget as HTMLSelectElement).value))}
          >
            {presets.points_presets.map((p) => (
              <option key={p} value={String(p)}>
                {pointsText(p)}
              </option>
            ))}
          </select>
        </label>
        <label class="field">
          <span class="muted">{t("rooms.timer")}</span>
          <select
            value={String(chosenTimer)}
            onChange={(e) => setTimer(Number((e.currentTarget as HTMLSelectElement).value))}
          >
            {presets.timer_presets.map((s) => (
              <option key={s} value={String(s)}>
                {timerText(s)}
              </option>
            ))}
          </select>
        </label>
        <label class="check">
          <input
            type="checkbox"
            checked={isPrivate}
            onChange={(e) => setPrivate((e.currentTarget as HTMLInputElement).checked)}
          />
          {t("rooms.private")}
        </label>
      </div>
      <p class="muted">{isPrivate ? t("rooms.private_hint") : t("rooms.public_hint")}</p>
      {error && (
        <p class="error" role="alert">
          {tError(error)}
        </p>
      )}
      <button type="submit" class="primary" disabled={busy}>
        {t("rooms.create_button")}
      </button>
    </form>
  );
}

function FindRooms() {
  const presets = builder.view.value?.rooms;
  const state = rooms.list.value;
  const [error, setError] = useState<string | null>(null);

  const join = async (roomId: string) => {
    setError(null);
    try {
      const joined = await roomsApi.join(roomId);
      enterRoom(joined.room_id);
    } catch (failure) {
      setError(reasonOf(failure));
      void rooms.refresh(); // it may have filled up or closed
    }
  };

  return (
    <div class="stack-tight">
      <h2>{t("rooms.find")}</h2>
      <div class="row wrap">
        <input
          type="search"
          value={rooms.query.value}
          placeholder={t("rooms.search")}
          aria-label={t("rooms.search")}
          onInput={(e) => rooms.setFilter({ query: (e.currentTarget as HTMLInputElement).value })}
        />
        <select
          aria-label={t("rooms.points")}
          value={rooms.points.value === null ? "" : String(rooms.points.value)}
          onChange={(e) => {
            const value = (e.currentTarget as HTMLSelectElement).value;
            rooms.setFilter({ points: value === "" ? null : Number(value) });
          }}
        >
          <option value="">{t("rooms.any_points")}</option>
          {presets?.points_presets.map((p) => (
            <option key={p} value={String(p)}>
              {pointsText(p)}
            </option>
          ))}
        </select>
        <button type="button" onClick={() => void rooms.refresh()}>
          {t("rooms.refresh")}
        </button>
      </div>
      {error && (
        <p class="error" role="alert">
          {tError(error)}
        </p>
      )}
      {state.status === "loading" && <p class="muted">{t("rooms.loading")}</p>}
      {state.status === "error" && <p class="error">{tError(state.reason)}</p>}
      {state.status === "ready" && state.rooms.length === 0 && <p class="muted">{t("rooms.none")}</p>}
      {state.status === "ready" && state.rooms.length > 0 && (
        <ul class="room-list">
          {state.rooms.map((card) => (
            <li key={card.room_id} class="room-card">
              <div class="stack-tight">
                <strong>{card.name}</strong>
                <span class="muted">
                  {t("rooms.host", { name: card.host_name })} · {pointsText(card.points_limit)} ·{" "}
                  {timerText(card.timer_s)}
                </span>
              </div>
              <button type="button" class="primary" onClick={() => void join(card.room_id)}>
                {t("rooms.join")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
