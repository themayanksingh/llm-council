"""OpenRouter API client for making LLM requests."""

import httpx
from typing import List, Dict, Any, Optional
from .config import OPENROUTER_API_URL, OPENROUTER_TIMEOUT


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    api_key: str,
    timeout: float = OPENROUTER_TIMEOUT
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-5.1")
        messages: List of message dicts with 'role' and 'content'
        api_key: OpenRouter API key
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers=headers,
                json=payload
            )
            response.raise_for_status()

            data = response.json()
            message = data['choices'][0]['message']

            return {
                'content': message.get('content'),
                'reasoning_details': message.get('reasoning_details')
            }

    except httpx.TimeoutException:
        print(f"Error querying model {model}: timeout after {timeout}s")
        return None
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            body = "<unavailable>"
        body_preview = (body[:800] + "\u2026") if body and len(body) > 800 else body
        print(
            f"Error querying model {model}: HTTP {e.response.status_code} "
            f"{e.response.reason_phrase or ''} - {body_preview}"
        )
        return None
    except Exception as e:
        print(f"Error querying model {model}: {type(e).__name__}: {e!r}")
        return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    api_key: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model
        api_key: OpenRouter API key

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # Create tasks for all models
    tasks = [query_model(model, messages, api_key) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
