import json
import logging
from datetime import date, timezone, datetime
from typing import List, Dict, Any, Optional

import tiktoken
import redis.asyncio as redis

from config import settings, MODEL_PRICING, DEFAULT_PRICING

logger = logging.getLogger("ai-firewall.budget")

_redis_pool: Optional[redis.Redis] = None
_encoding: Optional[tiktoken.Encoding] = None


async def get_redis() -> redis.Redis:
    """Return a shared async Redis connection."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _redis_pool


def get_encoding() -> tiktoken.Encoding:
    """Return a cached tiktoken encoding instance."""
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding(settings.TIKTOKEN_ENCODING)
    return _encoding


def _budget_key(user: str) -> str:
    """Redis key for the user's daily spend: budget:{user}:{YYYY-MM-DD}."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"budget:{user}:{today}"


# ── Budget checks ────────────────────────────────────────────────────────────


async def get_spent(user: str) -> float:
    """Return how much the user has spent today (USD)."""
    r = await get_redis()
    val = await r.get(_budget_key(user))
    return float(val) if val else 0.0


async def check_budget(user: str) -> bool:
    """Return True if the user is still within budget."""
    spent = await get_spent(user)
    return spent < settings.DAILY_BUDGET_LIMIT


async def increment_spend(user: str, amount: float) -> float:
    """Add `amount` USD to the user's daily spend. Returns new total."""
    r = await get_redis()
    key = _budget_key(user)
    new_total = await r.incrbyfloat(key, round(amount, 8))
    # Set TTL to 48h so keys auto-expire (covers timezone edge cases)
    await r.expire(key, 48 * 3600)
    logger.info("User %s spend updated: +$%.6f → $%.6f", user, amount, new_total)
    return float(new_total)


# ── Token counting ───────────────────────────────────────────────────────────


def count_tokens_for_messages(messages: List[Dict[str, Any]]) -> int:
    """Count tokens for an OpenAI-style messages list."""
    enc = get_encoding()
    num_tokens = 0
    for msg in messages:
        # Every message has role + content overhead (~4 tokens per message)
        num_tokens += 4
        for key, value in msg.items():
            if isinstance(value, str):
                num_tokens += len(enc.encode(value))
    num_tokens += 2  # priming tokens
    return num_tokens


def count_tokens_text(text: str) -> int:
    """Count tokens for a plain text string."""
    enc = get_encoding()
    return len(enc.encode(text))


# ── Cost calculation ─────────────────────────────────────────────────────────


def get_pricing(model: str):
    """Return (input_price_per_1k, output_price_per_1k) for a model."""
    return MODEL_PRICING.get(model, DEFAULT_PRICING)


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute total cost in USD for a given request."""
    input_price, output_price = get_pricing(model)
    cost = (input_tokens / 1000.0) * input_price + (output_tokens / 1000.0) * output_price
    return cost


# ── SSE output token extraction ──────────────────────────────────────────────


def extract_text_from_sse_chunks(chunks: List[str]) -> str:
    """
    Parse accumulated SSE chunks and extract the assistant's generated text.
    Each chunk follows the format: data: {json}\n\n
    """
    full_text = []
    for chunk in chunks:
        for line in chunk.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
                choices = data.get("choices", [])
                for choice in choices:
                    delta = choice.get("delta", {})
                    content = delta.get("content")
                    if content:
                        full_text.append(content)
            except (json.JSONDecodeError, KeyError):
                continue
    return "".join(full_text)


# ── Cleanup ──────────────────────────────────────────────────────────────────


async def close() -> None:
    """Close the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
