"""Data models for the ChatGPT-like conversation service."""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ── Database Models (ORM-style, used with SQLAlchemy or similar) ─────────────

class UserRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    email: str
    display_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    user_id: uuid.UUID
    title: Optional[str] = None
    model: str = "gpt-4"
    system_prompt: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None


class MessageRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    token_count: int = 0
    model: Optional[str] = None
    parent_message_id: Optional[uuid.UUID] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── API Request / Response Schemas ───────────────────────────────────────────

class CreateConversationRequest(BaseModel):
    title: Optional[str] = None
    model: str = "gpt-4"
    system_prompt: Optional[str] = None


class CreateConversationResponse(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    model: str
    created_at: datetime


class ConversationListItem(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    model: str
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationListItem]
    total: int
    page: int
    page_size: int


class SendMessageRequest(BaseModel):
    content: str = Field(..., max_length=32000)
    parent_message_id: Optional[uuid.UUID] = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    token_count: int
    model: Optional[str]
    created_at: datetime


class MessageHistoryResponse(BaseModel):
    messages: list[MessageResponse]
    has_more: bool
    next_cursor: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    timestamp: datetime
