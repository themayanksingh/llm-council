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

# Provider priority: which model ID patterns to consider as "latest" for each provider
# Ordered by preference - first match wins
PROVIDER_LATEST_PATTERNS = {
    "openai": [
        "gpt-5.2", "gpt-5.1", "gpt-5",  # GPT-5 series first
        "gpt-4o", "gpt-4",  # GPT-4 fallback
        "o3", "o1",  # O-series
    ],
    "google": [
        "gemini-3-pro", "gemini-3",  # Gemini 3
        "gemini-2.5-pro", "gemini-2.5", "gemini-2",  # Gemini 2
        "gemini-1.5-pro", "gemini-1.5",  # Gemini 1.5 fallback
    ],
    "anthropic": [
        "claude-sonnet-4.5", "claude-sonnet-4",  # Sonnet 4
        "claude-3.7", "claude-3.5", "claude-3",  # Claude 3 series
        "claude-opus-4", "claude-opus-3", "claude-opus",  # Opus fallback
    ],
    "x-ai": [
        "grok-4", "grok-3", "grok-2",  # Grok series
        "grok-beta", "grok",  # Grok beta fallback
    ],
}


def get_latest_models_by_provider(models: list[dict]) -> dict[str, str]:
    """Return a dict mapping provider -> latest model ID for each of the 4 providers."""
    latest = {}
    for provider, patterns in PROVIDER_LATEST_PATTERNS.items():
        # Find models matching this provider
        provider_models = [m for m in models if m.get("provider", "").lower() == provider.lower()]
        if not provider_models:
            continue
        
        # Find best match based on patterns
        for pattern in patterns:
            for m in provider_models:
                model_id = m.get("id", "").lower()
                # Exact match or prefix match (e.g., "gpt-5.2" matches "gpt-5.2-pro")
                if model_id == pattern or model_id.startswith(pattern + "-") or model_id.startswith(pattern):
                    latest[provider] = m.get("id")
                    break
            if provider in latest:
                break
        
        # Fallback: just pick the first one alphabetically if no pattern matches
        if provider not in latest and provider_models:
            sorted_models = sorted(provider_models, key=lambda m: m.get("id", ""), reverse=True)
            latest[provider] = sorted_models[0].get("id")
    
    return latest


def get_default_council_models(models: list[dict]) -> list[str]:
    """Get the 4 default council models (one from each provider)."""
    latest_by_provider = get_latest_models_by_provider(models)
    # Return in order: OpenAI, Google, Anthropic, x-ai
    order = ["openai", "google", "anthropic", "x-ai"]
    return [latest_by_provider.get(p) for p in order if latest_by_provider.get(p)]


def get_default_chairman_model(models: list[dict]) -> str:
    """Get the default chairman model (uses the best available)."""
    latest_by_provider = get_latest_models_by_provider(models)
    # Prefer Anthropic for chairman, then OpenAI, then Google, then x-ai
    for provider in ["anthropic", "openai", "google", "x-ai"]:
        if provider in latest_by_provider:
            return latest_by_provider[provider]
    return ""


def fallback_model_catalog() -> list[dict]:
    """Minimal fallback catalog used when live model fetch is unavailable."""
    # Hardcoded fallback IDs for when API is unavailable
    fallback_ids = [
        "openai/gpt-5.2",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-3-pro-preview",
        "x-ai/grok-4",
    ]
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
