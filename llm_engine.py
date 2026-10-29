"""
ZeroLeak OS - Phase 2: Gemini LLM Wrapper.

One shared pool of 3 Gemini clients. Every agent owns a primary key, and the
other two keys act as its fallbacks:

    sales       -> GEMINI_SALES_API_KEY -> GEMINI_PROC_API_KEY  -> GEMINI_API_KEY
    procurement -> GEMINI_PROC_API_KEY  -> GEMINI_SALES_API_KEY -> GEMINI_API_KEY
    judge       -> GEMINI_API_KEY       -> GEMINI_SALES_API_KEY -> GEMINI_PROC_API_KEY

Failover rules (per call):
  * 429 rate limit   -> key cools down for RATE_LIMIT_COOLDOWN_S; try next key.
  * invalid key/auth -> key disabled for the rest of the process; try next key.
  * 408 / 5xx        -> try next key, no cooldown (usually transient).
  * network error    -> try next key.
  * every key failed with a network error or 408/5xx (DNS blip, or the model is
    overloaded for all keys at once) -> wait, then retry the whole chain
    (RETRY_DELAYS_S), until RETRY_WINDOW_S has passed since the call started.
  * anything else    -> raised immediately (a bad prompt fails on every key).
Keys in cooldown are tried last rather than skipped, so a call only fails when
all usable keys have failed.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger("zeroleak.llm")

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
REQUEST_TIMEOUT_MS = 30_000  # short, so a hung key fails over instead of stalling the Boardroom
RATE_LIMIT_COOLDOWN_S = 60.0
# All keys share one host and one model, so a DNS blip or a model overload (504s) fails every key at
# once: wait, then retry the whole chain. Live 2026-10-26: a DNS outage outlasted the old 2s + 5s, and a
# Flash Lite overload gave 504 on all 3 keys; both crashed the match.
RETRY_DELAYS_S = (2.0, 5.0, 15.0, 30.0)
RETRY_WINDOW_S = 180.0  # no new round starts after this long, so the Boardroom is never silent for ages

# Agent -> key env names, primary first, then fallback order.
AGENT_KEY_CHAINS = {
    "sales":       ("GEMINI_SALES_API_KEY", "GEMINI_PROC_API_KEY", "GEMINI_API_KEY"),
    "procurement": ("GEMINI_PROC_API_KEY", "GEMINI_SALES_API_KEY", "GEMINI_API_KEY"),
    "judge":       ("GEMINI_API_KEY", "GEMINI_SALES_API_KEY", "GEMINI_PROC_API_KEY"),
}

_FAILOVER_CODES = {408, 429, 500, 502, 503, 504}
_AUTH_CODES = {401, 403}


class LLMError(RuntimeError):
    """Raised when no key can produce a usable response."""


@dataclass
class _KeySlot:
    env_name: str
    client: genai.Client
    cooldown_until: float = 0.0
    disabled: bool = False

    def is_cooling(self) -> bool:
        return time.monotonic() < self.cooldown_until


_pool: dict[str, _KeySlot] | None = None


def _get_pool() -> dict[str, _KeySlot]:
    global _pool
    if _pool is None:
        env_names = {name for chain in AGENT_KEY_CHAINS.values() for name in chain}
        http_options = types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
        _pool = {
            name: _KeySlot(name, genai.Client(api_key=os.environ[name], http_options=http_options))
            for name in sorted(env_names)
            if os.getenv(name)
        }
        if not _pool:
            raise LLMError(f"No Gemini API keys found in .env (expected: {sorted(env_names)})")
        for name in sorted(env_names - _pool.keys()):
            logger.warning("%s is not set; agents will use the remaining keys.", name)
    return _pool


def _is_auth_error(e: errors.APIError) -> bool:
    # Gemini reports a bad API key as 400 INVALID_ARGUMENT, not 401.
    return e.code in _AUTH_CODES or (e.code == 400 and "API_KEY_INVALID" in str(e))


def _ordered_slots(agent: str) -> list[_KeySlot]:
    pool = _get_pool()
    chain = [pool[name] for name in AGENT_KEY_CHAINS[agent] if name in pool]
    usable = [slot for slot in chain if not slot.disabled]
    return [s for s in usable if not s.is_cooling()] + [s for s in usable if s.is_cooling()]


async def generate(
    agent: str,
    prompt: str,
    system_instruction: str | None = None,
    json_mode: bool = False,
    temperature: float | None = None,
) -> str:
    """Send a prompt as `agent` ('sales' | 'procurement' | 'judge') and return the reply text."""
    if agent not in AGENT_KEY_CHAINS:
        raise ValueError(f"Unknown agent {agent!r}; expected one of {list(AGENT_KEY_CHAINS)}")

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )

    last_error: Exception | None = None
    started = time.monotonic()
    for delay in (0.0, *RETRY_DELAYS_S):
        if delay:
            if time.monotonic() - started + delay > RETRY_WINDOW_S:
                break
            logger.warning("No key could serve %r (network/overload); retrying chain in %.0fs.", agent, delay)
            await asyncio.sleep(delay)

        slots = _ordered_slots(agent)
        if not slots:
            raise LLMError(f"All Gemini keys are disabled; cannot serve {agent!r}.")

        transient_failures = 0  # network errors and 408/5xx: worth retrying the whole chain
        for slot in slots:
            try:
                response = await slot.client.aio.models.generate_content(
                    model=MODEL, contents=prompt, config=config
                )
            except httpx.TransportError as e:
                transient_failures += 1
                logger.warning("%s network error (%s); trying next key.", slot.env_name, type(e).__name__)
                last_error = e
                continue
            except errors.APIError as e:
                if _is_auth_error(e):
                    slot.disabled = True
                    logger.error("%s rejected (%s); disabled for this session.", slot.env_name, e.code)
                elif e.code == 429:
                    slot.cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN_S
                    logger.warning("%s rate-limited; cooling down %.0fs.", slot.env_name, RATE_LIMIT_COOLDOWN_S)
                elif e.code in _FAILOVER_CODES:
                    transient_failures += 1
                    logger.warning("%s failed with %s; trying next key.", slot.env_name, e.code)
                else:
                    raise
                last_error = e
                continue

            if not response.text:
                finish = response.candidates[0].finish_reason if response.candidates else None
                raise LLMError(f"Empty response for {agent!r} (finish_reason={finish}, "
                               f"prompt_feedback={response.prompt_feedback})")
            logger.info("%s served by %s", agent, slot.env_name)
            return response.text

        if transient_failures < len(slots):  # some key failed for a lasting reason (quota, auth)
            break

    raise LLMError(f"All Gemini keys failed for {agent!r}.") from last_error


async def aclose() -> None:
    """Close the async HTTP sessions held by the clients."""
    global _pool
    if _pool:
        await asyncio.gather(*(slot.client.aio.aclose() for slot in _pool.values()))
    _pool = None


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    try:
        for agent in AGENT_KEY_CHAINS:
            reply = await generate(agent, "Reply with exactly the word: OK", temperature=0)
            print(f"[{agent}] -> {reply.strip()!r}")
        reply = await generate(
            "judge", 'Return JSON {"status": "ok"} and nothing else.', json_mode=True, temperature=0
        )
        print(f"[judge json] -> {reply.strip()}")
    finally:
        await aclose()


if __name__ == "__main__":
    asyncio.run(_main())
