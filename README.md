# E-Commerce Customer Support Bot with Human Escalation (MVP)

Production-ready modular monolith architecture integrating FastAPI, LangChain, LangGraph, Google Gemini via Google GenAI | HuggingFace , and PostgreSQL + pgvector.

---

## Key Architecture & Features

1. **Stateful Support Orchestration**: LangGraph state machine handles context, intent classification, deterministic transactional tool execution, RAG over knowledge chunks, rule-based escalation, and conversational state persistence.
2. **AI Safety & Deterministic Boundaries**: The LLM is never given direct SQL access or authorization power. All transactional actions (order status, order cancellation, return request, refund status) execute inside strongly typed application services with strict customer identity and ownership validation.
3. **Multi-Factor Escalation Engine**: Automated escalation triggered on:
   - Explicit customer handoff requests
   - High frustration sentiment scores (>= 0.80)
   - Classification confidence < 0.50
   - Repeated operational or tool failures (>= 2)
   - Sensitive financial disputes and formal complaints
4. **Real-Time Server-Sent Events (SSE)**: Live streaming handoff connecting customers and support agents without introducing WebSocket complexity or external message brokers for the MVP.
5. **RAG with pgvector**: HNSW-indexed vector search with cosine distance (`vector_cosine_ops`) for policy documents and FAQs using Google `text-embedding-004` (768 dimensions).

---

## Quickstart via Docker Compose

### 1. Configure Environment
Create `.env` file from the example:
```bash
cp .env.example .env
```
Edit `.env` and set your `GEMINI_API_KEY or HF_TOKEN`:
```env
GEMINI_API_KEY=your-actual-google-gemini-api-key
or
HF_TOKEN=your-actual-google-gemini-api-key
```
#### Currently HuggingFace is in working
---
### 2. Start Services
```bash
docker-compose up --build
```
This boots:
- **PostgreSQL 16 + pgvector** on port `5432` with automatic schema creation and seed data (`init.sql`).
- **FastAPI Modular Monolith** on port `8000`.

### 3. Ingest Knowledge Documents
Trigger the RAG ingestion pipeline:
```bash
curl -X POST http://localhost:8000/api/v1/admin/ingest-knowledge
```

### 4. Access Interfaces
- **Portal & Documentation**: `http://localhost:8000/ui/index.html`
- **Customer Web Chat**: `http://localhost:8000/ui/customer.html`
- **Agent Dashboard**: `http://localhost:8000/ui/agent.html`
- **Interactive OpenAPI Specs**: `http://localhost:8000/docs`

---

## Seed Data for Testing

| Customer | Customer ID | Email |
| :--- | :--- | :--- |
| Alice Johnson | `c0000000-0000-0000-0000-000000000001` | `alice@example.com` |
| Bob Smith | `c0000000-0000-0000-0000-000000000002` | `bob@example.com` |

| Order ID | Customer | Status | Amount | Items |
| :--- | :--- | :--- | :--- | :--- |
| `b0000000-0000-0000-0000-000000000001` | Alice | `PROCESSING` | $199.99 | Acoustic Headphones (Eligible for cancellation) |
| `b0000000-0000-0000-0000-000000000002` | Alice | `DELIVERED` | $149.50 | Smartwatch (Eligible for return) |
| `b0000000-0000-0000-0000-000000000003` | Bob | `SHIPPED` | $349.49 | Multi-item package (Ownership check test) |
