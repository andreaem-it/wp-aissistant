import { useEffect, useRef } from "react";
import { mount } from "@wp-aissistant/widget/widget";
import "@wp-aissistant/widget/styles.css";

import { api } from "./api.js";

const BACKEND = import.meta.env.VITE_API_BASE || "http://localhost:8000";
// La chiave **pubblica** del nostro tenant, la stessa che sta nel widget del nostro sito. È
// pubblica per costruzione: identifica chi risponde, non autorizza niente. Di chi si parla lo
// dice il token di contesto, che è firmato e non passa mai di qui.
const ASSISTANT_KEY = import.meta.env.VITE_ASSISTANT_API_KEY || "";

// Il tema già risolto che il pannello stampa su <html> (mai "auto": vedi theme.js). Leggerlo di
// lì invece di ricalcolarlo evita che pannello e widget rispondano a due fonti diverse e finiscano
// per un attimo di temi diversi.
function temaCorrente() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

/**
 * La nostra assistenza, dentro il pannello del cliente.
 *
 * È il **widget vero**: lo stesso artefatto che diamo ai clienti, importato dal workspace invece
 * che dal CDN. Non è pigrizia — è la stessa ragione per cui l'anteprima del configuratore monta
 * il widget e non un facsimile. Se qui si comporta male, si comporta male anche sui loro siti.
 *
 * Dal workspace e non dal CDN, deliberatamente: questa è una pagina autenticata, il bundle è già
 * nel nostro build, e dipendere da un dominio esterno significherebbe che un problema al CDN
 * toglie l'assistenza proprio a chi sta cercando di risolvere un problema.
 *
 * **Due tenant in gioco.** A rispondere siamo noi, con la nostra knowledge base; l'argomento è il
 * cliente loggato. Il secondo non viaggia da qui: il browser manda solo un token firmato di 5
 * minuti, e i fatti li rilegge il backend dal database. Vedi `app/panel_assistant.py`.
 *
 * Senza `VITE_ASSISTANT_API_KEY` non monta niente. È la configurazione che accende la funzione,
 * e mancante deve lasciare il pannello identico a prima — non un launcher che apre una chat
 * verso un tenant che non esiste.
 */
export default function Assistant({ email }) {
  const instance = useRef(null);
  // Il token vale 5 minuti e una conversazione dura di più: si tiene finché è fresco e si
  // richiede quando sta per scadere, invece di chiederne uno per ogni messaggio.
  const cached = useRef({ token: "", scade: 0 });

  useEffect(() => {
    if (!ASSISTANT_KEY) return undefined;

    async function chatHeaders() {
      const adesso = Date.now();
      if (cached.current.token && adesso < cached.current.scade) {
        return { "X-Panel-Assistant-Token": cached.current.token };
      }
      try {
        const res = await api.assistantToken();
        // Un margine di 30 secondi: un token che scade mentre la richiesta è in volo arriva
        // scaduto, e il contesto sparirebbe a metà conversazione senza che nulla lo dica.
        //
        // Il fondo è **zero**, non 30: se il backend accorciasse la durata sotto il margine, un
        // minimo di 30 secondi terrebbe in cache un token già scaduto — cioè trasformerebbe una
        // misura di prudenza nel difetto da cui protegge. Sotto il margine non si tiene niente e
        // se ne chiede uno per messaggio, che è lento ma corretto.
        cached.current = {
          token: res.token,
          scade: adesso + Math.max((res.expires_in || 300) - 30, 0) * 1000,
        };
        return { "X-Panel-Assistant-Token": res.token };
      } catch (error) {
        // 503 = segreto di firma non configurato, cioè funzione spenta lato server. L'assistente
        // resta utile lo stesso: risponde dalla documentazione, solo senza sapere nulla di questo
        // account. Nessun errore in faccia a chi sta già chiedendo aiuto per altro.
        return {};
      }
    }

    instance.current = mount({
      backendUrl: BACKEND,
      apiKey: ASSISTANT_KEY,
      locale: "it-IT",
      appearance: { theme: temaCorrente() },
      title: "Assistenza WP AIssistant",
      subtitle: "Rispondiamo noi, di solito subito",
      welcome:
        "Ciao! Posso aiutarti con l'installazione, i domini, la knowledge base e "
        + "l'abbonamento. Cosa non torna?",
      contactEmail: email || "",
      host: {
        siteUrl: window.location.origin,
        chatHeaders,
      },
    });

    // Il tema si può cambiare a chat aperta. Rimontare il widget la chiuderebbe e perderebbe
    // quello che l'utente ha scritto, quindi si scambia la sola classe sulla radice — la stessa
    // che il widget si mette da solo al montaggio.
    const osservatore = new MutationObserver(() => {
      const root = document.getElementById("wpai-root");
      if (!root) return;
      root.classList.toggle("wpai-theme-dark", temaCorrente() === "dark");
      root.classList.toggle("wpai-theme-light", temaCorrente() !== "dark");
    });
    osservatore.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      osservatore.disconnect();
      instance.current?.destroy();
      instance.current = null;
    };
  }, [email]);

  // Il launcher lo disegna il widget in fondo alla pagina: qui non c'è markup da rendere. Il
  // componente esiste per il ciclo di vita, non per l'albero.
  return null;
}
