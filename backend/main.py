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
    DEFAULT_COUNCIL_MODELS,
    DEFAULT_CHAIRMAN_MODEL,
    fetch_available_models,
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


# --- Request/Response models ---

class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    council_models: Optional[List[str]] = None
    chairman_model: Optional[str] = None


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
    """Return available models from OpenRouter + defaults."""
    api_key = get_api_key(request)
    models = await fetch_available_models(api_key)
    return {
        "models": models,
        "defaults": {
            "council": DEFAULT_COUNCIL_MODELS,
            "chairman": DEFAULT_CHAIRMAN_MODEL,
        },
    }


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
    council_models = request_body.council_models or DEFAULT_COUNCIL_MODELS
    chairman_model = request_body.chairman_model or DEFAULT_CHAIRMAN_MODEL

    # Validate
    if len(council_models) < 2:
        raise HTTPException(status_code=400, detail="At least 2 council models are required.")
    if not chairman_model:
        raise HTTPException(status_code=400, detail="Chairman model is required.")

    is_first_message = len(conversation["messages"]) == 0
    storage.add_user_message(conversation_id, request_body.content)

    if is_first_message:
        title = await generate_conversation_title(request_body.content, api_key)
        storage.update_conversation_title(conversation_id, title)

    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request_body.content, council_models, chairman_model, api_key
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
    council_models = request_body.council_models or DEFAULT_COUNCIL_MODELS
    chairman_model = request_body.chairman_model or DEFAULT_CHAIRMAN_MODEL

    # Validate
    if len(council_models) < 2:
        raise HTTPException(status_code=400, detail="At least 2 council models are required.")
    if not chairman_model:
        raise HTTPException(status_code=400, detail="Chairman model is required.")

    is_first_message = len(conversation["messages"]) == 0

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
                request_body.content, council_models, api_key
            )
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            if not stage1_results:
                yield f"data: {json.dumps({'type': 'error', 'message': 'All models failed to respond. Please try again.'})}\n\n"
                return

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(
                request_body.content, stage1_results, council_models, api_key
            )
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(
                request_body.content, stage1_results, stage2_results,
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
