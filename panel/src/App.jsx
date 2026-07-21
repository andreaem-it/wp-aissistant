import { useState } from "react";
import { getToken, setToken, clearToken, api } from "./api.js";
import Conversations from "./Conversations.jsx";
import Tickets from "./Tickets.jsx";
import Upload from "./Upload.jsx";
import Stats from "./Stats.jsx";

const TABS = [
  { key: "conversations", label: "Chat", icon: "💬", Component: Conversations },
  { key: "tickets", label: "Ticket", icon: "🎫", Component: Tickets },
  { key: "upload", label: "Knowledge base", icon: "📄", Component: Upload },
  { key: "stats", label: "Statistiche", icon: "📊", Component: Stats },
];

export default function App() {
  const [token, setTokenState] = useState(getToken());
  const [tab, setTab] = useState("conversations");
  const [error, setError] = useState("");

  if (!token) {
    return (
      <div className="wpai-login">
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const data = new FormData(e.target);
            try {
              const { token } = await api.login(data.get("email"), data.get("password"));
              setToken(token);
              setTokenState(token);
              setError("");
            } catch {
              setError("Credenziali non valide");
            }
          }}
        >
          <h2>WP AIssistant</h2>
          <input name="email" type="email" placeholder="Email operatore" autoFocus />
          <input name="password" type="password" placeholder="Password" />
          <button className="wpai-btn" type="submit">Entra</button>
          {error && <p style={{ color: "#c0392b", margin: "8px 0 0" }}>{error}</p>}
        </form>
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

  const Active = TABS.find((t) => t.key === tab).Component;
  return (
    <div className="wpai-app">
      <nav className="wpai-sidebar">
        <div className="wpai-brand">WP AIssistant</div>
        {TABS.map((t) => (
          <button
            key={t.key}
            className={"wpai-nav-item" + (t.key === tab ? " active" : "")}
            onClick={() => setTab(t.key)}
          >
            <span>{t.icon}</span> {t.label}
          </button>
        ))}
        <button className="wpai-nav-item" style={{ marginTop: "auto" }} onClick={logout}>
          <span>🚪</span> Esci
        </button>
      </nav>
      <main className="wpai-main">
        <Active />
      </main>
    </div>
  );
}
