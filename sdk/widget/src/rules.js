/**
 * Regole di business del widget, senza browser.
 *
 * Stessa idea di `chat-i18n.js`: qui vive ciò che decide *se* fare qualcosa — il supporto è
 * raggiungibile adesso? questo messaggio proattivo può comparire su questa pagina? quale
 * variante A/B tocca a questo visitatore? — mentre il widget resta responsabile di leggere lo
 * storage e costruire il DOM.
 *
 * Ogni funzione riceve i suoi ingressi esplicitamente (orario, storage già letto, URL) invece di
 * andarli a prendere da variabili globali. È l'unica ragione per cui possono essere verificate
 * da `node --test` senza un DOM, ed è anche il motivo per cui restano leggibili: guardando la
 * firma si sa da cosa dipende la decisione.
 *
 * Modulo ESM del bundle `sdk/widget`.
 */
const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * Il supporto umano è raggiungibile in questo momento?
 *
 * `support` è la configurazione del tenant: giorni (1 = lunedì … 7 = domenica), orari "HH:MM"
 * e fuso orario WordPress. Il calcolo passa da Intl per rispettare il fuso *e* l'ora legale:
 * confrontare timestamp UTC darebbe la risposta sbagliata due volte l'anno.
 *
 * Un orario che scavalca la mezzanotte (22:00–02:00) appartiene al giorno in cui è iniziato,
 * quindi dopo mezzanotte si controlla il giorno precedente.
 *
 * In caso di configurazione illeggibile risponde **true**: preferiamo offrire un operatore che
 * potrebbe non esserci, piuttosto che nasconderlo a chi ne ha bisogno.
 */
function supportAvailable(support, now) {
  const config = support || {};
  if (!config.enabled) return true;
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: config.timezone,
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now || new Date());
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    const dayMap = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };
    const day = dayMap[values.weekday];
    const minute = Number(values.hour) * 60 + Number(values.minute);
    const toMinute = (value) => {
      const [hour, min] = String(value).split(":").map(Number);
      return hour * 60 + min;
    };
    const start = toMinute(config.start);
    const end = toMinute(config.end);
    const days = (config.days || []).map(Number);
    if (start <= end) return days.includes(day) && minute >= start && minute < end;
    const previousDay = day === 1 ? 7 : day - 1;
    return (days.includes(day) && minute >= start) || (days.includes(previousDay) && minute < end);
  } catch (error) {
    return true;
  }
}

/**
 * La regola proattiva è pertinente a questa pagina?
 *
 * `url` è l'indirizzo corrente e `cartItems` quanti articoli ci sono nel carrello: il widget li
 * legge, qui si decide soltanto.
 */
function proactiveMatches(rule, url, cartItems) {
  if (rule.url_pattern && !String(url || "").includes(rule.url_pattern)) return false;
  if (rule.trigger_type === "cart") return Number(cartItems || 0) > 0;
  return true;
}

/**
 * La regola può comparire, data la frequenza scelta dal tenant e quanto il visitatore ha già
 * visto? `state` è ciò che il widget ha letto dallo storage: opt-out, se la regola è già
 * comparsa in questa sessione, e quando è comparsa l'ultima volta.
 *
 * L'opt-out del visitatore vince su qualsiasi frequenza, anche su "always": chi ha detto di
 * non voler essere interrotto non va interrotto.
 */
function proactiveAllowed(rule, state) {
  const s = state || {};
  if (s.optedOut) return false;
  if (rule.frequency === "always") return true;
  if (rule.frequency === "once_per_session") return !s.seenThisSession;
  return (s.now || Date.now()) - (s.lastShownAt || 0) > DAY_MS; // once_per_day
}

/**
 * Quale variante mostrare in un A/B.
 *
 * L'assegnazione è **stabile**: una volta scelta resta quella per il visitatore, altrimenti il
 * confronto fra varianti misurerebbe il caso invece del messaggio. `current` è l'assegnazione
 * già memorizzata (se c'è) e `draw` un numero in [0,1) — passato dal chiamante così il test è
 * deterministico.
 *
 * Senza un messaggio B non c'è esperimento: sempre "a".
 */
function proactiveVariant(rule, current, draw) {
  if (!rule.message_b) return "a";
  if (current === "a" || current === "b") return current;
  const value = typeof draw === "number" ? draw : Math.random();
  return value < 0.5 ? "a" : "b";
}

export { supportAvailable, proactiveMatches, proactiveAllowed, proactiveVariant, DAY_MS };
