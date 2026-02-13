"""Configuration for the LLM Council."""

import os
import time
import hashlib
import re
from datetime import datetime
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

# Provider priority: which model ID patterns define each provider's flagship family.
# Pattern order matters only when timestamps/versions are equal.
PROVIDER_LATEST_PATTERNS = {
    "openai": [
        "gpt-5",  # Treat GPT-5 family alias as flagship track; timestamp decides latest
        "gpt-4o",
        "gpt-4",
        "o3",
        "o1",
    ],
    "google": [
        "gemini-3-pro",
        "gemini-3",
        "gemini-2.5-pro",
        "gemini-2.5",
        "gemini-2",
        "gemini-1.5-pro",
        "gemini-1.5",
    ],
    "anthropic": [
        "claude-sonnet-4",
        "claude-opus-4",
        "claude-3.7",
        "claude-3.5",
        "claude-3",
        "claude-opus",
    ],
    "x-ai": [
        "grok-4",
        "grok-3",
        "grok-2",
        "grok",
    ],
}

# Provider-specific variants that should not be treated as flagship defaults
# unless there is no better candidate available.
PROVIDER_NON_FLAGSHIP_TOKENS = {
    "openai": [
        "audio",
        "realtime",
        "codex",
        "transcrib",
        "tts",
        "whisper",
        "embed",
        "moderation",
        "guard",
        "search",
        "image",
        "vision",
        "mini",
        "nano",
    ],
    "google": [
        "embedding",
        "tts",
        "stt",
        "transcrib",
        "lite",
    ],
    "anthropic": [
        "haiku",
    ],
    "x-ai": [
        "mini",
        "vision",
        "image",
    ],
}

PROVIDER_ORDER = ["openai", "google", "anthropic", "x-ai"]
CHAIRMAN_PROVIDER_PREFERENCE = ["google", "openai", "anthropic", "x-ai"]
PROVIDER_FALLBACK_IDS = {
    "openai": "openai/gpt-5.2",
    "google": "google/gemini-3-pro-preview",
    "anthropic": "anthropic/claude-sonnet-4.5",
    "x-ai": "x-ai/grok-4",
}


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely parse string/number values to int."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_iso_to_epoch(value: Any) -> int:
    """Parse an ISO datetime string to epoch seconds."""
    if not isinstance(value, str) or not value.strip():
        return 0
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(normalized).timestamp())
    except Exception:
        return 0


def _extract_model_timestamp(model: dict[str, Any]) -> int:
    """Extract best-effort model release timestamp from known fields."""
    for key in ("created", "created_at", "published_at", "updated_at"):
        value = model.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            parsed = _parse_iso_to_epoch(value)
            if parsed:
                return parsed
    return 0


def _parse_model_version(model_id: str) -> tuple[int, ...]:
    """Extract numeric version parts from model id for tie-breaking."""
    nums = re.findall(r"\d+", (model_id or "").lower())
    return tuple(_safe_int(n, 0) for n in nums[:4]) or (0,)


def _is_non_flagship_variant(provider: str, model_id: str) -> bool:
    """Return True if model ID looks like a non-flagship variant."""
    name = (model_id or "").lower()
    tokens = PROVIDER_NON_FLAGSHIP_TOKENS.get((provider or "").lower(), [])
    return any(token in name for token in tokens)


def get_latest_models_by_provider(models: list[dict]) -> dict[str, str]:
    """Return a dict mapping provider -> latest model ID for each of the 4 providers."""
    latest = {}
    for provider in PROVIDER_ORDER:
        patterns = PROVIDER_LATEST_PATTERNS.get(provider, [])
        # Find models matching this provider
        provider_models = [m for m in models if m.get("provider", "").lower() == provider.lower()]
        if not provider_models:
            continue

        # Prefer likely flagship variants first; fall back to all provider models if none remain.
        flagship_pool = [
            m for m in provider_models
            if not _is_non_flagship_variant(provider, m.get("id", ""))
        ]
        candidate_pool = flagship_pool or provider_models

        def pattern_priority(model_id: str) -> int:
            model_id = (model_id or "").lower()
            for idx, pattern in enumerate(patterns):
                if model_id == pattern or model_id.startswith(f"{pattern}-") or pattern in model_id:
                    return len(patterns) - idx
            return 0

        candidates = sorted(
            candidate_pool,
            key=lambda m: (
                pattern_priority(m.get("id", "")),
                _parse_model_version(m.get("id", "")),
                _extract_model_timestamp(m),
                _safe_int(m.get("context_length"), 0),
                (m.get("id", "") or "").lower(),
            ),
            reverse=True,
        )
        latest[provider] = candidates[0].get("id")

    return latest


def get_default_council_models(models: list[dict]) -> list[str]:
    """Get exactly 4 default council models (one from each provider)."""
    latest_by_provider = get_latest_models_by_provider(models)
    defaults = []
    for provider in PROVIDER_ORDER:
        candidate = latest_by_provider.get(provider) or PROVIDER_FALLBACK_IDS[provider]
        if candidate not in defaults:
            defaults.append(candidate)
    return defaults


def get_default_chairman_model(models: list[dict]) -> str:
    """Get the default chairman model (uses the best available)."""
    latest_by_provider = get_latest_models_by_provider(models)
    for provider in CHAIRMAN_PROVIDER_PREFERENCE:
        if provider in latest_by_provider:
            return latest_by_provider[provider]
    # Final fallback: first council default.
    return get_default_council_models(models)[0]


def fallback_model_catalog() -> list[dict]:
    """Minimal fallback catalog used when live model fetch is unavailable."""
    fallback_ids = [PROVIDER_FALLBACK_IDS[p] for p in PROVIDER_ORDER]
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
            "created_at": 0,
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
                "created_at": _extract_model_timestamp(m),
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
