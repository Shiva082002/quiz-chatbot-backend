# Thinkly — Backend (Quiz Master API)

Flask API for **Thinkly**: Gemini-powered quiz generation/evaluation, topic tutor chat, and optional MongoDB storage for anonymous quiz sessions. The client is a separate repo (React); point it at this service with `VITE_API_BASE_URL`.

## Why this topic

I chose **learning and self-assessment** as the domain because it forces a **structured** AI product instead of an open-ended chat wrapper.

- **Quizzes need contracts.** The model returns **strict JSON** (Pydantic schemas), with retries when parsing fails, so the frontend can render single / multi / text questions and reviews reliably.
- **Chat has a narrow role.** The tutor answers in the context of the user’s chosen topic—same scope as the quiz—so `/api/chat` is purpose-built, not generic small talk.
- **Optional persistence fits the use case.** Saving anonymous session summaries to MongoDB is optional; when enabled, list endpoints expose `querySucceeded` so clients can tell “DB error” from “no rows.”

## What this service does

| Concern | Behavior |
|---------|------------|
| **Questions** | `generate_question` / `generate_batch_questions` — batched generation for fewer round trips. |
| **Answers** | `evaluate_answer` — structured evaluation for review screens. |
| **Chat** | `chat_reply` — topic-scoped tutor. |
| **Sessions** | `save_quiz_session` + `list_quiz_sessions` — MongoDB when `MONGODB_URI` is set; resilient reconnect/retry for serverless. |

**Reliability:** Request/response validation with Pydantic; Gemini JSON retried on invalid output; MongoDB client refresh on failed queries when listing sessions.

## Tech stack

- Python 3, Flask, Flask-CORS  
- Pydantic  
- Google Gemini (`google-genai` — `from google import genai`)  
- PyMongo (optional)

## Environment

Copy `.env.example` to `.env` in this directory.

| Variable | Required | Notes |
|----------|----------|--------|
| `GEMINI_API_KEY` | Yes | Google AI API key. |
| `GEMINI_MODEL` | No | Defaults in code if unset. |
| `PORT` | No | Default `5000` for local dev. |
| `MONGODB_URI` | No | If empty, session save/list skips DB or returns empty with flags. |
| `MONGODB_DATABASE` | No | Used with MongoDB. |
| `MONGODB_COLLECTION` | No | Used with MongoDB. |

Do not commit `.env` or real credentials.

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Health (`{"ok": true}`). |
| `POST` | `/api/generate-question` | Single question JSON. |
| `POST` | `/api/generate-batch-questions` | Batch of questions. |
| `POST` | `/api/evaluate-answer` | Evaluate user answer for results UI. |
| `POST` | `/api/save-quiz-session` | Persist anonymous session (MongoDB if configured). |
| `GET` | `/api/quiz-sessions?offset=&limit=` | Paginated history; includes `mongoConfigured`, `querySucceeded`. |
| `POST` | `/api/chat` | Topic tutor messages. |

## Run locally

From **this repository’s root** (the folder that contains `app.py`):

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
python app.py
```

The app listens on `PORT` (default `5000`). Enable CORS for your frontend origin in dev (already enabled broadly via Flask-CORS for local use).

If you still run this folder as a Python package named `backend` inside a parent monorepo, use: `python -m backend.app` from the parent directory instead.

## Deploy (e.g. Vercel)

This repo can ship a serverless entry under `api/` (see `api/index.py` and `vercel.json`). Set the same environment variables in the hosting dashboard. Ensure MongoDB Atlas **Network Access** allows your host (e.g. `0.0.0.0/0` for serverless, or static egress IPs).

## Demo

- **API base URL:** (add your deployed URL)  
- **Partner frontend repo:** (link to your React app repo)
