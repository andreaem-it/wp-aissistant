---
block: widget-parity
owner: claude
started_at: 2026-08-13T23:30:00+02:00
expires_at: 2026-08-15T23:30:00+02:00
branch: main
---

Obiettivo: l'installazione JavaScript deve dare **lo stesso widget** di quella con il plugin.
Oggi non lo dà, e nessuno dei difetti fa rumore.

Trovati partendo da uno screenshot dell'anteprima:

1. **Le icone non ci sono.** Il widget disegna `<i class="fa-solid …">` e conta su Font Awesome
   nella pagina. Il plugin la accoda da un CDN; il bundle standalone no, quindi il pulsante
   d'invio e il launcher sono rettangoli vuoti. Un bundle che si dichiara senza dipendenze ne ha
   una, non dichiarata, su un dominio di terzi.
2. **L'avatar è un'immagine rotta.** Senza `image` configurata `safeHttpUrl()` torna `"#"`, e il
   browser disegna l'icona di immagine mancante. Il plugin ha un avatar predefinito nel
   pacchetto; il bundle non ha né quello né il buon senso di non disegnare nulla.
3. **I testi dello snippet vengono ignorati in silenzio.** Il configuratore genera
   `texts: { title, subtitle, … }`, il widget legge `cfg.title` a livello superiore, e nessuno
   dei due se ne accorge: il cliente imposta il nome, copia lo snippet e vede il default. Vale
   anche per lo snippet del **nostro** sito.
4. **Avatar e link privacy non sono configurabili.** `widget_config.vocabulary()` espone solo
   `textLimits`, quindi il configuratore non può disegnare i campi URL — che pure hanno già la
   loro etichetta in `LABELS`, segno che dovevano esserci.
5. **`backendUrl` è un'opzione del cliente, e non deve esserlo.** Sta in chiaro nello snippet, il
   che significa che chi lo copia può ripuntare il widget dove vuole e che noi non possiamo
   cambiare indirizzo senza chiedere a ogni cliente di ricopiare. L'indirizzo del backend è una
   proprietà dell'artefatto, non una scelta di chi lo installa: va compilato dentro il bundle.
6. **E l'indirizzo era anche sbagliato.** Ovunque compare l'URL grezzo di Railway invece del
   dominio vero, `backend.wpaissistant.it` — che esiste e risponde. Ce l'hanno nello snippet
   generato, nel nostro sito e in `panel/.env.production`.

7. **`www.` e apex non sono lo stesso sito per la CORS** (trovato applicando il punto 6). Il
   controllo della licenza normalizza `www.` — `origins.host_of()` — mentre l'allowlist CORS
   confronta la stringa esatta dell'Origin. Una regola sola scritta in due modi: chi registra
   `https://esempio.it` e ha visitatori su `https://www.esempio.it` riceve `403` al preflight e
   la chat non parte. Vale **oggi in produzione sul nostro stesso sito**, e non c'entra con il
   dominio nuovo: si verifica identico sull'URL di Railway.

Perimetro previsto:
- `sdk/widget/src/` (icone inline, avatar, testi, indirizzo del backend), `build.mjs` e i test
- `backend/app/widget_config.py` (il vocabolario espone i campi URL) e i suoi test
- `backend/app/cors.py` (`www.` e apex sono lo stesso sito, come già per la licenza) e i test
- `panel/src/Install.jsx`, `panel/src/snippet.js`, `panel/.env.production` e i loro test
- `wp-plugin/wp-aissistant/wp-aissistant.php` (il front-end non ha più bisogno di Font Awesome)
- `website/index.html` (lo snippet nella forma giusta)
- `docs/embedded-assistant-roadmap.md`

Comporta una versione nuova del widget e la ripubblicazione sul CDN: il bundle cambia davvero.

Fuori perimetro: backend a parte `widget_config.py`, fatturazione, assistente del pannello.
