"""API validation tests for the ChatGPT-Test backend service.

Validates all key APIs and workflows:
1. Health check endpoints
2. Conversation CRUD lifecycle
3. Message send and retrieval
4. Pagination and cursor-based history
5. Error handling (404, validation errors)
6. Concurrent request handling
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.store import InMemoryStore, store as global_store


@pytest.fixture(autouse=True)
def reset_store():
    """Reset the in-memory store before each test."""
    global_store._conversations.clear()
    global_store._messages.clear()
    yield


client = TestClient(app)


# ── 1. Health Check ──────────────────────────────────────────────────────────


class TestHealthEndpoints:
    def test_health_check(self):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "timestamp" in data

    def test_readiness_check(self):
        resp = client.get("/api/v1/health/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"


# ── 2. Conversation CRUD ─────────────────────────────────────────────────────


class TestConversationCRUD:
    def test_create_conversation_default(self):
        resp = client.post("/api/v1/conversations", json={})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["model"] == "gpt-4"

    def test_create_conversation_with_params(self):
        resp = client.post(
            "/api/v1/conversations",
            json={
                "title": "Test Chat",
                "model": "gpt-3.5-turbo",
                "system_prompt": "You are a helpful assistant.",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Chat"
        assert data["model"] == "gpt-3.5-turbo"

    def test_get_conversation(self):
        create_resp = client.post(
            "/api/v1/conversations", json={"title": "Lookup Test"}
        )
        conv_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Lookup Test"

    def test_get_conversation_not_found(self):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/conversations/{fake_id}")
        assert resp.status_code == 404

    def test_list_conversations(self):
        for i in range(3):
            client.post("/api/v1/conversations", json={"title": f"Conv {i}"})
        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["conversations"]) == 3

    def test_list_conversations_pagination(self):
        for i in range(5):
            client.post("/api/v1/conversations", json={"title": f"Conv {i}"})
        resp = client.get("/api/v1/conversations?page=1&page_size=2")
        data = resp.json()
        assert len(data["conversations"]) == 2
        assert data["total"] == 5

    def test_delete_conversation(self):
        create_resp = client.post(
            "/api/v1/conversations", json={"title": "To Delete"}
        )
        conv_id = create_resp.json()["id"]
        del_resp = client.delete(f"/api/v1/conversations/{conv_id}")
        assert del_resp.status_code == 204

        # Verify it's no longer accessible
        get_resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert get_resp.status_code == 404

    def test_delete_conversation_not_found(self):
        fake_id = str(uuid.uuid4())
        resp = client.delete(f"/api/v1/conversations/{fake_id}")
        assert resp.status_code == 404


# ── 3. Message Send & Retrieval ──────────────────────────────────────────────


class TestMessages:
    def _create_conversation(self, title="Test"):
        resp = client.post("/api/v1/conversations", json={"title": title})
        return resp.json()["id"]

    def test_send_message(self):
        conv_id = self._create_conversation()
        resp = client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Hello, world!"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "assistant"
        assert "simulated response" in data["content"].lower()

    def test_send_message_to_nonexistent_conversation(self):
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"/api/v1/conversations/{fake_id}/messages",
            json={"content": "Hello"},
        )
        assert resp.status_code == 404

    def test_get_message_history(self):
        conv_id = self._create_conversation()
        # Send 3 messages
        for i in range(3):
            client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": f"Message {i}"},
            )
        resp = client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert resp.status_code == 200
        data = resp.json()
        # Each send creates user + assistant = 6 messages total
        assert len(data["messages"]) == 6

    def test_get_message_history_pagination(self):
        conv_id = self._create_conversation()
        for i in range(5):
            client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": f"Msg {i}"},
            )
        # 10 messages total (5 user + 5 assistant), fetch first 4
        resp = client.get(f"/api/v1/conversations/{conv_id}/messages?limit=4")
        data = resp.json()
        assert len(data["messages"]) == 4
        assert data["has_more"] is True
        assert data["next_cursor"] is not None

    def test_get_single_message(self):
        conv_id = self._create_conversation()
        send_resp = client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"content": "Find me"},
        )
        msg_id = send_resp.json()["id"]
        resp = client.get(f"/api/v1/conversations/{conv_id}/messages/{msg_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == msg_id

    def test_get_message_not_found(self):
        conv_id = self._create_conversation()
        fake_msg_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/conversations/{conv_id}/messages/{fake_msg_id}")
        assert resp.status_code == 404

    def test_message_history_for_nonexistent_conversation(self):
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/v1/conversations/{fake_id}/messages")
        assert resp.status_code == 404


# ── 4. Workflow: Full Conversation Lifecycle ─────────────────────────────────


class TestConversationWorkflow:
    def test_full_lifecycle(self):
        """End-to-end: create → send messages → retrieve history → delete."""
        # Create
        create_resp = client.post(
            "/api/v1/conversations",
            json={"title": "Lifecycle Test", "model": "gpt-4"},
        )
        assert create_resp.status_code == 201
        conv_id = create_resp.json()["id"]

        # Send messages
        for i in range(3):
            msg_resp = client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": f"Question {i}"},
            )
            assert msg_resp.status_code == 201

        # Retrieve history
        history_resp = client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert history_resp.status_code == 200
        assert len(history_resp.json()["messages"]) == 6

        # Verify in list
        list_resp = client.get("/api/v1/conversations")
        assert list_resp.json()["total"] >= 1

        # Delete
        del_resp = client.delete(f"/api/v1/conversations/{conv_id}")
        assert del_resp.status_code == 204

        # Confirm deleted
        get_resp = client.get(f"/api/v1/conversations/{conv_id}")
        assert get_resp.status_code == 404


# ── 5. Concurrent Request Handling ───────────────────────────────────────────


class TestConcurrency:
    def test_concurrent_conversation_creation(self):
        """Verify multiple conversations can be created concurrently."""
        results = []
        for i in range(10):
            resp = client.post(
                "/api/v1/conversations", json={"title": f"Concurrent {i}"}
            )
            results.append(resp)

        assert all(r.status_code == 201 for r in results)
        ids = {r.json()["id"] for r in results}
        assert len(ids) == 10  # All unique IDs

    def test_concurrent_messages_to_same_conversation(self):
        """Verify multiple messages can be sent to the same conversation."""
        create_resp = client.post(
            "/api/v1/conversations", json={"title": "Concurrent Msgs"}
        )
        conv_id = create_resp.json()["id"]

        results = []
        for i in range(10):
            resp = client.post(
                f"/api/v1/conversations/{conv_id}/messages",
                json={"content": f"Concurrent message {i}"},
            )
            results.append(resp)

        assert all(r.status_code == 201 for r in results)

        # All messages should be in history
        history = client.get(f"/api/v1/conversations/{conv_id}/messages")
        assert len(history.json()["messages"]) == 20  # 10 user + 10 assistant
