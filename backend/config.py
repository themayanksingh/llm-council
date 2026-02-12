"""Configuration for the LLM Council."""

import os
import time
import hashlib
import httpx
from typing import Any
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key (server-side fallback; primary source is client header)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Default request timeout (seconds) for OpenRouter calls.
OPENROUTER_TIMEOUT = float(os.getenv("OPENROUTER_TIMEOUT", "180"))

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# OpenRouter models list endpoint
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# USD to INR exchange-rate endpoint
USD_INR_RATE_URL = os.getenv("USD_INR_RATE_URL", "https://open.er-api.com/v6/latest/USD")

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Default council members (latest models as of Feb 2026)
DEFAULT_COUNCIL_MODELS = [
    "openai/gpt-5.2",
    "anthropic/claude-sonnet-4.5",
    "google/gemini-3-pro-preview",
    "x-ai/grok-4",
]

# Default chairman model
DEFAULT_CHAIRMAN_MODEL = "google/gemini-3-pro-preview"


def fallback_model_catalog() -> list[dict]:
    """Minimal fallback catalog used when live model fetch is unavailable."""
    fallback_ids = list(dict.fromkeys([*DEFAULT_COUNCIL_MODELS, DEFAULT_CHAIRMAN_MODEL]))
    catalog = []
    for model_id in fallback_ids:
        provider = model_id.split("/")[0] if "/" in model_id else "unknown"
        name = model_id.split("/", 1)[1] if "/" in model_id else model_id
        catalog.append({
            "id": model_id,
            "name": name,
            "provider": provider,
            "context_length": 0,
            "prompt_cost_per_token": 0.0,
            "completion_cost_per_token": 0.0,
        })
    return catalog

# --- Dynamic model fetching with in-memory cache ---
# Cache is keyed by API key hash to avoid leaking one user's catalog to another.
_models_cache: dict[str, dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 600  # 10 minutes

# FX cache
_fx_cache = {
    "rate": None,
    "fetched_at": 0,
}
_FX_CACHE_TTL_SECONDS = 3600  # 1 hour
_FALLBACK_USD_INR_RATE = float(os.getenv("FALLBACK_USD_INR_RATE", "83.0"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely parse string/number values to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _models_cache_key(api_key: str) -> str:
    """Return a non-reversible cache key for API-key scoped model caches."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def fetch_available_models(api_key: str) -> list[dict]:
    """Fetch available models from the OpenRouter API.

    Returns a list of dicts: [{"id": "openai/gpt-5.1", "name": "GPT-5.1", "provider": "OpenAI", "context_length": 128000}, ...]
    Results are cached in memory for 10 minutes.
    """
    if not api_key:
        return fallback_model_catalog()

    now = time.time()
    cache_key = _models_cache_key(api_key)
    cached = _models_cache.get(cache_key)
    if cached is not None and (now - cached["fetched_at"]) < _CACHE_TTL_SECONDS:
        return cached["data"]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                OPENROUTER_MODELS_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            raw = response.json()

        models = []
        for m in raw.get("data", []):
            model_id = m.get("id", "")
            name = m.get("name", model_id)
            # Derive provider from the id prefix (e.g. "openai/gpt-5.1" -> "openai")
            provider = model_id.split("/")[0] if "/" in model_id else "unknown"
            pricing = m.get("pricing") or {}
            models.append({
                "id": model_id,
                "name": name,
                "provider": provider,
                "context_length": m.get("context_length", 0),
                "prompt_cost_per_token": _safe_float(pricing.get("prompt")),
                "completion_cost_per_token": _safe_float(pricing.get("completion")),
            })

        _models_cache[cache_key] = {
            "data": models,
            "fetched_at": now,
        }
        return models

    except Exception as e:
        print(f"Failed to fetch models from OpenRouter: {e}")
        # Return cache even if stale, or fallback catalog.
        if cached is not None:
            return cached["data"]
        return fallback_model_catalog()


async def fetch_usd_to_inr_rate() -> dict:
    """Fetch USD->INR FX rate with 1-hour cache and fallback."""
    now = time.time()
    if _fx_cache["rate"] is not None and (now - _fx_cache["fetched_at"]) < _FX_CACHE_TTL_SECONDS:
        return {
            "usd_inr": _fx_cache["rate"],
            "source": USD_INR_RATE_URL,
            "fetched_at": int(_fx_cache["fetched_at"]),
            "stale": False,
        }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(USD_INR_RATE_URL)
            response.raise_for_status()
            data = response.json()

        rate = _safe_float((data.get("rates") or {}).get("INR"), 0.0)
        if rate <= 0:
            raise ValueError("USD_INR rate missing or invalid")

        _fx_cache["rate"] = rate
        _fx_cache["fetched_at"] = now
        return {
            "usd_inr": rate,
            "source": USD_INR_RATE_URL,
            "fetched_at": int(now),
            "stale": False,
        }
    except Exception as e:
        print(f"Failed to fetch USD->INR rate: {e}")
        # Use stale cache if available; otherwise hard fallback.
        if _fx_cache["rate"] is not None:
            return {
                "usd_inr": _fx_cache["rate"],
                "source": USD_INR_RATE_URL,
                "fetched_at": int(_fx_cache["fetched_at"]),
                "stale": True,
            }
        return {
            "usd_inr": _FALLBACK_USD_INR_RATE,
            "source": "fallback",
            "fetched_at": int(now),
            "stale": True,
        }
