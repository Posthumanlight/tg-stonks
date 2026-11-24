import { useState } from "preact/hooks";

import { t, tError } from "../../i18n";
import { ApiError } from "../../net/http";
import { login, register } from "../../state/auth";

type Mode = "login" | "register";

/** Sign in or create an account. On success the auth state moves us to the lobby. */
export function Login() {
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);

  const submit = async (event: Event) => {
    event.preventDefault();
    setBusy(true);
    setErrorKey(null);
    try {
      await (mode === "login" ? login : register)(username, password);
    } catch (error) {
      setErrorKey(error instanceof ApiError ? error.reasonKey : "network.error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main class="screen-center">
      <form class="panel card stack" onSubmit={(e) => void submit(e)}>
        <h1>{t("app.title")}</h1>
        <h2>{t(mode === "login" ? "auth.login.title" : "auth.register.title")}</h2>
        <label class="field">
          <span>{t("auth.username")}</span>
          <input
            name="username"
            autocomplete="username"
            value={username}
            onInput={(e) => setUsername(e.currentTarget.value)}
            required
          />
        </label>
        <label class="field">
          <span>{t("auth.password")}</span>
          <input
            name="password"
            type="password"
            autocomplete={mode === "login" ? "current-password" : "new-password"}
            value={password}
            onInput={(e) => setPassword(e.currentTarget.value)}
            required
          />
        </label>
        {mode === "register" && <p class="muted">{t("auth.register.rules")}</p>}
        {errorKey && (
          <p class="error" role="alert">
            {tError(errorKey)}
          </p>
        )}
        <button type="submit" class="primary" disabled={busy}>
          {t(mode === "login" ? "auth.login.submit" : "auth.register.submit")}
        </button>
        <button
          type="button"
          class="link"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setErrorKey(null);
          }}
        >
          {t(mode === "login" ? "auth.switch_to_register" : "auth.switch_to_login")}
        </button>
      </form>
    </main>
  );
}
