"""Groq chat-completions client (OpenAI-compatible, free tier).

Free-tier budgets are per model and per minute (8,000 tokens/min at the time of
writing), and they count *output* tokens including the model's hidden reasoning
tokens. A JD match is two calls and used to spend ~6,400 tokens, which meant
roughly one match per minute before a 429. Three things keep it under budget:

* `reasoning_effort="low"` on structured calls - the JSON schema does the
  thinking, so the model does not need to narrate its way there.
* Easy work runs on a smaller model, which has its own separate budget.
* Ceilings on `max_tokens` sized to the response we actually want.

When a 429 does happen, the reset time comes from Groq's own headers rather than
a guess, and a short wait is retried automatically.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

API_URL = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# A wait we will sit through rather than surface. A match already takes ~15s, so
# a few more seconds beats making the user click again; beyond this, telling
# them the real number is more useful than a long silent hang.
MAX_AUTO_RETRY_WAIT = 25.0


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured or the provider refuses the call."""


class RateLimited(LLMUnavailable):
    """A 429. Carries the provider's own reset estimate, in seconds."""

    def __init__(self, message: str, retry_after: float | None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_duration(value: str | None) -> float | None:
    """Groq reports resets as "53.28s", "1m26.4s", or "2m". Convert to seconds."""
    if not value:
        return None
    total = 0.0
    found = False
    for amount, unit in re.findall(r"([\d.]+)\s*(ms|s|m|h)", value):
        try:
            number = float(amount)
        except ValueError:
            continue
        found = True
        total += number * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    if found:
        return total
    try:  # a bare number means seconds (the retry-after header)
        return float(value)
    except ValueError:
        return None


def _retry_delay(resp: httpx.Response) -> float | None:
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        delay = _parse_duration(resp.headers.get(header))
        if delay is not None:
            return delay
    return None


def _describe_wait(seconds: float | None) -> str:
    if seconds is None:
        return "Wait about a minute and try again."
    if seconds < 60:
        return f"Try again in about {max(1, round(seconds))} seconds."
    return f"Try again in about {round(seconds / 60)} minute(s)."


async def complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 1200,
    json_mode: bool = False,
    model: str | None = None,
    reasoning_effort: str | None = None,
    _retried: bool = False,
) -> str:
    settings = get_settings()
    if not settings.llm_enabled:
        raise LLMUnavailable(
            "No GROQ_API_KEY configured. Add a free key from https://console.groq.com/keys "
            "to backend/.env to enable AI answers."
        )

    chosen = model or settings.groq_model
    payload: dict = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                API_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            )
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Could not reach the model provider: {exc}") from exc

    if resp.status_code == 401:
        raise LLMUnavailable("The GROQ_API_KEY was rejected. Check the key in backend/.env.")

    if resp.status_code == 429:
        delay = _retry_delay(resp)
        # One automatic retry for a short cool-off, so a burst self-heals
        # instead of bouncing the user back with an error they can only fix by
        # waiting anyway.
        if not _retried and delay is not None and delay <= MAX_AUTO_RETRY_WAIT:
            log.info("Rate limited on %s; retrying in %.1fs", chosen, delay)
            await asyncio.sleep(delay + 0.5)
            return await complete(
                system,
                user,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                model=model,
                reasoning_effort=reasoning_effort,
                _retried=True,
            )
        raise RateLimited(
            f"Groq's free tier allows a limited number of tokens per minute, and this "
            f"request went over. {_describe_wait(delay)}",
            delay,
        )

    if resp.status_code == 404:
        raise LLMUnavailable(
            f"The model '{chosen}' is not available on this account - it was most likely "
            "retired. Run `curl https://api.groq.com/openai/v1/models -H \"Authorization: "
            "Bearer $GROQ_API_KEY\"` to see current model IDs, then update GROQ_MODEL in "
            "backend/.env."
        )
    if resp.status_code >= 400:
        log.error("Groq error %s: %s", resp.status_code, resp.text[:500])
        raise LLMUnavailable(f"Model provider returned {resp.status_code}.")

    data = resp.json()
    usage = data.get("usage") or {}
    if usage:
        log.info(
            "%s: %s prompt + %s completion = %s tokens (%s left this minute)",
            chosen,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
            resp.headers.get("x-ratelimit-remaining-tokens", "?"),
        )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise LLMUnavailable("Malformed response from the model provider.") from exc


async def complete_json(
    system: str,
    user: str,
    *,
    max_tokens: int = 2500,
    model: str | None = None,
) -> dict:
    """Ask for JSON and parse it defensively.

    Temperature 0 to keep scoring as repeatable as the provider allows, and low
    reasoning effort because a strict output schema already constrains the work.
    """
    raw = await complete(
        system,
        user,
        temperature=0.0,
        max_tokens=max_tokens,
        json_mode=True,
        model=model,
        reasoning_effort="low",
    )
    return parse_json(raw)


def parse_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Models occasionally wrap JSON in prose or a ```json fence; salvage the object.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start != -1 and end > start else None
    if candidate:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    raise LLMUnavailable("The model did not return valid JSON. Try again.")
