import { useState } from "react";
import { api } from "./api.js";

export default function Upload() {
  const [status, setStatus] = useState("");

  const onUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setStatus("caricamento...");
    try {
      const res = await api.uploadDocument(file);
      setStatus(`"${file.name}" caricato — ${res.chars} caratteri estratti.`);
    } catch (err) {
      setStatus(`errore: ${err.message}`);
    }
  };

  return (
    <div>
      <h1>Knowledge base</h1>
      <label className="wpai-dropzone" style={{ display: "block", cursor: "pointer" }}>
        <input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" onChange={onUpload} style={{ display: "none" }} />
        📄 Clicca per caricare un documento (PDF, immagine o testo)
      </label>
      {status && <p style={{ marginTop: 12 }}>{status}</p>}
    </div>
  );
}
