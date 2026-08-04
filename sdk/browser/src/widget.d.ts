/** Web component `<wpai-chat>`: interfaccia minima isolata in Shadow DOM sopra il client. */
import type { WpAissistantClient, WpAissistantStreamEvent } from "./index.js";

/**
 * Attributi supportati da `<wpai-chat>`:
 * `api-base` e `api-key` (obbligatori), `storage-prefix`, `title`, `button-label`,
 * `placeholder`, `disclosure`, `privacy-url`, `locale`.
 *
 * Eventi emessi: `wpai-event` con l'evento di streaming, `wpai-error` con `{ message }`.
 */
export declare class WpAissistantChatElement extends HTMLElement {
  client?: WpAissistantClient;
  connectedCallback(): void;
  setOpen(open: boolean): void;
  addMessage(role: "user" | "assistant" | (string & {}), text: string): HTMLDivElement;
  restore(): Promise<void>;
  onSubmit(event: Event): Promise<void>;
}

/** Registra `<wpai-chat>` una sola volta. Restituisce sempre la classe dell'elemento. */
export declare function registerWpAissistantChat(
  registry?: CustomElementRegistry,
): typeof WpAissistantChatElement;

export interface WpAissistantChatEventMap {
  "wpai-event": CustomEvent<WpAissistantStreamEvent>;
  "wpai-error": CustomEvent<{ message: string }>;
}

declare global {
  interface HTMLElementTagNameMap {
    "wpai-chat": WpAissistantChatElement;
  }
}
