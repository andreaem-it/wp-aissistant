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

  function setRow(row, statusText, cls) {
    row.className = "wpai-sync-row" + (cls ? " " + cls : "");
    row.querySelector(".status").textContent = statusText;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // poll the ingest job until it's done/error (or we give up after ~30s)
  async function waitForJob(jobId, row) {
    for (let i = 0; i < 20; i++) {
      await sleep(1500);
      let res;
      try {
        res = await ajax({ action: "wpai_job_status", job_id: jobId });
      } catch (e) {
        continue;
      }
      if (!res || !res.success) continue;
      const status = res.data.status;
      if (status === "done") { setRow(row, "✓ sincronizzato", "done"); return; }
      if (status === "error") { setRow(row, "errore: " + (res.data.error || ""), "error"); return; }
      setRow(row, status === "processing" ? "elaborazione…" : "in coda…");
    }
    setRow(row, "✓ inviato (elaborazione in corso)", "done");
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
        setRow(rows[i], "errore di rete", "error");
        continue;
      }
      if (!res || !res.success) {
        setRow(rows[i], "errore: " + (res && res.data ? res.data : ""), "error");
        continue;
      }
      await waitForJob(res.data.job_id, rows[i]);
      done++;
    }

    progressEl.textContent = `Completato — ${done} / ${items.length} elementi sincronizzati.`;
    btn.disabled = false;
  }

  document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("wpai-sync-start");
    if (btn) btn.addEventListener("click", () => run(btn));
  });
})();
