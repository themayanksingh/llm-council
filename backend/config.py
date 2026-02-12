"""Configuration for the LLM Council."""

import os
import time
import httpx
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

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Default council members
DEFAULT_COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Default chairman model
DEFAULT_CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# --- Dynamic model fetching with in-memory cache ---

_models_cache = {
    "data": None,
    "fetched_at": 0,
}
_CACHE_TTL_SECONDS = 600  # 10 minutes


async def fetch_available_models(api_key: str) -> list[dict]:
    """Fetch available models from the OpenRouter API.

    Returns a list of dicts: [{"id": "openai/gpt-5.1", "name": "GPT-5.1", "provider": "OpenAI", "context_length": 128000}, ...]
    Results are cached in memory for 10 minutes.
    """
    now = time.time()
    if _models_cache["data"] is not None and (now - _models_cache["fetched_at"]) < _CACHE_TTL_SECONDS:
        return _models_cache["data"]

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
            models.append({
                "id": model_id,
                "name": name,
                "provider": provider,
                "context_length": m.get("context_length", 0),
            })

        _models_cache["data"] = models
        _models_cache["fetched_at"] = now
        return models

    except Exception as e:
        print(f"Failed to fetch models from OpenRouter: {e}")
        # Return cache even if stale, or empty list
        if _models_cache["data"] is not None:
            return _models_cache["data"]
        return []
