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
