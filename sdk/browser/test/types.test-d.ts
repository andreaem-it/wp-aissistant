/**
 * Controllo di compilazione dei tipi pubblici: non gira con `node --test`, viene verificato da
 * `npm run types`. Se una firma cambia in modo incompatibile, qui il compilatore si ferma.
 */
import {
  createClient,
  WpAissistantClient,
  WpAissistantError,
  type WpAissistantReply,
  type WpAissistantStreamEvent,
} from "../src/index.js";
import { registerWpAissistantChat, type WpAissistantChatElement } from "../src/widget.js";

const assistant: WpAissistantClient = createClient({
  apiBase: "https://backend.example",
  apiKey: "public-key",
  storagePrefix: "shop",
  timeout: 15000,
  storage: { getItem: () => null, setItem: () => undefined, removeItem: () => undefined },
});

async function conversation(): Promise<string> {
  const reply: WpAissistantReply = await assistant.send("Avete questo prodotto in blu?", {
    locale: "it-IT",
    supportAvailable: true,
  });
  const title: string | undefined = reply.products?.[0]?.title;
  let text = `${reply.reply ?? ""}${title ?? ""}`;

  for await (const event of assistant.stream("Mostrami le alternative")) {
    const narrowed: WpAissistantStreamEvent = event;
    if (narrowed.type === "token") text += narrowed.text;
    if (narrowed.type === "done") text += String(narrowed.message_id ?? "");
    if (narrowed.type === "ticket_offered") text += narrowed.reason ?? "";
  }

  const history = await assistant.messages({ afterId: 4, limit: 20 });
  text += history.messages.map((message) => message.content).join("");
  text += history.rated ? "rated" : "";

  await assistant.feedback(12, "up");
  await assistant.contact("cliente@example.it");
  await assistant.rating(5, "perfetto");
  const ticket = await assistant.ticket("serve un umano");
  text += String(ticket.conversation_id);

  const { form } = await assistant.leadForm("chat_start");
  if (form) {
    const answers: Record<string, string> = Object.fromEntries(form.fields.map((field) => [field.key, ""]));
    const lead = await assistant.submitLead(form.id, answers, true);
    text += String(lead.id);
  }

  const session = assistant.session;
  text += `${session.visitorId}${session.conversationId ?? 0}${session.conversationToken}`;
  assistant.reset();
  return text;
}

async function failure(): Promise<number> {
  try {
    await conversation();
    return 0;
  } catch (error) {
    return error instanceof WpAissistantError ? error.status : -1;
  }
}

const element: typeof WpAissistantChatElement = registerWpAissistantChat();
void element;
void failure;
