import { useState } from "react";
import { getApiKey, setApiKey } from "./api.js";
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
  const [apiKey, setApiKeyState] = useState(getApiKey());
  const [tab, setTab] = useState("conversations");

  if (!apiKey) {
    return (
      <div className="wpai-login">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const key = new FormData(e.target).get("key");
            setApiKey(key);
            setApiKeyState(key);
          }}
        >
          <h2>WP AIssistant</h2>
          <input name="key" placeholder="API key cliente" autoFocus />
          <button className="wpai-btn" type="submit">Entra</button>
        </form>
      </div>
    );
  }

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
      </nav>
      <main className="wpai-main">
        <Active />
      </main>
    </div>
  );
}
