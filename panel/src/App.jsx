import { useEffect, useState } from "react";
import { MessageSquare, Ticket as TicketIcon, FileText, BarChart3, LogOut } from "lucide-react";
import { getToken, setToken, clearToken, getEmail, setEmail, api } from "./api.js";
import Conversations from "./Conversations.jsx";
import Tickets from "./Tickets.jsx";
import Upload from "./Upload.jsx";
import Stats from "./Stats.jsx";
import Profile from "./Profile.jsx";
import Signup from "./Signup.jsx";

const TABS = [
  { key: "conversations", label: "Chat", Icon: MessageSquare, Component: Conversations },
  { key: "tickets", label: "Ticket", Icon: TicketIcon, Component: Tickets },
  { key: "upload", label: "Knowledge base", Icon: FileText, Component: Upload },
  { key: "stats", label: "Statistiche", Icon: BarChart3, Component: Stats },
];

const PROFILE_TAB = { key: "profile", Component: Profile };

function Brand() {
  return (
    <div className="wpai-brand">
      <div className="wpai-brand-mark" />
      <div className="wpai-brand-name">
        <span className="dim">WP</span> AIssistant
      </div>
    </div>
  );
}

const initialAuthMode = () =>
  new URLSearchParams(window.location.search).has("signup") ? "signup" : "login";

export default function App() {
  const [token, setTokenState] = useState(getToken());
  const [authMode, setAuthMode] = useState(initialAuthMode);
  const [tab, setTab] = useState("conversations");
  const [error, setError] = useState("");
  const [openTickets, setOpenTickets] = useState(0);

  useEffect(() => {
    if (!token) return;
    const refresh = () => api.tickets("open").then((items) => setOpenTickets(items.length)).catch(() => {});
    refresh();
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [token, tab]);

  if (!token) {
    const isSignup = authMode === "signup";
    return (
      <div className="wpai-login">
        <div className="wpai-login-card">
          <Brand />
          <h1>{isSignup ? "Crea il tuo account" : "Accedi al pannello"}</h1>
          <p className="sub">
            {isSignup
              ? "Attiva l'assistente AI sul tuo sito in pochi minuti."
              : "Gestisci conversazioni, ticket e knowledge base."}
          </p>
          {isSignup ? (
            <Signup onBackToLogin={() => { setAuthMode("login"); setError(""); }} />
          ) : (
            <>
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  const data = new FormData(e.target);
                  const email = data.get("email");
                  try {
                    const { token } = await api.login(email, data.get("password"));
                    setToken(token);
                    setEmail(email);
                    setTokenState(token);
                    setError("");
                  } catch {
                    setError("Credenziali non valide.");
                  }
                }}
              >
                {error && <div className="wpai-error">{error}</div>}
                <div className="wpai-field">
                  <label htmlFor="wpai-email">Email</label>
                  <input id="wpai-email" name="email" type="email" placeholder="operatore@azienda.it" autoFocus required />
                </div>
                <div className="wpai-field">
                  <label htmlFor="wpai-password">Password</label>
                  <input id="wpai-password" name="password" type="password" placeholder="••••••••" required />
                </div>
                <button className="wpai-btn full" type="submit">Entra</button>
              </form>
              <p className="sub" style={{ marginTop: 14, textAlign: "center" }}>
                Non hai un account?{" "}
                <a href="#" onClick={(e) => { e.preventDefault(); setAuthMode("signup"); setError(""); }}>
                  Registrati
                </a>
              </p>
            </>
          )}
        </div>
      </div>
    );
  }

  const logout = async () => {
    try {
      await api.logout();
    } catch {
      // ignore: we clear the local token regardless
    }
    clearToken();
    setTokenState("");
  };

  const email = getEmail();
  const initials = email ? email.slice(0, 2).toUpperCase() : "?";
  const Active = (tab === "profile" ? PROFILE_TAB : TABS.find((t) => t.key === tab)).Component;

  return (
    <div className="wpai-app">
      <nav className="wpai-sidebar">
        <Brand />
        <div className="wpai-nav">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={"wpai-nav-item" + (t.key === tab ? " active" : "")}
              onClick={() => setTab(t.key)}
            >
              <t.Icon size={17} strokeWidth={2.25} />
              {t.label}
              {t.key === "tickets" && openTickets > 0 && (
                <span className="wpai-nav-count">{openTickets}</span>
              )}
            </button>
          ))}
        </div>
        <div className={"wpai-sidebar-footer" + (tab === "profile" ? " active" : "")}>
          <button className="wpai-footer-profile" onClick={() => setTab("profile")}>
            <div className="wpai-avatar">{initials}</div>
            <div className="wpai-sidebar-email">{email}</div>
          </button>
          <button className="wpai-icon-btn" onClick={logout} title="Esci" aria-label="Esci">
            <LogOut size={16} strokeWidth={2.25} />
          </button>
        </div>
      </nav>
      <main className="wpai-main">
        <Active />
      </main>
    </div>
  );
}
