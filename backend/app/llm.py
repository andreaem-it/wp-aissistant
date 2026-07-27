import json
import os
import re
import time
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
# request token usage in streamed responses (so streamed replies log real token counts).
# Opt-in (default off) because it touches the live chat path: enable once you've confirmed your
# provider accepts stream_options. Auto-disabled at runtime anyway if the provider rejects it.
_stream_usage_supported = os.getenv("STREAM_INCLUDE_USAGE", "false").lower() == "true"

ESCALATE_PREFIX = "ESCALATE:"
ORDER_LOOKUP_PREFIX = "ORDER_LOOKUP:"
# ponytail: the model doesn't reliably reproduce the marker word itself — seen "ORDERS_LOOKUP:"
# and even a fully hallucinated "ORDINELISTO:". Matching on the word is a losing game, so match
# the marker's *shape* instead: a single short label, a colon, an order number, a pipe, an
# identifier. That "N | text" shape essentially never occurs in an ordinary reply, so it's a
# safe anchor even when the label itself is unpredictable.
ORDER_LOOKUP_RE = re.compile(r"^\s*[A-Za-z_]{3,30}:\s*(\d{2,})\s*\|\s*([^\n]+)", re.I)


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
    """Returns {"reply": str} or {"escalate": reason}, always with diagnostic fields
    {"model", "latency_ms", "tokens_prompt", "tokens_completion"} for the AI response log.

    ponytail: plain-text escalation marker instead of native tool-calling — small local
    models (llama3.1 on Ollama) hallucinate arbitrary function calls when given a tools
    schema instead of respecting it, so a text convention is more reliable and also
    works unchanged across OpenAI/Claude/Perplexity once those are wired in.
    """
    messages = [{"role": "system", "content": _chat_instructions(system)}, *history, {"role": "user", "content": user_message}]
    start = time.monotonic()
    try:
        resp = litellm.completion(
            model=CHAT_MODEL, messages=messages, timeout=LLM_TIMEOUT, num_retries=LLM_RETRIES
        )
    except Exception as exc:
        raise LLMUnavailableError(str(exc)) from exc
    usage = getattr(resp, "usage", None)
    meta = {
        "model": getattr(resp, "model", None) or CHAT_MODEL,
        "latency_ms": int((time.monotonic() - start) * 1000),
        "tokens_prompt": int(getattr(usage, "prompt_tokens", 0) or 0),
        "tokens_completion": int(getattr(usage, "completion_tokens", 0) or 0),
    }
    text = (resp.choices[0].message.content or "").strip()
    if text.startswith(ESCALATE_PREFIX):
        return {"escalate": text[len(ESCALATE_PREFIX):].strip() or "unspecified", **meta}
    lookup_match = ORDER_LOOKUP_RE.match(text)
    if lookup_match:
        return {"order_lookup": f"{lookup_match.group(1)} | {lookup_match.group(2).strip()}", **meta}
    return {"reply": text, **meta}


def _chat_instructions(system: str) -> str:
    return (
        f"{system}\n\nIf you cannot answer from the context above, or the request needs "
        f"human authority (refunds, complaints, account changes), you MUST respond with "
        f'EXACTLY one line: "{ESCALATE_PREFIX} <short reason>" and nothing else — do not ask '
        f"clarifying questions first, do not explain, do not apologize, just escalate "
        f"immediately. Otherwise answer normally.\n\n"
        f"If the visitor asks about the status of an order, first ask them (in the same "
        f"message, conversationally) for their order number and, to verify their identity, "
        f"either their email address or their surname used on the order. Once you have BOTH "
        f'the order number and that identifier in the conversation, respond with EXACTLY one '
        f'line: "{ORDER_LOOKUP_PREFIX} <order number> | <email or surname>" and nothing else — '
        f"no extra words, do not guess or make up order data yourself."
    )


def chat_stream(system: str, history: list[dict], user_message: str):
    """Streaming variant of chat(). A generator that yields ("delta", text) tuples as tokens
    arrive, then one final ("meta", {model, latency_ms, tokens_prompt, tokens_completion}).

    The caller reassembles the text and applies the same ESCALATE_PREFIX convention as chat()
    — it must buffer the first tokens to decide escalation before showing anything. Raises
    LLMUnavailableError if the provider is unreachable (before or mid-stream)."""
    messages = [{"role": "system", "content": _chat_instructions(system)}, *history, {"role": "user", "content": user_message}]
    start = time.monotonic()
    kwargs = dict(model=CHAT_MODEL, messages=messages, timeout=LLM_TIMEOUT, num_retries=LLM_RETRIES, stream=True)
    # Ask for token usage in the stream so streamed replies aren't logged with tokens=0. Not
    # every provider (e.g. Cloudflare Workers AI via litellm) accepts stream_options; if it's
    # rejected we retry once without it and remember, so we never pay the double call again.
    global _stream_usage_supported
    try:
        if _stream_usage_supported:
            stream = litellm.completion(**kwargs, stream_options={"include_usage": True})
        else:
            stream = litellm.completion(**kwargs)
    except Exception as first:
        if _stream_usage_supported:
            try:
                stream = litellm.completion(**kwargs)  # provider likely rejected stream_options
                _stream_usage_supported = False
            except Exception as exc:
                raise LLMUnavailableError(str(exc)) from exc
        else:
            raise LLMUnavailableError(str(first)) from first

    model = CHAT_MODEL
    usage = None
    try:
        for chunk in stream:
            if getattr(chunk, "model", None):
                model = chunk.model
            if getattr(chunk, "usage", None):
                usage = chunk.usage  # some providers send usage only in the final chunk
            choices = getattr(chunk, "choices", None)
            if choices:
                content = getattr(choices[0].delta, "content", None)
                if content:
                    yield ("delta", content)
    except Exception as exc:
        raise LLMUnavailableError(str(exc)) from exc

    yield ("meta", {
        "model": model,
        "latency_ms": int((time.monotonic() - start) * 1000),
        "tokens_prompt": int(getattr(usage, "prompt_tokens", 0) or 0),
        "tokens_completion": int(getattr(usage, "completion_tokens", 0) or 0),
    })
