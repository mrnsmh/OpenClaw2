from pydantic_settings import BaseSettings
from typing import Dict, Tuple


class Settings(BaseSettings):
    # Internal API key used by clients to authenticate with the proxy
    INTERNAL_API_KEY: str = "changeme-internal-key"

    # Upstream provider base URL (OpenRouter by default)
    UPSTREAM_BASE_URL: str = "https://openrouter.ai/api"

    # Upstream provider API key
    UPSTREAM_API_KEY: str = ""

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Daily budget limit per user (in USD)
    DAILY_BUDGET_LIMIT: float = 5.0

    # Default tiktoken encoding to use
    TIKTOKEN_ENCODING: str = "cl100k_base"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

# Model pricing: (input_price_per_1k_tokens, output_price_per_1k_tokens) in USD
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.0025, 0.0100),
    "gpt-4o-mini": (0.000150, 0.000600),
    "gpt-4-turbo": (0.0100, 0.0300),
    "gpt-4": (0.0300, 0.0600),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    # Anthropic
    "claude-3-5-sonnet-20241022": (0.0030, 0.0150),
    "claude-3-5-haiku-20241022": (0.0008, 0.0040),
    "claude-3-opus-20240229": (0.0150, 0.0750),
    # OpenRouter prefixed
    "openai/gpt-4o": (0.0025, 0.0100),
    "openai/gpt-4o-mini": (0.000150, 0.000600),
    "anthropic/claude-3.5-sonnet": (0.0030, 0.0150),
    "anthropic/claude-3.5-haiku": (0.0008, 0.0040),
    "anthropic/claude-3-opus": (0.0150, 0.0750),
}

# Fallback pricing for unknown models (conservative estimate)
DEFAULT_PRICING: Tuple[float, float] = (0.0100, 0.0300)
