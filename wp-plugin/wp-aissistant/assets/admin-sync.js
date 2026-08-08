/* Realtime item-by-item content sync for the "Sincronizzazione" admin page.
   Fetches the list of items, then pushes each to the backend and polls its ingest job
   status, updating a live list. Sequential (naturally paces the per-minute ingest limit). */
(function () {
  function ajax(params) {
    return fetch(WPAI_SYNC.ajaxUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(Object.assign({ _ajax_nonce: WPAI_SYNC.nonce }, params)),
    }).then((r) => r.json());
  }

  function setRow(row, statusText, cls, icon) {
    // built via DOM, not innerHTML: statusText can carry a backend error message verbatim
    row.className = "wpai-sync-row" + (cls ? " " + cls : "");
    const el = row.querySelector(".status");
    el.textContent = "";
    if (icon) {
      const i = document.createElement("i");
      i.className = "fa-solid " + icon;
      el.appendChild(i);
      el.appendChild(document.createTextNode(" "));
    }
    el.appendChild(document.createTextNode(statusText));
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Segue i job di una riga finché non sono tutti finiti (o si rinuncia dopo ~30s).
  //
  // Un prodotto ne produce due, scheda e testo: la riga è "sincronizzato" solo quando lo sono
  // entrambi, e l'errore di uno solo è l'errore della riga. Prima se ne osservava uno, quindi
  // metà del prodotto poteva mancare sotto una spunta verde.
  //
  // Torna true se la riga è a posto, così il conteggio finale non annovera fra i sincronizzati
  // ciò che è fallito sotto gli occhi di chi guarda.
  async function waitForJobs(jobIds, row) {
    const pending = new Set(jobIds);
    let latest = "in coda…";
    for (let i = 0; i < 20 && pending.size; i++) {
      await sleep(1500);
      for (const jobId of Array.from(pending)) {
        let res;
        try {
          res = await ajax({ action: "wpai_job_status", job_id: jobId });
        } catch (e) {
          continue;
        }
        if (!res || !res.success) continue;
        const status = res.data.status;
        if (status === "done") { pending.delete(jobId); continue; }
        if (status === "error") {
          setRow(row, "errore: " + (res.data.error || ""), "error", "fa-triangle-exclamation");
          return false;
        }
        latest = status === "processing" ? "elaborazione…" : "in coda…";
      }
      if (pending.size) setRow(row, latest);
    }
    if (pending.size) {
      setRow(row, "inviato (elaborazione in corso)", "done", "fa-check");
      return true;
    }
    setRow(row, "sincronizzato", "done", "fa-check");
    return true;
  }

  async function run(btn) {
    const listEl = document.getElementById("wpai-sync-list");
    const progressEl = document.getElementById("wpai-sync-progress");
    btn.disabled = true;
    listEl.innerHTML = "";
    progressEl.textContent = "Recupero elenco…";

    let items;
    try {
      const res = await ajax({ action: "wpai_sync_list" });
      if (!res.success) throw new Error();
      items = res.data;
    } catch (e) {
      progressEl.textContent = "Errore nel recupero dell'elenco.";
      btn.disabled = false;
      return;
    }

    const rows = items.map((it) => {
      const row = document.createElement("div");
      row.className = "wpai-sync-row";
      const label = document.createElement("span");
      label.textContent = it.title + (it.type !== "site-info" ? " · " + it.type : "");
      const status = document.createElement("span");
      status.className = "status";
      status.textContent = "in coda…";
      row.appendChild(label);
      row.appendChild(status);
      listEl.appendChild(row);
      return row;
    });

    let done = 0;
    for (let i = 0; i < items.length; i++) {
      progressEl.textContent = `Sincronizzazione ${i + 1} / ${items.length}…`;
      setRow(rows[i], "invio…");
      let res;
      try {
        res = await ajax({ action: "wpai_sync_item", type: items[i].type, id: items[i].id });
      } catch (e) {
        setRow(rows[i], "errore di rete", "error", "fa-triangle-exclamation");
        continue;
      }
      if (!res || !res.success) {
        setRow(rows[i], "errore: " + (res && res.data ? res.data : ""), "error", "fa-triangle-exclamation");
        continue;
      }
      const jobIds = res.data.job_ids || [res.data.job_id];
      if (await waitForJobs(jobIds, rows[i])) done++;
    }

    progressEl.textContent = `Completato — ${done} / ${items.length} elementi sincronizzati.`;
    btn.disabled = false;
  }

  // Svuotamento della knowledge base. Distruttivo e non annullabile: chiede conferma prima,
  // e non dice "fatto" se il backend ha rifiutato — riporta il motivo.
  async function clearKnowledgeBase(btn, statusEl) {
    const ok = window.confirm(
      "Svuotare la knowledge base?\n\n" +
      "L'assistente resterà senza contenuti da cui rispondere finché non lanci una nuova " +
      "sincronizzazione, e nel frattempo passerà le domande a un operatore.\n\n" +
      "L'operazione non è annullabile."
    );
    if (!ok) return;

    btn.disabled = true;
    statusEl.textContent = "Svuotamento in corso…";
    try {
      const res = await ajax({ action: "wpai_clear_kb" });
      if (!res || !res.success) {
        statusEl.textContent = "Non riuscito: " + ((res && res.data) || "errore sconosciuto");
        return;
      }
      const removed = res.data || {};
      statusEl.textContent =
        `Svuotata: ${removed.removed_chunks || 0} contenuti e ${removed.removed_products || 0} prodotti rimossi. ` +
        "Lancia ora una sincronizzazione completa.";
    } catch (e) {
      statusEl.textContent = "Non riuscito: errore di rete.";
    } finally {
      btn.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("wpai-sync-start");
    if (btn) btn.addEventListener("click", () => run(btn));

    const clearBtn = document.getElementById("wpai-kb-clear");
    const clearStatus = document.getElementById("wpai-kb-clear-status");
    if (clearBtn && clearStatus) {
      clearBtn.addEventListener("click", () => clearKnowledgeBase(clearBtn, clearStatus));
    }
  });
})();
