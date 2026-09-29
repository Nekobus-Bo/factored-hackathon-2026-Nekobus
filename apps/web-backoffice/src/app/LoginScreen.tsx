import { useState, type FormEvent } from "react";
import type { LoginError } from "../machines/app";
import { useI18n } from "./context";
import { Alert } from "./ui";

export function LoginScreen({ submitting, error, onSubmit }: { submitting: boolean; error: LoginError | null; onSubmit: (email: string, password: string) => void }) {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!submitting) onSubmit(email.trim(), password);
  };

  return (
    <main className="bo-login">
      <form className="pb-card bo-login__card" onSubmit={submit} aria-labelledby="login-title">
        <h1 className="h1" id="login-title">
          {t("login.title")}
        </h1>
        <p className="pb-t-small">{t("login.lede")}</p>

        <div className="bo-field">
          <label className="pb-t-label" htmlFor="login-email">
            {t("login.email")}
          </label>
          <div className="pb-field">
            <input id="login-email" type="email" name="email" autoComplete="username" autoFocus required value={email} onChange={(event) => setEmail(event.target.value)} />
          </div>
        </div>

        <div className="bo-field">
          <label className="pb-t-label" htmlFor="login-password">
            {t("login.password")}
          </label>
          <div className="pb-field">
            <input id="login-password" type="password" name="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          </div>
        </div>

        {error !== null && (
          <Alert tone="caution" eyebrow={t("login.title")}>
            {t(error === "invalid" ? "login.invalid" : error === "malformed" ? "login.malformed" : "login.unavailable")}
          </Alert>
        )}

        <button type="submit" className="pb-btn pb-btn--primary pb-btn--block" disabled={submitting}>
          {submitting ? t("login.submitting") : t("login.submit")}
        </button>
        <p className="pb-t-small">{t("login.demoNote")}</p>
      </form>
    </main>
  );
}
