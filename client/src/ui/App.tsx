import { useEffect } from "preact/hooks";

import { t } from "../i18n";
import type { Platform } from "../platform/telegram";
import type { GalaxyView, StarView } from "../protocol";
import {
  galaxyState,
  loadGalaxy,
  selectedStar,
  selectedStarIndex,
  starLinkCounts,
} from "../state/galaxy";

interface AppProps {
  platform: Platform;
}

/** DOM overlay above the Phaser canvas. Only panels capture input (see styles.css). */
export function App({ platform }: AppProps) {
  const state = galaxyState.value;
  const star = selectedStar.value;

  return (
    <>
      <header class="topbar panel">
        <h1>{t("app.title")}</h1>
        {state.status === "ready" && (
          <span class="muted">
            {t("galaxy.summary", {
              stars: state.galaxy.stars.length,
              clusters: state.galaxy.clusters.length,
            })}
          </span>
        )}
      </header>

      {state.status === "loading" && <p class="note">{t("galaxy.loading")}</p>}

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
        <StarSheet galaxy={state.galaxy} star={star} platform={platform} />
      )}
    </>
  );
}

interface StarSheetProps {
  galaxy: GalaxyView;
  star: StarView;
  platform: Platform;
}

function StarSheet({ galaxy, star, platform }: StarSheetProps) {
  const close = () => {
    selectedStarIndex.value = null;
  };
  // Inside Telegram, the native back button closes the sheet too.
  useEffect(() => {
    platform.setBackButton(close);
    return () => platform.setBackButton(null);
  }, [platform]);

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
