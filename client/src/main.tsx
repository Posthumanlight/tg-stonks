import "./ui/styles.css";

import { render } from "preact";

import { startGame } from "./game/config";
import { initI18n, t } from "./i18n";
import { initPlatform } from "./platform/telegram";
import { loadGalaxy } from "./state/galaxy";
import { App } from "./ui/App";

function mustGet(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`#${id} missing from index.html`);
  return element;
}

const platform = initPlatform();
initI18n(platform.languageCode);
document.title = t("app.title");

render(<App platform={platform} />, mustGet("ui"));
startGame(mustGet("game"));
void loadGalaxy();
