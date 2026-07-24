import { useState } from "react";
import { UploadCloud, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { api } from "./api.js";

export default function Upload() {
  const [state, setState] = useState({ kind: "idle" });

  const onUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setState({ kind: "loading" });
    try {
      const res = await api.uploadDocument(file);
      setState({ kind: "done", text: `"${file.name}" caricato — ${res.chars} caratteri estratti.` });
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
    </div>
  );
}
