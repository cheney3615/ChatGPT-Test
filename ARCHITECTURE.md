# ChatGPT-Test Backend Architecture

## 1. Overview

This document describes the backend architecture for a ChatGPT-like conversation service. The system supports creating conversations, sending and storing messages, retrieving conversation history, streaming responses, and handling high-concurrency workloads with graceful failure handling.

## 2. API Design

All endpoints are RESTful, versioned under `/api/v1`, and return JSON. Authentication is via Bearer JWT tokens.

### 2.1 Conversations

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/conversations` | Create a new conversation |
| GET | `/api/v1/conversations` | List conversations for the authenticated user (paginated) |
| GET | `/api/v1/conversations/{id}` | Get conversation metadata |
| DELETE | `/api/v1/conversations/{id}` | Soft-delete a conversation |

### 2.2 Messages

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/conversations/{id}/messages` | Send a message and receive AI response (SSE stream) |
| GET | `/api/v1/conversations/{id}/messages` | Retrieve message history (cursor-based pagination) |
| GET | `/api/v1/conversations/{id}/messages/{msgId}` | Get a single message |

### 2.3 System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/health/ready` | Readiness probe |

### 2.4 Rate Limiting

All endpoints are rate-limited per user via a sliding-window counter stored in Redis. Default limits: 60 requests/minute for reads, 20 requests/minute for message sends.

## 3. Data Model

### 3.1 Core Entities

**User**
- `id` (UUID, PK)
- `email` (VARCHAR, unique)
- `display_name` (VARCHAR)
- `created_at` (TIMESTAMP)

**Conversation**
- `id` (UUID, PK)
- `user_id` (UUID, FK → User, partition key)
- `title` (VARCHAR, nullable — auto-generated from first message)
- `model` (VARCHAR, default "gpt-4")
- `system_prompt` (TEXT, nullable)
- `created_at` (TIMESTAMP)
- `updated_at` (TIMESTAMP)
- `deleted_at` (TIMESTAMP, nullable — soft delete)

**Message**
- `id` (UUID, PK)
- `conversation_id` (UUID, FK → Conversation, partition key)
- `role` (ENUM: user | assistant | system)
- `content` (TEXT)
- `token_count` (INTEGER)
- `model` (VARCHAR, nullable — set for assistant messages)
- `parent_message_id` (UUID, nullable — for branching)
- `created_at` (TIMESTAMP)

### 3.2 Indexes

- `conversation`: composite index on `(user_id, updated_at DESC)` for listing.
- `message`: composite index on `(conversation_id, created_at ASC)` for history retrieval; index on `(conversation_id, parent_message_id)` for branch lookups.

## 4. Service Components

### 4.1 API Gateway (Nginx / Envoy)

Handles TLS termination, request routing, rate limiting enforcement, and load balancing across API server instances.

### 4.2 API Server (FastAPI / Python)

Stateless HTTP server handling REST endpoints and SSE streaming. Horizontally scalable. Each instance connects to PostgreSQL (via connection pool), Redis, and the LLM Gateway.

### 4.3 LLM Gateway

An internal proxy that routes completion requests to upstream LLM providers (OpenAI, self-hosted models). Provides retry logic, circuit breaking, model routing, token counting, and usage metering.

### 4.4 Message Queue (Redis Streams / Kafka)

Decouples message ingestion from LLM processing. When a user sends a message, the API server publishes to the queue; a pool of LLM Worker processes consumes and generates responses. This prevents long-running LLM calls from blocking HTTP threads.

### 4.5 LLM Worker Pool

Consumer processes that read from the message queue, call the LLM Gateway, write the assistant response to the database, and push SSE chunks to the user's active connection via a pub/sub channel.

### 4.6 Background Workers

Handle non-critical tasks: conversation title generation, token usage aggregation, conversation summarization for long contexts, and cleanup of soft-deleted records.

## 5. Storage

### 5.1 Primary Database — PostgreSQL

PostgreSQL serves as the single source of truth for all structured data (users, conversations, messages). Chosen for strong consistency, JSONB support for metadata, and mature partitioning.

**Partitioning strategy:** The `message` table is range-partitioned by `created_at` (monthly partitions) to keep per-partition sizes manageable and enable efficient time-range queries and archival.

**Connection pooling:** PgBouncer sits between the API servers and PostgreSQL, maintaining a shared pool of connections in transaction mode.

### 5.2 Cache — Redis

Redis serves three roles:
1. **Session/rate-limit store:** Sliding-window counters for rate limiting; JWT session blacklist.
2. **Conversation cache:** Recent conversation metadata and the last N messages cached with a 10-minute TTL, invalidated on write.
3. **SSE pub/sub:** Used as a channel for LLM Workers to push streaming tokens to the correct API server instance holding the user's SSE connection.

### 5.3 Object Storage (S3 / MinIO)

Stores file attachments (images, documents) referenced by messages. The API server generates pre-signed upload/download URLs.

## 6. Caching Strategy

### 6.1 Cache-Aside Pattern

The API server checks Redis before querying PostgreSQL. On cache miss, it fetches from the database, populates the cache, and returns the result. Writes always go to PostgreSQL first, then invalidate (delete) the relevant cache keys.

### 6.2 Key Design

```
conv:{user_id}:list        → sorted set of conversation IDs (TTL 10m)
conv:{conv_id}:meta        → conversation metadata hash (TTL 10m)
conv:{conv_id}:msgs:recent → list of last 50 messages (TTL 10m)
ratelimit:{user_id}:{endpoint} → sliding window counter (TTL 1m)
```

### 6.3 Invalidation

On any write to a conversation or its messages, the API server deletes the related cache keys. This ensures eventual consistency with a maximum staleness of one write operation.

## 7. Scalability

### 7.1 Horizontal Scaling

- **API Servers:** Stateless; scale out behind the load balancer based on CPU/request-rate metrics.
- **LLM Workers:** Scale independently based on queue depth. Each worker is single-purpose and can be autoscaled via Kubernetes HPA.
- **Database:** Read replicas for conversation listing and history retrieval. Writes go to the primary. Partitioning keeps individual partition sizes small.

### 7.2 Vertical Scaling Points

- **Connection pooling:** PgBouncer prevents connection exhaustion under spike load.
- **Redis cluster:** Shard by key prefix to distribute cache load across multiple Redis nodes.

### 7.3 Estimated Capacity

| Component | Single Instance | 10-Instance Cluster |
|-----------|----------------|---------------------|
| API Server | ~2,000 req/s | ~20,000 req/s |
| LLM Worker | ~50 concurrent completions | ~500 concurrent completions |
| PostgreSQL (primary) | ~10,000 TPS (mixed) | + read replicas for reads |
| Redis | ~100,000 ops/s | ~1M ops/s (cluster) |

## 8. Failure Handling

### 8.1 LLM Provider Failures

- **Retry with exponential backoff:** Up to 3 retries with jitter for transient errors (429, 500, 503).
- **Circuit breaker:** After 5 consecutive failures to a provider, the circuit opens for 30 seconds, routing to a fallback model or returning a graceful error.
- **Timeout:** 60-second timeout per LLM call; partial responses are saved and the user is notified.

### 8.2 Database Failures

- **Connection pool exhaustion:** PgBouncer queues requests; API server returns 503 after 5-second wait.
- **Primary failure:** Automatic failover via Patroni/Stolon. Read traffic continues on replicas.
- **Data integrity:** All message writes are wrapped in transactions. The assistant response is committed only after the full response is generated.

### 8.3 Cache Failures

- **Redis down:** The system degrades gracefully — all requests fall through to PostgreSQL. Rate limiting falls back to local in-memory counters.
- **Cache stampede prevention:** Probabilistic early expiration (PER) prevents thundering herd on popular cache keys.

### 8.4 Queue Failures

- **Consumer lag:** Alert on queue depth > 1000. Autoscale LLM Workers.
- **Message loss:** Redis Streams with consumer groups provide at-least-once delivery. Kafka alternative provides stronger durability guarantees.
- **Dead letter queue:** Messages that fail processing after 3 attempts are moved to a DLQ for manual inspection.

### 8.5 Observability

- **Metrics:** Prometheus endpoints on every service (request latency, error rate, queue depth, cache hit ratio, LLM token usage).
- **Tracing:** OpenTelemetry distributed tracing across API → Queue → Worker → LLM Gateway.
- **Logging:** Structured JSON logs shipped to ELK/Loki. Request correlation IDs propagated across all services.
- **Alerting:** PagerDuty integration for P0/P1 alerts (error rate > 5%, p99 latency > 10s, queue depth > 1000).

## 9. Security

- **Authentication:** JWT tokens with RS256 signing. Refresh token rotation.
- **Authorization:** Row-level security — users can only access their own conversations.
- **Encryption:** TLS 1.3 in transit; AES-256 encryption at rest for message content.
- **Input validation:** All inputs sanitized; message content length capped at 32K characters.
- **Audit logging:** All conversation creation, deletion, and admin actions are logged.

## 10. Deployment

- **Container orchestration:** Kubernetes with separate deployments for API servers, LLM workers, and background workers.
- **CI/CD:** GitHub Actions for build, test, and deploy.
- **Environments:** dev → staging → production with feature flags.
- **Infrastructure as Code:** Terraform for cloud resources; Helm charts for Kubernetes manifests.
