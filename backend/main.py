"""FastAPI backend for LLM Council."""

import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from .config import (
    OPENROUTER_API_KEY,
    get_default_council_models,
    get_default_chairman_model,
    fetch_available_models,
    fetch_usd_to_inr_rate,
)
from .council import (
    run_full_council,
    generate_conversation_title,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage3_synthesize_final,
    calculate_aggregate_rankings,
)

app = FastAPI(title="LLM Council API")

# CORS: localhost for dev + configurable production origins
_origins = ["http://localhost:5173", "http://localhost:3000"]
_extra = os.getenv("ALLOWED_ORIGINS", "")
if _extra:
    _origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Helpers ---

def get_api_key(request: Request) -> str:
    """Extract API key from request header, fall back to env."""
    key = request.headers.get("X-OpenRouter-Key")
    if not key:
        key = OPENROUTER_API_KEY
    if not key:
        raise HTTPException(status_code=401, detail="API key required. Set it in Settings.")
    return key


def validate_model_selection(
    council_models: Optional[List[str]],
    chairman_model: Optional[str],
    available_model_ids: set[str],
) -> tuple[List[str], str]:
    """Validate and normalize selected council/chairman models."""
    selected_council = list(dict.fromkeys(council_models or DEFAULT_COUNCIL_MODELS))
    selected_chairman = chairman_model or DEFAULT_CHAIRMAN_MODEL

    if len(selected_council) < 2:
        raise HTTPException(status_code=400, detail="At least 2 council models are required.")
    if not selected_chairman:
        raise HTTPException(status_code=400, detail="Chairman model is required.")

    # If model catalog is available, validate IDs strictly.
    if available_model_ids:
        unknown_council = [m for m in selected_council if m not in available_model_ids]
        if unknown_council:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown council model(s): {', '.join(unknown_council)}",
            )
        if selected_chairman not in available_model_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown chairman model: {selected_chairman}",
            )

    return selected_council, selected_chairman


def _truncate_text(text: str, max_chars: int = 1800) -> str:
    """Truncate long text before injecting it into council context."""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."


def build_contextual_query(user_query: str, prior_messages: List[Dict[str, Any]]) -> str:
    """Build a contextual prompt from recent conversation history."""
    if not prior_messages:
        return user_query

    max_messages = int(os.getenv("COUNCIL_CONTEXT_MESSAGES", "8"))
    recent = prior_messages[-max_messages:]

    history_lines = []
    for message in recent:
        role = message.get("role")
        if role == "user":
            content = (message.get("content") or "").strip()
            if content:
                history_lines.append(f"User: {_truncate_text(content)}")
            continue

        if role == "assistant":
            stage3 = message.get("stage3") or {}
            response = (stage3.get("response") if isinstance(stage3, dict) else "") or ""
            response = response.strip()
            if response:
                history_lines.append(f"Assistant: {_truncate_text(response)}")

    if not history_lines:
        return user_query

    history_text = "\n\n".join(history_lines)
    return (
        "Use the following conversation context to answer the latest question.\n"
        "Focus on the latest user question, but keep continuity with prior turns when relevant.\n\n"
        f"Conversation so far:\n{history_text}\n\n"
        f"Latest user question:\n{user_query}"
    )


# --- Request/Response models ---

class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    council_models: Optional[List[str]] = None
    chairman_model: Optional[str] = None


class RenameConversationRequest(BaseModel):
    """Request to rename a conversation."""
    title: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


# --- Endpoints ---

@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/models")
async def get_available_models(request: Request):
    """Return available models from OpenRouter + dynamic defaults (latest from each provider)."""
    api_key = get_api_key(request)
    models = await fetch_available_models(api_key)
    # Dynamically compute latest defaults from fetched models
    defaults = {
        "council": get_default_council_models(models),
        "chairman": get_default_chairman_model(models),
    }
    return {
        "models": models,
        "defaults": defaults,
    }


@app.get("/api/fx/usd-inr")
async def get_usd_inr_rate():
    """Return the latest cached USD->INR exchange rate."""
    return await fetch_usd_to_inr_rate()


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationMetadata)
async def rename_conversation(conversation_id: str, request_body: RenameConversationRequest):
    """Rename an existing conversation."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    title = request_body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty.")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail="Title must be 120 characters or fewer.")

    storage.update_conversation_title(conversation_id, title)
    updated = storage.get_conversation(conversation_id)
    return {
        "id": updated["id"],
        "created_at": updated["created_at"],
        "title": updated.get("title", "New Conversation"),
        "message_count": len(updated.get("messages", [])),
    }


@app.post("/api/conversations/{conversation_id}/rename", response_model=ConversationMetadata)
async def rename_conversation_post(conversation_id: str, request_body: RenameConversationRequest):
    """Rename an existing conversation (POST fallback for restricted clients)."""
    return await rename_conversation(conversation_id, request_body)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """Delete a conversation."""
    deleted = storage.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted", "id": conversation_id}


@app.post("/api/conversations/{conversation_id}/delete")
async def delete_conversation_post(conversation_id: str):
    """Delete a conversation (POST fallback for restricted clients)."""
    return await delete_conversation(conversation_id)


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(
    conversation_id: str,
    request_body: SendMessageRequest,
    request: Request,
):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    api_key = get_api_key(request)
    available_models = await fetch_available_models(api_key)
    available_model_ids = {m.get("id", "") for m in available_models if m.get("id")}
    council_models, chairman_model = validate_model_selection(
        request_body.council_models,
        request_body.chairman_model,
        available_model_ids,
    )

    is_first_message = len(conversation["messages"]) == 0
    council_query = build_contextual_query(
        request_body.content,
        conversation.get("messages", []),
    )
    storage.add_user_message(conversation_id, request_body.content)

    if is_first_message:
        title = await generate_conversation_title(request_body.content, api_key)
        storage.update_conversation_title(conversation_id, title)

    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        council_query, council_models, chairman_model, api_key
    )

    storage.add_assistant_message(conversation_id, stage1_results, stage2_results, stage3_result)

    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata,
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(
    conversation_id: str,
    request_body: SendMessageRequest,
    request: Request,
):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    api_key = get_api_key(request)
    available_models = await fetch_available_models(api_key)
    available_model_ids = {m.get("id", "") for m in available_models if m.get("id")}
    council_models, chairman_model = validate_model_selection(
        request_body.council_models,
        request_body.chairman_model,
        available_model_ids,
    )

    is_first_message = len(conversation["messages"]) == 0
    council_query = build_contextual_query(
        request_body.content,
        conversation.get("messages", []),
    )

    async def event_generator():
        try:
            storage.add_user_message(conversation_id, request_body.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(
                    generate_conversation_title(request_body.content, api_key)
                )

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(
                council_query, council_models, api_key
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            if not stage1_results:
                yield f"data: {json.dumps({'type': 'error', 'message': 'All models failed to respond. Please try again.'})}\n\n"
                return

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(
                council_query, stage1_results, council_models, api_key
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                council_query, stage1_results, stage2_results,
                chairman_model, api_key
            )
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id, stage1_results, stage2_results, stage3_result
            )

            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
