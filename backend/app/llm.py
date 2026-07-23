import os
import litellm

# ponytail: single global model config for now, per-client override if multi-tenant pricing/models needed later
CHAT_MODEL = os.getenv("CHAT_MODEL", "ollama/llama3.1")
EMBED_MODEL = os.getenv("EMBED_MODEL", "ollama/nomic-embed-text")
litellm.api_base = os.getenv("LLM_API_BASE", "http://localhost:11434")

# litellm retries+times out its own HTTP calls to the model provider; these just set the
# knobs so a slow/unreachable Ollama fails fast instead of hanging a request indefinitely.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))

ESCALATE_PREFIX = "ESCALATE:"


class LLMUnavailableError(Exception):
    """Raised when the model provider can't be reached after retries. Callers should
    degrade gracefully (e.g. escalate to a human) instead of letting this 500."""


def embed(text: str) -> list[float]:
    try:
        resp = litellm.embedding(
            model=EMBED_MODEL, input=[text], timeout=LLM_TIMEOUT, num_retries=LLM_RETRIES
        )
    except Exception as exc:
        raise LLMUnavailableError(str(exc)) from exc
    return resp.data[0]["embedding"]


def chat(system: str, history: list[dict], user_message: str) -> dict:
    """Returns {"reply": str} or {"escalate": reason}.

    ponytail: plain-text escalation marker instead of native tool-calling — small local
    models (llama3.1 on Ollama) hallucinate arbitrary function calls when given a tools
    schema instead of respecting it, so a text convention is more reliable and also
    works unchanged across OpenAI/Claude/Perplexity once those are wired in.
    """
    instructions = (
        f"{system}\n\nIf you cannot answer from the context above, or the request needs "
        f"human authority (refunds, complaints, account changes, order-specific issues), "
        f'you MUST respond with EXACTLY one line: "{ESCALATE_PREFIX} <short reason>" and '
        f"nothing else — do not ask clarifying questions first, do not explain, do not "
        f"apologize, just escalate immediately. Otherwise answer normally."
    )
    messages = [{"role": "system", "content": instructions}, *history, {"role": "user", "content": user_message}]
    try:
        resp = litellm.completion(
            model=CHAT_MODEL, messages=messages, timeout=LLM_TIMEOUT, num_retries=LLM_RETRIES
        )
    except Exception as exc:
        raise LLMUnavailableError(str(exc)) from exc
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith(ESCALATE_PREFIX):
        return {"escalate": text[len(ESCALATE_PREFIX):].strip() or "unspecified"}
    return {"reply": text}
