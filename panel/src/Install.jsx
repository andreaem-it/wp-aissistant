import { useCallback, useEffect, useRef, useState } from "react";
import { Boxes, Code2, Copy, Check, Download, RefreshCw, TriangleAlert } from "lucide-react";
import { mount } from "@wp-aissistant/widget/widget";
import "@wp-aissistant/widget/styles.css";

import { api } from "./api.js";
import Loading from "./Loading.jsx";
import { errorMessage } from "./licence.js";
import { buildSnippet, siteFor } from "./snippet.js";

const BACKEND = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const CDN = import.meta.env.VITE_WIDGET_CDN || "https://cdn.wpaissistant.it";
const WIDGET_VERSION = import.meta.env.VITE_WIDGET_VERSION || "0.1.0";
const PLUGIN_DOWNLOAD = import.meta.env.VITE_PLUGIN_DOWNLOAD || "";

/**
 * Come si installa il widget: plugin WordPress o JavaScript.
 *
 * Le due strade producono **lo stesso oggetto di opzioni** e caricano **lo stesso artefatto**:
 * è il motivo per cui il widget è stato estratto dal plugin. Qui cambia solo chi scrive le
 * opzioni — la pagina delle impostazioni di WordPress o questa schermata.
 */
export default function Install() {
  const [choice, setChoice] = useState("wordpress");
  const [state, setState] = useState({ loading: true, error: "" });
  const [data, setData] = useState(null);
  const [account, setAccount] = useState(null);
  const [origins, setOrigins] = useState([]);
  const [draft, setDraft] = useState(null);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState({ error: "", ok: "" });

  const load = useCallback(() => {
    setState({ loading: true, error: "" });
    Promise.all([api.widgetConfig(), api.me(), api.origins()])
      .then(([config, me, domains]) => {
        setData(config);
        setAccount(me);
        setOrigins(domains.origins || []);
        setDraft(config.config);
        setState({ loading: false, error: "" });
      })
      .catch((error) => setState({
        loading: false,
        error: errorMessage(error, "Non è stato possibile caricare la configurazione."),
      }));
  }, []);

  useEffect(() => { load(); }, [load]);

  if (state.loading) return <Loading label="Caricamento…" />;
  if (state.error) {
    return (
      <div className="wpai-card">
        <p role="alert" className="wpai-error">{state.error}</p>
        <button className="wpai-btn" type="button" onClick={load}>
          <RefreshCw size={14} /> Riprova
        </button>
      </div>
    );
  }

  const site = siteFor(origins);
  const vocabulary = data.vocabulary;

  const save = async () => {
    setSaving(true);
    setFeedback({ error: "", ok: "" });
    try {
      const saved = await api.saveWidgetConfig(draft);
      setData({ ...data, config: saved.config, configured: true });
      setDraft(saved.config);
      setFeedback({ error: "", ok: "Salvato. Ricopia lo snippet nel sito per applicarlo." });
    } catch (error) {
      setFeedback({ error: errorMessage(error), ok: "" });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="wpai-card">
        <div className="wpai-card-title">Come vuoi installare l'assistente?</div>
        <div className="wpai-choice" role="radiogroup" aria-label="Modo di installazione">
          <ChoiceCard
            active={choice === "wordpress"}
            onSelect={() => setChoice("wordpress")}
            Icon={Boxes}
            title="Plugin WordPress"
            description="Un plugin da installare. Aggiunge le schede prodotto WooCommerce, il carrello e la ricerca ordini."
          />
          <ChoiceCard
            active={choice === "javascript"}
            onSelect={() => setChoice("javascript")}
            Icon={Code2}
            title="Integrazione JavaScript"
            description="Due righe da incollare in qualunque sito. Nessun plugin, nessuna piattaforma richiesta."
          />
        </div>
      </div>

      {!site && (
        <div className="wpai-card">
          <p role="alert" className="wpai-error" style={{ margin: 0 }}>
            <TriangleAlert size={14} aria-hidden="true" /> Nessun dominio di produzione registrato:
            il widget non parte da nessuna parte. Registralo in <strong>Siti e licenza</strong>
            prima di installare.
          </p>
        </div>
      )}

      {choice === "wordpress"
        ? <WordPressInstall apiKey={account?.api_key} />
        : (
          <JavaScriptInstall
            apiKey={account?.api_key}
            site={site}
            vocabulary={vocabulary}
            draft={draft}
            setDraft={setDraft}
            save={save}
            saving={saving}
            feedback={feedback}
          />
        )}
    </>
  );
}

function ChoiceCard({ active, onSelect, Icon, title, description }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={active}
      className={"wpai-choice-card" + (active ? " active" : "")}
      onClick={onSelect}
    >
      <Icon size={18} aria-hidden="true" />
      <strong>{title}</strong>
      <span>{description}</span>
    </button>
  );
}

function WordPressInstall({ apiKey }) {
  return (
    <div className="wpai-card">
      <div className="wpai-card-title"><Boxes size={15} /> Plugin WordPress</div>
      <ol className="wpai-steps">
        <li>
          {PLUGIN_DOWNLOAD
            ? <a className="wpai-btn" href={PLUGIN_DOWNLOAD}><Download size={14} /> Scarica il plugin</a>
            : <span>Scarica il plugin dal collegamento che ti abbiamo inviato.</span>}
        </li>
        <li>In WordPress: <em>Plugin → Aggiungi nuovo → Carica plugin</em>, poi attiva.</li>
        <li>
          Incolla la chiave in <em>AI Assistant → Impostazioni</em>:
          <CopyField label="Chiave pubblica" value={apiKey || ""} />
        </li>
        <li>
          L'aspetto si configura dalla pagina del plugin. Il dominio del sito viene registrato da
          solo alla prima connessione: il plugin dimostra di essere su quel sito, e non serve che
          tu faccia altro.
        </li>
      </ol>
    </div>
  );
}

function JavaScriptInstall({ apiKey, site, vocabulary, draft, setDraft, save, saving, feedback }) {
  const snippet = buildSnippet({
    apiKey,
    backendUrl: BACKEND,
    site,
    cdnUrl: CDN,
    version: WIDGET_VERSION,
    appearance: draft?.appearance,
    texts: draft?.texts,
    defaults: vocabulary,
  });

  const setAppearance = (name, value) =>
    setDraft({ ...draft, appearance: { ...draft.appearance, [name]: value } });
  const setText = (name, value) =>
    setDraft({ ...draft, texts: { ...draft.texts, [name]: value } });

  return (
    <>
      <div className="wpai-card">
        <div className="wpai-card-title"><Code2 size={15} /> Aspetto</div>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
          Le opzioni e i valori ammessi arrivano dal backend: quello che vedi qui è esattamente
          ciò che il widget sa fare, senza una seconda lista che può divergere.
        </p>
        <div className="wpai-config-grid">
          {Object.entries(vocabulary.appearance).map(([name, spec]) => (
            <label key={name} style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
              {LABELS[name] || name}
              <select
                value={draft.appearance[name]}
                onChange={(e) => setAppearance(name, e.target.value)}
              >
                {spec.values.map((value) => (
                  <option key={value} value={value}>{VALUE_LABELS[value] || value}</option>
                ))}
              </select>
            </label>
          ))}
          <label style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
            Colore
            <input
              type="color"
              value={draft.appearance.color}
              onChange={(e) => setAppearance("color", e.target.value)}
            />
          </label>
          {Object.keys(vocabulary.flags).map((name) => (
            <label key={name} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5 }}>
              <input
                type="checkbox"
                checked={Boolean(draft.appearance[name])}
                onChange={(e) => setAppearance(name, e.target.checked)}
              />
              {LABELS[name] || name}
            </label>
          ))}
        </div>
      </div>

      <div className="wpai-card">
        <div className="wpai-card-title">Testi</div>
        <div className="wpai-config-grid">
          {Object.entries(vocabulary.textLimits).map(([name, limit]) => (
            <label key={name} style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
              {LABELS[name] || name} <span style={{ color: "var(--text-muted)" }}>(max {limit})</span>
              <input
                type="text"
                maxLength={limit}
                value={draft.texts[name] || ""}
                onChange={(e) => setText(name, e.target.value)}
              />
            </label>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "center" }}>
          <button className="wpai-btn" type="button" onClick={save} disabled={saving}>
            {saving ? "Salvataggio…" : "Salva"}
          </button>
          {feedback.error && <span role="alert" style={{ color: "var(--red)", fontSize: 12.5 }}>{feedback.error}</span>}
          {feedback.ok && <span role="status" style={{ color: "var(--text-muted)", fontSize: 12.5 }}>{feedback.ok}</span>}
        </div>
      </div>

      <Preview appearance={draft.appearance} texts={draft.texts} />

      <div className="wpai-card">
        <div className="wpai-card-title">Il tuo snippet</div>
        <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 12px" }}>
          Incollalo prima di <code>&lt;/body&gt;</code>. Contiene le opzioni in chiaro: se le
          cambi qui, <strong>ricopialo</strong> — il sito continua altrimenti con quelle vecchie.
        </p>
        <CopyField label="Snippet" value={snippet} multiline />
      </div>
    </>
  );
}

/**
 * L'anteprima monta il **widget vero**, non un facsimile: stesso codice, stesso CSS, stesso
 * vocabolario. È l'argomento per cui questa schermata viene dopo l'estrazione del widget — un
 * facsimile diverge il giorno dopo, e mostrerebbe al cliente qualcosa che il suo sito non fa.
 *
 * In modalità anteprima il widget disegna tutto e non chiama niente: senza, ogni sguardo a
 * questa pagina aprirebbe una conversazione vera nell'inbox e la conterebbe nelle statistiche.
 */
function Preview({ appearance, texts }) {
  const holder = useRef(null);
  const instance = useRef(null);

  useEffect(() => {
    instance.current?.destroy();
    instance.current = mount({
      backendUrl: BACKEND,
      apiKey: "preview",
      preview: true,
      locale: "it-IT",
      appearance,
      title: texts.title || "Assistenza",
      subtitle: texts.subtitle || "Di solito risponde subito",
      welcome: texts.welcome || "Ciao! Come posso aiutarti oggi?",
      aiDisclosure: texts.aiDisclosure || "",
      launcherLabel: texts.launcherLabel || "",
      inputPlaceholder: texts.inputPlaceholder || "",
      host: {},
    });
    return () => {
      instance.current?.destroy();
      instance.current = null;
    };
  }, [appearance, texts]);

  return (
    <div className="wpai-card">
      <div className="wpai-card-title">Anteprima</div>
      <p style={{ fontSize: 12.5, color: "var(--text-muted)", margin: "6px 0 0" }}>
        È il widget vero, con la chat disattivata. Compare in basso in questa pagina, dove
        comparirà sul tuo sito.
      </p>
      <div ref={holder} />
    </div>
  );
}

function CopyField({ label, value, multiline }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      setCopied(false); // niente conferma se la copia non è avvenuta davvero
    }
  };

  return (
    <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
      <label className="wpai-sr-only" htmlFor={`copy-${label}`}>{label}</label>
      {multiline
        ? <textarea id={`copy-${label}`} readOnly value={value} rows={10} style={{ fontFamily: "monospace", fontSize: 12 }} />
        : <input id={`copy-${label}`} readOnly value={value} style={{ fontFamily: "monospace" }} />}
      <div>
        <button className="wpai-btn" type="button" onClick={copy}>
          {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? "Copiato" : "Copia"}
        </button>
      </div>
    </div>
  );
}

const LABELS = {
  theme: "Tema", position: "Posizione", motion: "Animazioni", launcherStyle: "Stile del pulsante",
  launcherIcon: "Icona", launcherSize: "Dimensione del pulsante", windowStyle: "Stile della finestra",
  windowSize: "Dimensione della finestra", headerStyle: "Intestazione", cornerStyle: "Angoli",
  fontSize: "Testo", showAvatar: "Mostra l'avatar", showStatus: "Mostra il sottotitolo",
  title: "Titolo", subtitle: "Sottotitolo", welcome: "Messaggio di benvenuto",
  aiDisclosure: "Avviso sull'AI", launcherLabel: "Etichetta del pulsante",
  inputPlaceholder: "Testo del campo", privacyUrl: "Link alla privacy", image: "Avatar (URL)",
};

const VALUE_LABELS = {
  light: "Chiaro", dark: "Scuro", auto: "Automatico",
  right: "A destra", left: "A sinistra",
  subtle: "Discrete", playful: "Vivaci", none: "Nessuna",
  small: "Piccolo", standard: "Normale", large: "Grande",
  compact: "Compatta", soft: "Morbida", flat: "Piatta", glass: "Vetro",
  bubble: "Bolla", pill: "Pillola", square: "Quadrato", outline: "Contorno",
  tint: "Colorata", solid: "Piena", minimal: "Minimale", rounded: "Arrotondati",
};
