import { useEffect, useState } from "react";
import { api } from "./api.js";

// Strip a query param from the URL bar after we've consumed its token, so a refresh
// (or the browser back button) doesn't replay a one-shot verify/reset link.
function clearParam(name) {
  const url = new URL(window.location.href);
  url.searchParams.delete(name);
  window.history.replaceState({}, "", url.pathname + url.search);
}

// Shell matching the login card so the standalone auth screens feel native.
function AuthCard({ title, sub, children }) {
  return (
    <div className="wpai-login">
      <div className="wpai-login-card">
        <div className="wpai-brand">
          <div className="wpai-brand-mark" />
          <div className="wpai-brand-name">
            <span className="dim">WP</span> AIssistant
          </div>
        </div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
        {children}
      </div>
    </div>
  );
}

export function VerifyEmail({ token, onDone }) {
  const [state, setState] = useState("loading"); // loading | ok | error

  useEffect(() => {
    api
      .verifyEmail(token)
      .then(() => setState("ok"))
      .catch(() => setState("error"))
      .finally(() => clearParam("verify"));
  }, [token]);

  return (
    <AuthCard title="Verifica email">
      {state === "loading" && <p className="sub">Conferma in corso…</p>}
      {state === "ok" && (
        <>
          <div className="wpai-success">Email confermata! Ora puoi accedere.</div>
          <button className="wpai-btn full" onClick={onDone}>Vai al login</button>
        </>
      )}
      {state === "error" && (
        <>
          <div className="wpai-error">Link non valido o scaduto.</div>
          <button className="wpai-btn full" onClick={onDone}>Torna al login</button>
        </>
      )}
    </AuthCard>
  );
}

export function ResetPassword({ token, onDone }) {
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    const data = new FormData(e.target);
    const pw = data.get("password");
    if (pw !== data.get("confirm")) return setError("Le password non coincidono.");
    if (pw.length < 8) return setError("La password deve avere almeno 8 caratteri.");
    try {
      await api.resetPassword(token, pw);
      clearParam("reset");
      setDone(true);
    } catch {
      setError("Link non valido o scaduto. Richiedine uno nuovo.");
    }
  };

  if (done) {
    return (
      <AuthCard title="Password aggiornata">
        <div className="wpai-success">Password reimpostata con successo.</div>
        <button className="wpai-btn full" onClick={onDone}>Vai al login</button>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Nuova password" sub="Scegli una nuova password per il tuo account.">
      <form onSubmit={submit}>
        {error && <div className="wpai-error">{error}</div>}
        <div className="wpai-field">
          <label htmlFor="reset-pw">Nuova password</label>
          <input id="reset-pw" name="password" type="password" placeholder="••••••••" autoFocus required />
        </div>
        <div className="wpai-field">
          <label htmlFor="reset-confirm">Conferma password</label>
          <input id="reset-confirm" name="confirm" type="password" placeholder="••••••••" required />
        </div>
        <button className="wpai-btn full" type="submit">Reimposta password</button>
      </form>
    </AuthCard>
  );
}

export function ForgotPassword({ onBack }) {
  const [sent, setSent] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    const email = new FormData(e.target).get("email");
    // backend always returns ok (no user enumeration); show the same confirmation regardless
    await api.forgotPassword(email).catch(() => {});
    setSent(true);
  };

  return (
    <AuthCard
      title="Password dimenticata"
      sub={sent ? null : "Ti invieremo un link per reimpostare la password."}
    >
      {sent ? (
        <>
          <div className="wpai-success">
            Se l'email è registrata, riceverai a breve un link per reimpostare la password.
          </div>
          <button className="wpai-btn full" onClick={onBack}>Torna al login</button>
        </>
      ) : (
        <form onSubmit={submit}>
          <div className="wpai-field">
            <label htmlFor="forgot-email">Email</label>
            <input id="forgot-email" name="email" type="email" placeholder="operatore@azienda.it" autoFocus required />
          </div>
          <button className="wpai-btn full" type="submit">Invia link</button>
          <p className="sub" style={{ marginTop: 14, textAlign: "center" }}>
            <a href="#" onClick={(e) => { e.preventDefault(); onBack(); }}>Torna al login</a>
          </p>
        </form>
      )}
    </AuthCard>
  );
}
