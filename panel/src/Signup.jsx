import { useEffect, useState } from "react";
import { api } from "./api.js";

export default function Signup({ onBackToLogin }) {
  const [plans, setPlans] = useState(null);
  const [form, setForm] = useState({ company: "", email: "", password: "", plan_id: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .publicPlans()
      .then((ps) => {
        setPlans(ps);
        if (ps[0]) setForm((f) => ({ ...f, plan_id: String(ps[0].id) }));
      })
      .catch(() => setPlans([]));
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    if (form.password.length < 8) {
      setError("La password deve avere almeno 8 caratteri.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const { checkout_url } = await api.signup({
        company_name: form.company,
        email: form.email,
        password: form.password,
        plan_id: Number(form.plan_id),
      });
      window.location.href = checkout_url; // -> Stripe Checkout (card + free trial)
    } catch (err) {
      setBusy(false);
      const msg = String(err.message || "");
      if (msg.includes("409")) setError("Email già registrata — accedi.");
      else if (msg.includes("503")) setError("Le registrazioni non sono al momento disponibili.");
      else setError("Registrazione non riuscita. Riprova.");
    }
  };

  if (plans !== null && plans.length === 0) {
    return (
      <>
        <div className="wpai-error">Le registrazioni non sono al momento disponibili.</div>
        <p className="sub" style={{ marginTop: 12, textAlign: "center" }}>
          <a href="#" onClick={(e) => { e.preventDefault(); onBackToLogin(); }}>Torna al login</a>
        </p>
      </>
    );
  }

  return (
    <form onSubmit={submit}>
      {error && <div className="wpai-error">{error}</div>}
      <div className="wpai-field">
        <label htmlFor="su-company">Nome azienda</label>
        <input id="su-company" value={form.company} onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))} required autoFocus />
      </div>
      <div className="wpai-field">
        <label htmlFor="su-email">Email</label>
        <input id="su-email" type="email" placeholder="tu@azienda.it" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} required />
      </div>
      <div className="wpai-field">
        <label htmlFor="su-password">Password</label>
        <input id="su-password" type="password" placeholder="almeno 8 caratteri" minLength={8} value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} required />
      </div>
      {plans && plans.length > 0 && (
        <div className="wpai-field">
          <label htmlFor="su-plan">Piano</label>
          <select id="su-plan" value={form.plan_id} onChange={(e) => setForm((f) => ({ ...f, plan_id: e.target.value }))}>
            {plans.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {(p.price_cents / 100).toFixed(2)} {p.currency.toUpperCase()}/mese
              </option>
            ))}
          </select>
        </div>
      )}
      <button className="wpai-btn full" type="submit" disabled={busy || plans === null}>
        {busy ? "Reindirizzamento…" : "Inizia la prova gratuita"}
      </button>
      <p className="sub" style={{ marginTop: 6, textAlign: "center", fontSize: 12.5 }}>
        14 giorni gratis · carta richiesta · nessun addebito durante la prova
      </p>
      <p className="sub" style={{ marginTop: 12, textAlign: "center" }}>
        Hai già un account? <a href="#" onClick={(e) => { e.preventDefault(); onBackToLogin(); }}>Accedi</a>
      </p>
    </form>
  );
}
