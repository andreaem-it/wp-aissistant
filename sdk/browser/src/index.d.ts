/**
 * Tipi pubblici di `@wp-aissistant/browser`.
 *
 * I payload del backend sono descritti con i campi garantiti dall'API `1.0` più una firma
 * indicizzata: un campo aggiunto in futuro non rompe la compilazione di chi integra l'SDK.
 */

/** Sottoinsieme di `localStorage` richiesto dal client: funziona anche con storage custom. */
export interface WpAissistantStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface WpAissistantClientOptions {
  /** Base URL del backend. Fuori da `localhost`/`127.0.0.1` deve usare HTTPS. */
  apiBase: string;
  /** Chiave pubblica del widget: mai una chiave con scope operatore o canale. */
  apiKey: string;
  /** Default: `globalThis.localStorage`, con fallback in memoria. */
  storage?: WpAissistantStorage;
  /** Prefisso delle chiavi di sessione. Default: `wpai_sdk`. */
  storagePrefix?: string;
  /** `fetch` alternativo (test, SSR, proxy). Default: `globalThis.fetch`. */
  fetchImpl?: typeof globalThis.fetch;
  /** Timeout per richiesta in millisecondi. Default: 30000. */
  timeout?: number;
}

export interface WpAissistantSession {
  visitorId: string;
  conversationId: number | null;
  conversationToken: string;
}

export interface WpAissistantSendOptions {
  /** Lingua del visitatore: è solo un suggerimento, il backend rileva la lingua dal testo. */
  locale?: string;
  /** `false` quando il supporto umano è chiuso: il backend propone un ticket invece dell'escalation. */
  supportAvailable?: boolean;
  siteUrl?: string;
  /** Token utente WordPress firmato, quando l'integrazione lo espone. */
  wpUserToken?: string;
}

export type WpAissistantStatus =
  | "new"
  | "open"
  | "escalated"
  | "ticket_offered"
  | "quota_exceeded"
  | "closed"
  | (string & {});

export interface WpAissistantProduct {
  title: string;
  price: string | number | null;
  image_url: string | null;
  product_url: string;
  [key: string]: unknown;
}

/** Risposta di `send()`. `reply` è `null` quando la conversazione è passata a un operatore. */
export interface WpAissistantReply {
  conversation_id: number;
  conversation_token: string;
  status: WpAissistantStatus;
  reply: string | null;
  products?: WpAissistantProduct[];
  message_id?: number;
  reason?: string;
  [key: string]: unknown;
}

export interface WpAissistantAttachment {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
}

export interface WpAissistantMessage {
  id: number;
  role: "user" | "assistant" | "operator" | (string & {});
  content: string;
  attachments: WpAissistantAttachment[];
  [key: string]: unknown;
}

export interface WpAissistantMessagesResult {
  status: WpAissistantStatus;
  messages: WpAissistantMessage[];
  /** Nome dell'operatore che sta scrivendo, `null` se nessuno. */
  operator_typing?: string | null;
  /** `true` quando il CSAT è già stato chiesto: non richiederlo di nuovo. */
  rated: boolean;
  [key: string]: unknown;
}

/**
 * Eventi dello streaming SSE. L'unione è discriminata su `type`, così `event.type === "token"`
 * restringe il tipo. Ogni membro accetta campi aggiuntivi: un evento arricchito dal backend
 * non rompe la compilazione. Un `type` non ancora conosciuto va gestito nel ramo finale,
 * restringendo con `event as { type: string; [key: string]: unknown }`.
 */
export type WpAissistantStreamEvent =
  | { type: "start"; conversation_id: number; conversation_token: string; [key: string]: unknown }
  | { type: "token"; text: string; [key: string]: unknown }
  | { type: "escalated"; conversation_id: number; [key: string]: unknown }
  | { type: "quota_exceeded"; conversation_id: number; [key: string]: unknown }
  | { type: "ticket_offered"; conversation_id: number; reason?: string; [key: string]: unknown }
  | {
      type: "done";
      conversation_id: number;
      message_id?: number;
      products?: WpAissistantProduct[];
      [key: string]: unknown;
    };

export type WpAissistantLeadFieldType = "text" | "email" | "tel" | "select";
export type WpAissistantLeadTrigger = "escalation" | "chat_start";

/** Campo del form come lo riceve il browser: i punti di scoring non vengono mai esposti. */
export interface WpAissistantLeadField {
  key: string;
  label: string;
  type: WpAissistantLeadFieldType | (string & {});
  required: boolean;
  options: string[];
  [key: string]: unknown;
}

export interface WpAissistantLeadForm {
  id: number;
  intro: string | null;
  consent_text: string | null;
  trigger: WpAissistantLeadTrigger | (string & {});
  fields: WpAissistantLeadField[];
  [key: string]: unknown;
}

export interface WpAissistantLeadFormResult {
  form: WpAissistantLeadForm | null;
}

export interface WpAissistantAck {
  ok: boolean;
  [key: string]: unknown;
}

export interface WpAissistantLeadAck extends WpAissistantAck {
  id: number;
}

export interface WpAissistantRequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  conversationToken?: string;
}

/** Errore applicativo dell'SDK: `status` è 0 per timeout e problemi di rete. */
export declare class WpAissistantError extends Error {
  constructor(message: string, status?: number, payload?: unknown);
  name: "WpAissistantError";
  status: number;
  payload: unknown;
}

export declare class WpAissistantClient {
  constructor(options: WpAissistantClientOptions);

  readonly apiBase: string;
  readonly apiKey: string;
  readonly fetchImpl: typeof globalThis.fetch;
  readonly timeout: number;
  readonly storage: WpAissistantStorage;
  readonly prefix: string;

  /** Sessione corrente letta dallo storage: il token conversazione non finisce mai nella URL. */
  readonly session: WpAissistantSession;

  /** Dimentica visitatore, conversazione e token. Da chiamare al logout o su richiesta GDPR. */
  reset(): void;

  /** Identificativo stabile del visitatore, generato al primo utilizzo. */
  visitorId(): string;

  request<T = unknown>(path: string, options?: WpAissistantRequestOptions): Promise<T>;

  /** Salva `conversation_id`/`conversation_token` se presenti e restituisce il payload. */
  remember<T>(payload: T): T;

  send(message: string, options?: WpAissistantSendOptions): Promise<WpAissistantReply>;

  /** Streaming SSE: gli eventi arrivano nell'ordine emesso dal backend. */
  stream(
    message: string,
    options?: WpAissistantSendOptions,
  ): AsyncGenerator<WpAissistantStreamEvent, void, undefined>;

  /** Polling dei messaggi, incluse le risposte dell'operatore. Senza conversazione attiva
   * restituisce `{ status: "new", messages: [], rated: false }` senza chiamare il backend. */
  messages(options?: { afterId?: number; limit?: number }): Promise<WpAissistantMessagesResult>;

  feedback(messageId: number, value: "up" | "down"): Promise<WpAissistantAck>;
  contact(email: string, url?: string): Promise<WpAissistantAck>;
  ticket(reason: string): Promise<WpAissistantAck & { conversation_id: number }>;
  /** CSAT di fine conversazione: punteggio 1–5 e commento facoltativo. */
  rating(score: number, comment?: string): Promise<WpAissistantAck>;

  /** Lancia `WpAissistantError` se non c'è una conversazione attiva. */
  conversationPost<T = WpAissistantAck>(path: string, fields: Record<string, unknown>): Promise<T>;

  leadForm(trigger?: WpAissistantLeadTrigger | (string & {})): Promise<WpAissistantLeadFormResult>;
  submitLead(
    formId: number,
    data: Record<string, string>,
    consent?: boolean,
  ): Promise<WpAissistantLeadAck>;
}

export declare function createClient(options: WpAissistantClientOptions): WpAissistantClient;
