import { t } from "../../i18n";
import type { GalaxyView, StarView } from "../../protocol";
import {
  galaxyState,
  loadGalaxy,
  selectedStar,
  selectedStarIndex,
  starLinkCounts,
} from "../../state/galaxy";
import { goTo } from "../../state/screen";

/** DOM overlay above the galaxy chart. Only panels capture input (see styles.css). */
export function GalaxyOverlay() {
  const state = galaxyState.value;
  const star = selectedStar.value;

  return (
    <>
      <header class="topbar panel">
        <button type="button" class="icon" onClick={() => goTo("lobby")} aria-label={t("nav.back_to_lobby")}>
          ‹
        </button>
        <h1>{t("lobby.galaxy")}</h1>
        {state.status === "ready" && (
          <span class="muted">
            {t("galaxy.summary", {
              stars: state.galaxy.stars.length,
              clusters: state.galaxy.clusters.length,
            })}
          </span>
        )}
      </header>

      {(state.status === "loading" || state.status === "idle") && (
        <p class="note">{t("galaxy.loading")}</p>
      )}

      {state.status === "error" && (
        <div class="note panel" role="alert">
          <p>{t("galaxy.error")}</p>
          <button type="button" onClick={() => void loadGalaxy()}>
            {t("galaxy.retry")}
          </button>
        </div>
      )}

      {state.status === "ready" && !star && <p class="hint">{t("galaxy.hint")}</p>}

      {state.status === "ready" && star && (
        <StarSheet galaxy={state.galaxy} star={star} />
      )}
    </>
  );
}

interface StarSheetProps {
  galaxy: GalaxyView;
  star: StarView;
}

function StarSheet({ galaxy, star }: StarSheetProps) {
  const close = () => {
    selectedStarIndex.value = null;
  };

  const counts = starLinkCounts.value;
  const cluster = galaxy.clusters[star.cluster];
  return (
    <section class="sheet panel" aria-labelledby="star-name">
      <div class="sheet-head">
        <div>
          <h2 id="star-name">{star.name}</h2>
          <span class="muted">{star.code}</span>
        </div>
        <button type="button" class="icon" onClick={close} aria-label={t("star.close")}>
          ×
        </button>
      </div>
      <dl class="facts">
        <dt>{t("star.class")}</dt>
        <dd>{`${star.star_class}${star.subclass}V`}</dd>
        <dt>{t("star.cluster")}</dt>
        <dd>{cluster ? `${cluster.name} (${cluster.code})` : "—"}</dd>
        <dt>{t("star.links")}</dt>
        <dd>{counts?.lanes[star.index] ?? 0}</dd>
        <dt>{t("star.bridges")}</dt>
        <dd>{counts?.bridges[star.index] ?? 0}</dd>
      </dl>
    </section>
  );
}
