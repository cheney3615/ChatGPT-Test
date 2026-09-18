# ChatGPT-Test

A backend system for a ChatGPT-like conversation service built with FastAPI.

## Features

- **Conversation Management:** Create, list, retrieve, and soft-delete conversations.
- **Message Handling:** Send messages, receive AI responses, retrieve full conversation history with cursor-based pagination.
- **Scalable Architecture:** Designed for horizontal scaling with stateless API servers, message queue decoupling, and independent LLM worker pools.
- **Caching:** Redis-based cache-aside pattern for conversation metadata and recent messages.
- **Failure Handling:** Circuit breakers, retry with backoff, graceful degradation, and dead letter queues.

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full system design, including:
- API design and data model
- Service components (API Gateway, API Server, LLM Gateway, Message Queue, Worker Pool)
- Storage strategy (PostgreSQL + Redis + S3)
- Scalability and failure handling
- Security and deployment

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload --port 8000

# Run tests
pytest tests/ -v
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/health/ready` | Readiness probe |
| POST | `/api/v1/conversations` | Create conversation |
| GET | `/api/v1/conversations` | List conversations |
| GET | `/api/v1/conversations/{id}` | Get conversation |
| DELETE | `/api/v1/conversations/{id}` | Delete conversation |
| POST | `/api/v1/conversations/{id}/messages` | Send message |
| GET | `/api/v1/conversations/{id}/messages` | Get message history |
| GET | `/api/v1/conversations/{id}/messages/{msgId}` | Get single message |

## Project Structure

```
chatgpt-test/
├── ARCHITECTURE.md      # Full architecture documentation
├── README.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── config.py        # Environment-based configuration
│   ├── main.py          # FastAPI app with all endpoints
│   ├── models.py        # Pydantic data models
│   └── store.py         # Storage layer (in-memory for demo)
└── tests/
    ├── __init__.py
    └── test_api.py      # Comprehensive API tests
```

## License

MIT
