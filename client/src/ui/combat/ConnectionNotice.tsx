import { t } from "../../i18n";
import { combat } from "../../state/combat";

/** A banner while the socket isn't usable; nothing when it is. */
export function ConnectionNotice() {
  switch (combat.connection.value) {
    case "connecting":
      return <p class="banner panel muted">{t("combat.connecting")}</p>;
    case "reconnecting":
      return <p class="banner panel muted">{t("combat.reconnecting")}</p>;
    case "outdated":
      return (
        <div class="banner panel row" role="alert">
          <span>{t("combat.outdated")}</span>
          <button type="button" onClick={() => window.location.reload()}>
            {t("combat.reload")}
          </button>
        </div>
      );
    default:
      return null; // open, idle, or signed out (the auth flow takes over)
  }
}
