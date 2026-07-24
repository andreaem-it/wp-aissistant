import json
import os
import urllib.request

import litellm

# ponytail: single global model config for now, per-client override if multi-tenant pricing/models needed later
# Default: Cloudflare Workers AI (no GPU to host). Override to ollama/* for local dev — see .env.example.
CHAT_MODEL = os.getenv("CHAT_MODEL", "cloudflare/@cf/meta/llama-3.1-8b-instruct-fp8")
EMBED_MODEL = os.getenv("EMBED_MODEL", "cloudflare/@cf/baai/bge-m3")
# Only pin a global api_base when explicitly set (e.g. Ollama). Leave it unset for providers
# that litellm routes by model prefix + their own env creds (Cloudflare Workers AI, OpenAI, …),
# otherwise every call would be forced at the Ollama URL.
_api_base = os.getenv("LLM_API_BASE")
if _api_base:
    litellm.api_base = _api_base

# litellm retries+times out its own HTTP calls to the model provider; these just set the
# knobs so a slow/unreachable Ollama fails fast instead of hanging a request indefinitely.
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))

ESCALATE_PREFIX = "ESCALATE:"


class LLMUnavailableError(Exception):
    """Raised when the model provider can't be reached after retries. Callers should
    degrade gracefully (e.g. escalate to a human) instead of letting this 500."""


def _embed_cloudflare_direct(text: str) -> list[float]:
    """litellm 1.93.0 routes Cloudflare Workers AI chat completions but not embeddings
    (raises LiteLLMUnknownProvider) — call the Workers AI REST API directly instead.
    Drop this once litellm adds embedding support for the cloudflare provider."""
    model = EMBED_MODEL.split("/", 1)[1]  # "cloudflare/@cf/baai/bge-m3" -> "@cf/baai/bge-m3"
    account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
    api_key = os.environ["CLOUDFLARE_API_KEY"]
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
        data=json.dumps({"text": [text]}).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
        data = json.loads(resp.read())
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare embedding error: {data.get('errors')}")
    return data["result"]["data"][0]


def embed(text: str) -> list[float]:
    try:
        if EMBED_MODEL.startswith("cloudflare/"):
            return _embed_cloudflare_direct(text)
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
