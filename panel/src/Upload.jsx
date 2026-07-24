import { useEffect, useState } from "react";
import { UploadCloud, CheckCircle2, XCircle, Loader2, FileText, Globe, Package, Inbox } from "lucide-react";
import { api } from "./api.js";

function sourceLabel(source, ref) {
  if (source === "document") return ref;
  try {
    const url = new URL(ref);
    return url.pathname === "/" || url.hash === "#site-info" ? url.hostname : url.pathname;
  } catch {
    return ref;
  }
}

export default function Upload() {
  const [state, setState] = useState({ kind: "idle" });
  const [kb, setKb] = useState(null);

  const loadKb = () => api.knowledgeBase().then(setKb);
  useEffect(() => { loadKb(); }, []);

  const onUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setState({ kind: "loading" });
    try {
      const res = await api.uploadDocument(file);
      setState({ kind: "done", text: `"${file.name}" caricato — ${res.chars} caratteri estratti.` });
      loadKb();
      setTimeout(loadKb, 3000); // catch it once the background job finishes embedding
    } catch (err) {
      setState({ kind: "error", text: `Caricamento fallito: ${err.message}` });
    }
  };

  return (
    <div>
      <h1 className="wpai-page-title">Knowledge base</h1>
      <label className="wpai-dropzone">
        <input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={onUpload} style={{ display: "none" }} />
        <UploadCloud size={28} strokeWidth={1.5} />
        <span className="title">Clicca per caricare un documento</span>
        <span className="hint">PDF, immagine (OCR) o file di testo</span>
      </label>
      {state.kind !== "idle" && (
        <div className="wpai-status-line">
          {state.kind === "loading" && <Loader2 size={15} className="wpai-spin" />}
          {state.kind === "done" && <CheckCircle2 size={15} color="var(--green)" />}
          {state.kind === "error" && <XCircle size={15} color="var(--red)" />}
          {state.kind === "loading" ? "Caricamento in corso…" : state.text}
        </div>
      )}

      {kb && (kb.documents.length > 0 || kb.products.length > 0) ? (
        <>
          {kb.documents.length > 0 && (
            <div style={{ marginTop: 28 }}>
              <h2 className="wpai-section-title">Contenuti sincronizzati ({kb.documents.length})</h2>
              <div className="wpai-kb-list">
                {kb.documents.map((d) => (
                  <div key={d.source_ref} className="wpai-kb-row">
                    {d.source === "document" ? <FileText size={15} strokeWidth={2} /> : <Globe size={15} strokeWidth={2} />}
                    <span className="wpai-kb-label" title={d.source_ref}>{sourceLabel(d.source, d.source_ref)}</span>
                    <span className="wpai-kb-count">{d.chunks} {d.chunks === 1 ? "chunk" : "chunk"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {kb.products.length > 0 && (
            <div style={{ marginTop: 28 }}>
              <h2 className="wpai-section-title"><Package size={15} strokeWidth={2} /> Prodotti ({kb.products.length})</h2>
              <div className="wpai-kb-products">
                {kb.products.map((p) => (
                  <a key={p.product_url} href={p.product_url} target="_blank" rel="noopener noreferrer" className="wpai-kb-product">
                    {p.image_url ? <img src={p.image_url} alt="" /> : <div className="wpai-kb-product-placeholder"><Package size={16} /></div>}
                    <div>
                      <div className="wpai-kb-product-title">{p.title}</div>
                      {p.price && <div className="wpai-kb-product-price">{p.price} €</div>}
                    </div>
                  </a>
                ))}
              </div>
            </div>
          )}
        </>
      ) : kb ? (
        <div className="wpai-empty" style={{ marginTop: 20 }}>
          <Inbox size={28} strokeWidth={1.5} />
          <p>Nessun contenuto sincronizzato ancora. Carica un documento qui sopra, oppure usa "Sincronizza ora" nel plugin WordPress.</p>
        </div>
      ) : null}
    </div>
  );
}
