# Campus Copilot Service

The FastAPI backend behind Campus Copilot: authentication, campus records, vector-grounded RAG, and
the AI agent that answers students' questions using them.

The assistant runs on **Groq** only using OpenAI-compatible tool calling completions.
Retrieval uses **local embeddings** via FastEmbed (`BAAI/bge-small-en-v1.5`) and an on-disk **ChromaDB** store, requiring no external embeddings API.

## Architecture Mapping

| Original Component | Service Implementation | Description |
|---|---|---|
| `query_campus_docs` | `search_campus_documents` | Semantic vector search over college policies, regulations, notices, and uploaded documents using local embeddings & ChromaDB. |
| `query_student_db` | `get_attendance_summary`, `get_class_sessions`, `simulate_attendance_change`, `get_timetable`, `get_assignments`, `get_exams`, `get_fees`, `get_campus_info` | Direct Python functions querying SQLite/MySQL with JWT-derived student identity isolation. |
| `get_campus_events` | `get_campus_events` | Retrieval of campus events via `CampusEventsProvider` (external API when configured, or seeded local demo events table). |

## How a question is answered

```
student question (+ recent conversation)
        |
  POST /ai/chat (or /api/chat)      ai_router.py
        |
  agent loop                        ai_agent.py
        |-> Groq model decides which tools the question needs
        |-> tools read the real database                ai_tools.py
        |-> campus documents are searched semantically  document_index.py / rag_service.py
        |
  grounded answer + cards + sources
```

The model never sees a hardcoded reply. It sees the student's profile, the tools
it may call, and the results those tools return (defended against prompt injection by untrusted data quotes).

## Files

| File | Responsibility |
|---|---|
| `main.py` | App setup, lifespan handler, CORS restrictions, rate limiting, `/health` |
| `config.py` | Settings read from `.env` with security validation for `SECRET_KEY` |
| `auth/` | Register, login, password change, `/auth/me`, JWT verification, password hashing |
| `attendance_router.py` | Attendance status and marking |
| `student_router.py` | `/student/insights` for the "Copilot noticed" proactive panel |
| `ai_router.py` | `/ai/chat` and `/api/chat` endpoints with persistent chat session linking |
| `chat_router.py` | Session persistence: `/chat/sessions`, `/chat/sessions/{id}` |
| `document_router.py` | Document ingestion: `/api/documents` (upload, list, delete) |
| `meta_router.py` | Academic catalogue: `/meta/catalogue` |
| `ai_agent.py` | The multi-round tool-calling loop supporting multiple cards |
| `ai_tools.py` | Tools: attendance, timetable, assignments, exams, fees, campus info, campus events, RAG search |
| `prompts.py` | System instructions and prompt injection defense |
| `llm_client.py` | Groq client with backoff retries for 429/5xx and tool-call 400 recovery |
| `document_index.py` | FastEmbed chunking, on-disk ChromaDB persistence, page-aware RAG |
| `services/rag_service.py` | Public RAG interface module |
| `db/` | SQLAlchemy engine, models, schemas, and idempotent schema migrations |
| `seed_data.py` | Seeds subjects, timetable, sessions, assignments, exams, fees, demo events, and indexes policies |
| `enrollment.py` | Academic environment provisioning for registered students |

## Setup

```bash
# 1. Create a virtual environment
python -m venv venv
.\venv\Scripts\activate          # Windows; source venv/bin/activate on macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env: Set GROQ_API_KEY and generate a secure SECRET_KEY (min 32 chars)
# python -c "import secrets; print(secrets.token_urlsafe(32))"

# 4. Seed academic data and index documents
python seed_data.py --all --reindex

# 5. Start the service
uvicorn main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs for Swagger API documentation or http://127.0.0.1:8000/health to verify service health and provider.

## Running Tests

Run backend unit and integration test suite:

```bash
pytest -v
```

Run live opt-in test against the Groq API (requires `GROQ_API_KEY` set):

```bash
pytest -m live -v
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create a student account, returns JWT token |
| POST | `/auth/login` | Sign in with email or roll number, returns JWT token |
| POST | `/auth/change-password` | Update current student password |
| GET | `/auth/me` | Current authenticated student details |
| GET | `/attendance/status` | Class sessions and attendance states |
| POST | `/attendance/{session_id}/mark` | Mark attendance present or absent |
| GET | `/student/insights` | Proactive alerts built from live records |
| POST | `/ai/chat` | Main AI assistant chat turn (accepts `session_id`) |
| POST | `/api/chat` | Alias of `/ai/chat` |
| GET | `/chat/sessions` | List authenticated student's chat sessions |
| GET | `/chat/sessions/{id}` | Retrieve messages and cards for a chat session |
| DELETE | `/chat/sessions/{id}` | Delete a chat session |
| POST | `/api/documents` | Upload and vector-index a document (PDF, DOCX, TXT, MD) |
| GET | `/api/documents` | List accessible campus and private documents |
| DELETE | `/api/documents/{id}` | Delete document and vector embeddings |
| GET | `/meta/catalogue` | List seeded department and semester combinations |
| GET | `/health` | Service status, database connection, AI model info |
