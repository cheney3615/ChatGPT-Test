"""FastAPI application for the ChatGPT-like conversation service."""

import uuid
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import (
    ConversationListItem,
    ConversationListResponse,
    CreateConversationRequest,
    CreateConversationResponse,
    HealthResponse,
    MessageHistoryResponse,
    MessageResponse,
    MessageRole,
    SendMessageRequest,
)
from app.store import store

app = FastAPI(
    title="ChatGPT-Test API",
    version=settings.app_version,
    description="Backend service for a ChatGPT-like conversation system",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Demo user ID (in production, extracted from JWT)
DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ── Health ───────────────────────────────────────────────────────────────────


@app.get("/api/v1/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        timestamp=datetime.utcnow(),
    )


@app.get("/api/v1/health/ready", response_model=HealthResponse, tags=["System"])
async def readiness_check():
    return HealthResponse(
        status="ready",
        version=settings.app_version,
        timestamp=datetime.utcnow(),
    )


# ── Conversations ────────────────────────────────────────────────────────────


@app.post(
    "/api/v1/conversations",
    response_model=CreateConversationResponse,
    status_code=201,
    tags=["Conversations"],
)
async def create_conversation(req: CreateConversationRequest):
    conv = store.create_conversation(
        user_id=DEMO_USER_ID,
        title=req.title,
        model=req.model,
        system_prompt=req.system_prompt,
    )
    return CreateConversationResponse(
        id=conv.id,
        title=conv.title,
        model=conv.model,
        created_at=conv.created_at,
    )


@app.get(
    "/api/v1/conversations",
    response_model=ConversationListResponse,
    tags=["Conversations"],
)
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    convs, total = store.list_conversations(
        user_id=DEMO_USER_ID, page=page, page_size=page_size
    )
    return ConversationListResponse(
        conversations=[
            ConversationListItem(
                id=c.id, title=c.title, model=c.model, updated_at=c.updated_at
            )
            for c in convs
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@app.get(
    "/api/v1/conversations/{conv_id}",
    response_model=CreateConversationResponse,
    tags=["Conversations"],
)
async def get_conversation(conv_id: uuid.UUID):
    conv = store.get_conversation(conv_id, DEMO_USER_ID)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return CreateConversationResponse(
        id=conv.id, title=conv.title, model=conv.model, created_at=conv.created_at
    )


@app.delete(
    "/api/v1/conversations/{conv_id}",
    status_code=204,
    tags=["Conversations"],
)
async def delete_conversation(conv_id: uuid.UUID):
    if not store.delete_conversation(conv_id, DEMO_USER_ID):
        raise HTTPException(status_code=404, detail="Conversation not found")


# ── Messages ─────────────────────────────────────────────────────────────────


@app.post(
    "/api/v1/conversations/{conv_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    tags=["Messages"],
)
async def send_message(conv_id: uuid.UUID, req: SendMessageRequest):
    conv = store.get_conversation(conv_id, DEMO_USER_ID)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Store the user message
    user_msg = store.add_message(
        conversation_id=conv_id,
        role=MessageRole.USER,
        content=req.content,
        token_count=len(req.content.split()),  # Rough estimate
        parent_message_id=req.parent_message_id,
    )

    # Simulate an assistant response (in production, this goes through the
    # message queue → LLM Worker → SSE stream pipeline)
    assistant_content = f"This is a simulated response to: {req.content[:100]}"
    assistant_msg = store.add_message(
        conversation_id=conv_id,
        role=MessageRole.ASSISTANT,
        content=assistant_content,
        token_count=len(assistant_content.split()),
        model=conv.model,
    )

    return MessageResponse(
        id=assistant_msg.id,
        conversation_id=conv_id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        token_count=assistant_msg.token_count,
        model=assistant_msg.model,
        created_at=assistant_msg.created_at,
    )


@app.get(
    "/api/v1/conversations/{conv_id}/messages",
    response_model=MessageHistoryResponse,
    tags=["Messages"],
)
async def get_message_history(
    conv_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: str = Query(None),
):
    conv = store.get_conversation(conv_id, DEMO_USER_ID)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages, has_more, next_cursor = store.get_messages(
        conversation_id=conv_id, limit=limit, cursor=cursor
    )
    return MessageHistoryResponse(
        messages=[
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role,
                content=m.content,
                token_count=m.token_count,
                model=m.model,
                created_at=m.created_at,
            )
            for m in messages
        ],
        has_more=has_more,
        next_cursor=next_cursor,
    )


@app.get(
    "/api/v1/conversations/{conv_id}/messages/{msg_id}",
    response_model=MessageResponse,
    tags=["Messages"],
)
async def get_message(conv_id: uuid.UUID, msg_id: uuid.UUID):
    conv = store.get_conversation(conv_id, DEMO_USER_ID)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = store.get_message(conv_id, msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    return MessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        token_count=msg.token_count,
        model=msg.model,
        created_at=msg.created_at,
    )
