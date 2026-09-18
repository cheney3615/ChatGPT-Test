"""In-memory storage layer for demonstration and testing.

In production, replace with SQLAlchemy async sessions backed by PostgreSQL
and Redis caching. This module provides the same interface so the API layer
is storage-agnostic.
"""

import uuid
from datetime import datetime
from typing import Optional

from app.models import (
    ConversationRecord,
    MessageRecord,
    MessageRole,
)


class InMemoryStore:
    """Thread-safe (GIL-protected) in-memory store for conversations and messages."""

    def __init__(self):
        self._conversations: dict[uuid.UUID, ConversationRecord] = {}
        self._messages: dict[uuid.UUID, list[MessageRecord]] = {}  # conv_id → messages

    # ── Conversations ────────────────────────────────────────────────────

    def create_conversation(
        self,
        user_id: uuid.UUID,
        title: Optional[str] = None,
        model: str = "gpt-4",
        system_prompt: Optional[str] = None,
    ) -> ConversationRecord:
        conv = ConversationRecord(
            user_id=user_id,
            title=title,
            model=model,
            system_prompt=system_prompt,
        )
        self._conversations[conv.id] = conv
        self._messages[conv.id] = []

        # If a system prompt is provided, store it as the first message
        if system_prompt:
            sys_msg = MessageRecord(
                conversation_id=conv.id,
                role=MessageRole.SYSTEM,
                content=system_prompt,
            )
            self._messages[conv.id].append(sys_msg)

        return conv

    def get_conversation(
        self, conv_id: uuid.UUID, user_id: uuid.UUID
    ) -> Optional[ConversationRecord]:
        conv = self._conversations.get(conv_id)
        if conv and conv.user_id == user_id and conv.deleted_at is None:
            return conv
        return None

    def list_conversations(
        self, user_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[ConversationRecord], int]:
        user_convs = sorted(
            [
                c
                for c in self._conversations.values()
                if c.user_id == user_id and c.deleted_at is None
            ],
            key=lambda c: c.updated_at,
            reverse=True,
        )
        total = len(user_convs)
        start = (page - 1) * page_size
        return user_convs[start : start + page_size], total

    def delete_conversation(self, conv_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        conv = self.get_conversation(conv_id, user_id)
        if conv is None:
            return False
        conv.deleted_at = datetime.utcnow()
        return True

    # ── Messages ─────────────────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: uuid.UUID,
        role: MessageRole,
        content: str,
        token_count: int = 0,
        model: Optional[str] = None,
        parent_message_id: Optional[uuid.UUID] = None,
    ) -> MessageRecord:
        msg = MessageRecord(
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            model=model,
            parent_message_id=parent_message_id,
        )
        if conversation_id not in self._messages:
            self._messages[conversation_id] = []
        self._messages[conversation_id].append(msg)

        # Update conversation timestamp
        if conversation_id in self._conversations:
            self._conversations[conversation_id].updated_at = datetime.utcnow()

        return msg

    def get_messages(
        self,
        conversation_id: uuid.UUID,
        limit: int = 50,
        cursor: Optional[str] = None,
    ) -> tuple[list[MessageRecord], bool, Optional[str]]:
        msgs = self._messages.get(conversation_id, [])
        start_idx = 0

        if cursor:
            cursor_id = uuid.UUID(cursor)
            for i, m in enumerate(msgs):
                if m.id == cursor_id:
                    start_idx = i + 1
                    break

        page = msgs[start_idx : start_idx + limit]
        has_more = (start_idx + limit) < len(msgs)
        next_cursor = str(page[-1].id) if has_more and page else None
        return page, has_more, next_cursor

    def get_message(
        self, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> Optional[MessageRecord]:
        for msg in self._messages.get(conversation_id, []):
            if msg.id == message_id:
                return msg
        return None


# Singleton store instance
store = InMemoryStore()
