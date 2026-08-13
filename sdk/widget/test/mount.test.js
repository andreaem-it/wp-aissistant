/**
 * Il widget si monta davvero.
 *
 * Questa è la rete dell'estrazione. Il widget è stato spostato da `wp-plugin` a qui senza
 * riscriverlo, ma "senza riscriverlo" è un'intenzione: 1165 righe passate attraverso una
 * trasformazione meccanica hanno bisogno di qualcosa che dica se il risultato si monta ancora,
 * chiama gli endpoint giusti e ha smesso di parlare di WordPress.
 *
 * Non è una suite di UI: verifica il perimetro — la radice, le classi che vengono dal
 * vocabolario, la chiamata al backend, e il fatto che senza adapter non compaia nulla che
 * presupponga una piattaforma ospite.
 */
import test from "node:test";
import assert from "node:assert";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";

const BACKEND = "https://backend.example";

function setupDom() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "https://esempio.it/pagina",
  });
  global.window = dom.window;
  global.document = dom.window.document;
  global.localStorage = dom.window.localStorage;
  global.CustomEvent = dom.window.CustomEvent;
  // `navigator` e `crypto` sono getter su globalThis nelle versioni recenti di Node: si
  // ridefiniscono, non si assegnano.
  Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
  Object.defineProperty(global, "crypto", {
    value: { randomUUID: () => "visitor-fisso" }, configurable: true,
  });
  return dom;
}

/** Una risposta finta con la forma che il widget si aspetta. */
function reply(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    clone() { return this; },
    json: async () => body,
    body: null,
  };
}

const tick = (ms = 0) => new Promise((resolve) => setTimeout(resolve, ms));

let mountCounter = 0;

async function mountWidget({ config = {}, fetchHandler } = {}) {
  const dom = setupDom();
  const calls = [];
  global.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    return (fetchHandler && fetchHandler(String(url), options)) || reply({});
  };
  // import fresco a ogni test: il modulo tiene stato di sessione fra un mount e l'altro
  mountCounter += 1;
  const { mount } = await import(`../src/widget.js?t=${mountCounter}`);
  const instance = mount({
    backendUrl: BACKEND,
    apiKey: "chiave-pubblica",
    title: "Assistenza",
    subtitle: "Di solito risponde subito",
    welcome: "Ciao!",
    locale: "it-IT",
    host: { siteUrl: "https://esempio.it" },
    ...config,
  });
  await tick();
  return {
    instance,
    calls,
    document: dom.window.document,
    /** Smonta e chiude: senza, il polling del widget terrebbe vivo il processo di test. */
    teardown() {
      instance?.destroy();
      dom.window.close();
    },
  };
}

async function send(w, text) {
  w.document.getElementById("wpai-input").value = text;
  w.document.getElementById("wpai-form").dispatchEvent(new global.window.Event("submit"));
  await tick(20);
}

const withProducts = (url) => (url.includes("/chat")
  ? reply({
      reply: "Eccolo",
      conversation_id: 1,
      conversation_token: "t",
      message_id: 1,
      products: [{ title: "Scarpe", product_url: "https://esempio.it/scarpe", price: "10" }],
    })
  : null);

test("monta la radice, il pulsante e la finestra", async () => {
  const w = await mountWidget();
  try {
    assert.ok(w.document.getElementById("wpai-root"), "manca la radice");
    assert.ok(w.document.getElementById("wpai-toggle"), "manca il pulsante");
    assert.ok(w.document.getElementById("wpai-window"), "manca la finestra");
    assert.ok(w.document.getElementById("wpai-input"), "manca il campo di testo");
  } finally {
    w.teardown();
  }
});

test("le classi della radice vengono dal vocabolario", async () => {
  const w = await mountWidget({
    config: { appearance: { theme: "dark", position: "left", windowSize: "large" } },
  });
  try {
    const root = w.document.getElementById("wpai-root");
    assert.ok(root.classList.contains("wpai-theme-dark"));
    assert.ok(root.classList.contains("wpai-left"));
    assert.ok(root.classList.contains("wpai-size-large"));
  } finally {
    w.teardown();
  }
});

test("un valore di aspetto fuori vocabolario non finisce nel DOM", async () => {
  const w = await mountWidget({
    config: { appearance: { theme: "arcobaleno", color: "#000; url(x)" } },
  });
  try {
    const root = w.document.getElementById("wpai-root");
    assert.ok(root.classList.contains("wpai-theme-light"), "doveva ricadere sul default");
    assert.ok(!root.className.includes("arcobaleno"));
    assert.equal(root.style.getPropertyValue("--wpai-accent"), "#635bff");
  } finally {
    w.teardown();
  }
});

test("il benvenuto compare quando non c'è una conversazione da riprendere", async () => {
  const w = await mountWidget({ config: { welcome: "Ciao dal test!" } });
  try {
    assert.ok(w.document.getElementById("wpai-messages").textContent.includes("Ciao dal test!"));
  } finally {
    w.teardown();
  }
});

test("inviare un messaggio chiama il backend configurato con la chiave pubblica", async () => {
  const w = await mountWidget();
  try {
    await send(w, "ciao");
    const chat = w.calls.find((c) => c.url.includes("/chat"));
    assert.ok(chat, "nessuna chiamata alla chat");
    assert.ok(chat.url.startsWith(BACKEND), "il backend non è quello configurato");
    assert.equal(chat.options.headers.Authorization, "Bearer chiave-pubblica");
  } finally {
    w.teardown();
  }
});

test("il corpo della chat porta il dominio dichiarato dall'adapter", async () => {
  // Serve alla callback della ricerca ordini: l'header Origin non porta il percorso, quindi
  // un'installazione in sottocartella costruirebbe una URL sbagliata.
  const w = await mountWidget();
  try {
    await send(w, "dov'è il mio ordine 123");
    const chat = w.calls.find((c) => c.url.includes("/chat"));
    assert.equal(JSON.parse(chat.options.body).site_url, "https://esempio.it");
  } finally {
    w.teardown();
  }
});

test("un 403 di licenza non arriva al visitatore e finisce in console", async () => {
  const errors = [];
  const original = console.error;
  console.error = (message) => errors.push(String(message));
  const w = await mountWidget({
    fetchHandler: () => reply(
      { detail: "Il dominio esempio.it non è registrato per questa licenza." },
      { ok: false, status: 403 },
    ),
  });
  try {
    await send(w, "ciao");
    const shown = w.document.getElementById("wpai-messages").textContent;
    assert.ok(!shown.includes("licenza"), "il visitatore non deve leggere di licenze");
    assert.ok(!shown.includes("403"));
    assert.ok(errors.some((e) => e.includes("non è registrato")), "il motivo doveva finire in console");
  } finally {
    console.error = original;
    w.teardown();
  }
});

test("senza adapter del carrello non compare nessun pulsante di acquisto", async () => {
  // È il comportamento su un sito che non vende da sé: la card resta un collegamento al
  // prodotto invece di un pulsante che non può funzionare.
  const w = await mountWidget({ fetchHandler: withProducts });
  try {
    await send(w, "scarpe");
    assert.ok(w.document.querySelector(".wpai-product-card"), "la card doveva esserci");
    assert.equal(w.document.querySelector(".wpai-add-to-cart"), null, "il pulsante non doveva esserci");
  } finally {
    w.teardown();
  }
});

test("con l'adapter del carrello il pulsante c'è e chiama l'adapter", async () => {
  let added = null;
  const w = await mountWidget({
    config: {
      host: {
        siteUrl: "https://esempio.it",
        addToCart: async (product) => { added = product.product_url; return { ok: true }; },
      },
    },
    fetchHandler: withProducts,
  });
  try {
    await send(w, "scarpe");
    const button = w.document.querySelector(".wpai-add-to-cart");
    assert.ok(button, "il pulsante doveva esserci");
    button.dispatchEvent(new global.window.Event("click"));
    await tick(10);
    assert.equal(added, "https://esempio.it/scarpe");
  } finally {
    w.teardown();
  }
});

test("smontare ferma il polling, non solo il DOM", async () => {
  // Su un sito non si nota perché la pagina cambia; dentro un pannello a pagina singola
  // resterebbe un poller per ogni visita, tutti attivi insieme.
  const w = await mountWidget({
    fetchHandler: (url) => (url.includes("/chat")
      ? reply({ reply: "ok", conversation_id: 7, conversation_token: "t", message_id: 1 })
      : null),
  });
  await send(w, "ciao");
  const before = w.calls.length;
  w.teardown();
  await tick(30);

  assert.equal(w.calls.length, before, "il widget ha continuato a chiamare dopo destroy()");
});

test("l'adapter può aggiungere header alle chiamate di chat", async () => {
  // Il pannello ci manda il token con cui il backend sa *di chi* si sta parlando. È una capacità
  // dell'host come le altre: il widget non sa cosa sia, lo inoltra e basta.
  const w = await mountWidget({
    config: { host: { siteUrl: "https://esempio.it", chatHeaders: () => ({ "X-Prova": "abc" }) } },
  });
  try {
    await send(w, "ciao");
    const chat = w.calls.find((c) => c.url.includes("/chat"));
    assert.equal(chat.options.headers["X-Prova"], "abc");
    // e non deve aver perso quelli che servivano già
    assert.equal(chat.options.headers.Authorization, "Bearer chiave-pubblica");
  } finally {
    w.teardown();
  }
});

test("gli header dell'adapter si richiedono a ogni messaggio", async () => {
  // Non si tengono per la vita della pagina come `identityToken()`: il token del pannello dura
  // 5 minuti e una conversazione dura di più, quindi una cache lo farebbe scadere a metà chat
  // e il contesto sparirebbe senza che nulla lo dica.
  let chiamate = 0;
  const w = await mountWidget({
    config: {
      host: {
        siteUrl: "https://esempio.it",
        chatHeaders: () => { chiamate += 1; return { "X-Prova": String(chiamate) }; },
      },
    },
  });
  try {
    await send(w, "uno");
    await send(w, "due");
    // Il valore chiesto per il secondo messaggio è diverso da quello del primo: è la prova che
    // non è stato riusato. Il conteggio grezzo direbbe poco — ogni messaggio prova prima lo
    // streaming e poi ripiega su /chat, quindi le chiamate sono più dei messaggi.
    const inviati = w.calls
      .filter((c) => c.url.includes("/chat"))
      .map((c) => c.options.headers["X-Prova"]);
    assert.ok(chiamate >= 2, "l'adapter non è stato richiamato per il secondo messaggio");
    assert.ok(inviati.length >= 2);
    assert.notEqual(inviati[0], inviati[inviati.length - 1], "l'header è stato riusato");
  } finally {
    w.teardown();
  }
});

test("un adapter che fallisce non impedisce di scrivere", async () => {
  // Il contesto è un di più, non una credenziale: se non arriva si risponde lo stesso, in modo
  // più generico. Un'eccezione qui bloccherebbe la chat per un'informazione accessoria.
  const w = await mountWidget({
    config: {
      host: {
        siteUrl: "https://esempio.it",
        chatHeaders: () => { throw new Error("niente token"); },
      },
    },
  });
  try {
    await send(w, "ciao");
    const chat = w.calls.find((c) => c.url.includes("/chat"));
    assert.ok(chat, "il messaggio non è partito");
    assert.equal(chat.options.headers.Authorization, "Bearer chiave-pubblica");
  } finally {
    w.teardown();
  }
});

test("senza adapter le chiamate di chat restano come prima", async () => {
  const w = await mountWidget();
  try {
    await send(w, "ciao");
    const chat = w.calls.find((c) => c.url.includes("/chat"));
    assert.deepEqual(Object.keys(chat.options.headers).sort(),
                     ["Authorization", "Content-Type"]);
  } finally {
    w.teardown();
  }
});

test("il codice del widget non nomina più WordPress", async () => {
  const source = await readFile(new URL("../src/widget.js", import.meta.url), "utf8");
  // Solo il codice: un commento può citare WooCommerce per spiegare cosa fa l'adapter, ed è
  // giusto che lo faccia. È il codice a non doverne più sapere niente.
  const code = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n").map((line) => line.replace(/\/\/.*$/, "")).join("\n");

  for (const token of ["ajaxUrl", "wpai_add_to_cart", "wpai_user_token", "jQuery",
                       "woocommerce", "window.WPAI", "WPAI."]) {
    assert.ok(!code.includes(token), `il widget nomina ancora "${token}"`);
  }
});

// ---- Le icone, l'avatar e i testi -------------------------------------------------------------
//
// Tre difetti trovati insieme guardando uno screenshot dell'anteprima, tutti della stessa
// famiglia: l'installazione JavaScript non dava lo stesso widget di quella con il plugin, e
// nessuno dei tre diceva niente.

test("le icone sono dentro il bundle, non in un font della pagina ospite", async () => {
  // Erano `<i class="fa-solid …">`: il plugin accodava Font Awesome da un CDN di terzi e sembrava
  // tutto a posto, mentre chi installava il JavaScript vedeva un pulsante d'invio vuoto.
  const w = await mountWidget();
  try {
    const root = w.document.getElementById("wpai-root");
    assert.equal(root.querySelectorAll("i.fa-solid, i.fa-regular").length, 0,
                 "il widget dipende ancora da un font di icone esterno");
    assert.ok(w.document.querySelector("#wpai-toggle svg.wpai-icon"), "il launcher non ha icona");
    assert.ok(w.document.querySelector("#wpai-form button svg.wpai-icon"), "l'invio non ha icona");
    assert.ok(w.document.querySelector("#wpai-close svg.wpai-icon"), "la chiusura non ha icona");
  } finally {
    w.teardown();
  }
});

test("ogni icona del vocabolario del launcher esiste davvero", async () => {
  // Il vocabolario offre quattro icone: se una non fosse disegnata, il cliente la sceglierebbe
  // dal configuratore e otterrebbe un launcher vuoto — di nuovo senza nessun errore.
  const { names } = await import("../src/icons.js");
  const { APPEARANCE } = await import("../src/schema.js");
  for (const scelta of APPEARANCE.launcherIcon.values) {
    assert.ok(names().includes(scelta), `manca l'icona "${scelta}"`);
  }
});

test("senza immagine l'avatar è l'iniziale, non un file rotto", async () => {
  // `safeHttpUrl()` tornava "#" e il browser disegnava l'icona di immagine mancante: il plugin
  // non lo mostrava perché ne accoda uno predefinito dal pacchetto, il bundle sì.
  const w = await mountWidget({ config: { title: "Acme" } });
  try {
    assert.equal(w.document.querySelector("#wpai-header img"), null);
    const iniziale = w.document.querySelector(".wpai-avatar-initials");
    assert.ok(iniziale, "manca il ripiego dell'avatar");
    assert.equal(iniziale.textContent, "A");
  } finally {
    w.teardown();
  }
});

test("con un'immagine valida l'avatar è quella", async () => {
  const w = await mountWidget({ config: { image: "https://esempio.it/logo.png" } });
  try {
    const img = w.document.querySelector("#wpai-header img");
    assert.ok(img);
    assert.equal(img.src, "https://esempio.it/logo.png");
  } finally {
    w.teardown();
  }
});

test("i testi annidati dello snippet non vengono più ignorati", async () => {
  // Il configuratore genera `texts: { title: … }`, il widget leggeva `cfg.title`: il cliente
  // cambiava il nome, copiava lo snippet e continuava a vedere il default. Nessun errore da
  // nessuna parte — vale anche per lo snippet del nostro sito.
  const w = await mountWidget({
    config: {
      title: undefined, subtitle: undefined,
      texts: { title: "Acme", subtitle: "Sempre attivi" },
    },
  });
  try {
    assert.equal(w.document.querySelector(".wpai-header-copy strong").textContent, "Acme");
    assert.equal(w.document.querySelector(".wpai-header-copy small").textContent, "Sempre attivi");
  } finally {
    w.teardown();
  }
});

test("un testo in cima vince su quello annidato", async () => {
  // È la forma che un host costruisce a runtime sapendo qualcosa in più: il plugin legge le
  // impostazioni del sito, il pannello sa chi è l'operatore loggato.
  const w = await mountWidget({ config: { title: "In cima", texts: { title: "Annidato" } } });
  try {
    assert.equal(w.document.querySelector(".wpai-header-copy strong").textContent, "In cima");
  } finally {
    w.teardown();
  }
});

test("senza testi si usano i default, non stringhe vuote", async () => {
  const w = await mountWidget({ config: { title: undefined, subtitle: undefined } });
  try {
    assert.equal(w.document.querySelector(".wpai-header-copy strong").textContent, "Assistenza");
    assert.ok(w.document.querySelector(".wpai-header-copy small").textContent.length > 0);
  } finally {
    w.teardown();
  }
});

// ---- L'indirizzo del backend ------------------------------------------------------------------


/**
 * Il bundle costruito, costruendolo se non c'è.
 *
 * In CI `npm test` gira **prima** di `npm run build`, quindi un test che legge `dist/` non lo
 * trova. La convenzione qui accanto è uscire in silenzio, ma un test che non verifica niente e
 * riporta verde è il fallimento muto contro cui è scritta metà di questo repository: costruire
 * costa duecento millisecondi e l'asserzione resta vera sempre.
 */
let bundleCache = null;
async function builtBundle() {
  if (bundleCache) return bundleCache;
  const url = new URL("../dist/wpai-widget.js", import.meta.url);
  try {
    bundleCache = await readFile(url, "utf8");
  } catch {
    const { execFileSync } = await import("node:child_process");
    execFileSync(process.execPath, ["build.mjs"], {
      cwd: new URL("..", import.meta.url).pathname,
      stdio: "ignore",
    });
    bundleCache = await readFile(url, "utf8");
  }
  return bundleCache;
}

test("l\'artefatto pubblicato porta dentro l\'indirizzo del backend", async () => {
  // Non è un'opzione di chi installa: uno snippet che lo porta in chiaro è un indirizzo congelato
  // nelle pagine dei clienti, e cambiarlo richiederebbe di chiederglielo uno per uno.
  const bundle = await builtBundle();

  assert.ok(bundle.includes("https://backend.wpaissistant.it"), "l'indirizzo non è compilato");
  assert.ok(!bundle.includes("railway.app"), "l'artefatto punta ancora all'URL grezzo di Railway");
  assert.ok(!bundle.includes("__WPAI_"), "una define della build non è stata sostituita");
});

test("nel bundle pubblicato un backendUrl nella configurazione viene ignorato", async () => {
  // La porta si chiude a build time (`DEV: false`), non con un controllo che qualcuno può
  // togliere: chi copia lo snippet non deve poter ripuntare il widget altrove.
  const bundle = await builtBundle();
  // `!1` è il `false` minificato: la scelta è già stata fatta dalla build.
  assert.ok(/=\s*!1\s*;/.test(bundle) || bundle.includes("=!1,"),
            "l'interruttore di sviluppo non risulta spento nell'artefatto");
});
