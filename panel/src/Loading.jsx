import { Loader2 } from "lucide-react";

/**
 * Indicatore di caricamento.
 *
 * `full` (predefinito) occupa l'area della vista e centra lo spinner: è il caso in cui non c'è
 * ancora nulla da mostrare. `inline` sta dentro una scheda accanto a contenuto già visibile e
 * resta discreto.
 *
 * Il testo non sparisce, diventa invisibile: `role="status"` più l'etichetta per i lettori di
 * schermo, altrimenti sostituire una parola con un'icona toglierebbe l'informazione a chi non
 * la vede. E sotto `prefers-reduced-motion` il testo torna visibile al posto dell'icona — con
 * le animazioni disattivate uno spinner fermo sembra un'interfaccia bloccata, non un'attesa.
 */
export default function Loading({ inline = false, label = "Caricamento…" }) {
  return (
    <div className={"wpai-loading" + (inline ? " inline" : "")} role="status" aria-live="polite">
      <Loader2 size={inline ? 15 : 22} strokeWidth={2.25} className="wpai-spin" aria-hidden="true" />
      <span className="wpai-loading-label">{label}</span>
    </div>
  );
}
