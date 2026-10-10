# StudyAI

AI study assistant for college students: upload notes (PDF/TXT/MD), then use an AI Tutor grounded in your material,
notes generation with PDF/DOCX export, quizzes, flashcards, a study planner, a tracker with streaks/badges and an AI coach.

## Problem statement
Students have long PDFs and little time. StudyAI retrieves the relevant passages of *their own* material (TF-IDF),
sends them to an NVIDIA-hosted LLM, and turns the result into study tools whose progress is stored per user.

## Features
- Accounts (hashed passwords, per-user data isolation) - Library with upload/delete - AI Tutor (5 answer styles, saved history, sources)
- AI notes (saved, searchable, PDF/DOCX download) - Quiz (answers hidden until you answer, explanations, history, topic accuracy)
- Flashcard decks (saved) - Planner (saved plans, tick-off tasks, PDF) - Dashboard (14-day chart, goal, badges, recent activity)
- Global search - Profile personalisation - Loading/empty/error states, toasts, responsive layout

## Technology stack
Flask 3 (Python) - vanilla JS/CSS front end (no build step, no CDN) - SQLite locally / PostgreSQL (Neon) in production -
pypdf, reportlab, python-docx - NVIDIA NIM chat-completions API - unittest + Playwright (UI check).

## Architecture
```
Browser (public/index.html + static/app.js)  --JSON/cookie-->  Flask app.py  -->  db.py  -->  SQLite | PostgreSQL
                                                                  |--> retrieval.py (TF-IDF)   |--> llm_client.py -> NVIDIA API
                                                                  |--> ingest.py / exports.py (in-memory PDF/DOCX)
```
On Vercel, Flask runs as one serverless function and `public/` is served by the CDN. Nothing is written to disk.

## Folder structure
```
app.py  db.py  llm_client.py  retrieval.py  ingest.py  quiz.py  exports.py  seed.py  manage.py
public/index.html  public/static/{app.css,app.js}
database/{schema.sql,schema.sqlite.sql,README.md}   docs/API.md
tests/{test_api.py,helpers.py,fake_nvidia.py}
vercel.json  requirements.txt  .env.example  docker-compose.yml  Dockerfile  .gitignore
```

## Prerequisites (Windows)
1. Python 3.11+ from python.org (tick "Add python.exe to PATH"). 2. An NVIDIA API key from build.nvidia.com.
3. Optional: PostgreSQL 16 *or* Docker Desktop. Node.js is **not** needed (no front-end build).

## Installation (Option A - normal Windows setup, SQLite, no database install)
```powershell
cd StudyAI
python -m venv venv
.\venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install -r requirements.txt
Copy-Item .env.example .env          # then edit .env: set NVIDIA_API_KEY and SECRET_KEY
python manage.py init-db
python manage.py seed                # optional demo account: demo@studyai.local / Demo@12345
python app.py
```
Open http://127.0.0.1:5001

## Database setup
- **SQLite (default):** nothing to do; `studyai.db` is created automatically. Delete it for a clean slate.
- **Local PostgreSQL:** `psql -U postgres -c "CREATE DATABASE studyai;"`, set `DATABASE_URL=postgresql://postgres:YOURPASSWORD@localhost:5432/studyai` in `.env`, then `python manage.py init-db` and `python manage.py seed`.
- **Option B - Docker:** `docker compose up -d db`, set `DATABASE_URL=postgresql://studyai:studyai@localhost:5432/studyai`, then as above. `docker compose up --build` runs the whole app.
- Tables are created/upgraded by versioned migrations (`python manage.py init-db`, also run at app start). Old v1 `studyai.db` files are upgraded in place.
- Check: `python manage.py status`.

## Environment variables
See `.env.example` (every variable documented). Required: `NVIDIA_API_KEY` (AI features), `SECRET_KEY` (required on Vercel).
Optional: `DATABASE_URL`, `STUDYAI_GEN_MODEL`, `STUDYAI_FALLBACK_MODELS`, `MAX_UPLOAD_MB`, `STUDYAI_AI_TIMEOUT_SECONDS`, `STUDYAI_AI_BUDGET_SECONDS`, `SQLITE_PATH`.

## Running / API documentation
Backend and front end are one process: `python app.py`. Health check: http://127.0.0.1:5001/api/health. API reference: `docs/API.md`.

## Testing
```powershell
python -m unittest discover -s tests -t . -v
```
26 backend tests (auth, validation, user isolation, upload rejection, tutor/notes/flashcards/quiz/planner flows, dashboard,
exports, TF-IDF ranking, migration of an old database, AI-client error handling). They replace only the network call to NVIDIA.
To try the UI without an NVIDIA key, run the test-only stand-in: `python tests/fake_nvidia.py 9100`, then start the app with
`NVIDIA_API_KEY=test` and `NVIDIA_API_BASE=http://127.0.0.1:9100/v1/chat/completions`. Its answers are canned, not real AI output.

## Sample credentials
After `python manage.py seed`: `demo@studyai.local` / `Demo@12345` (synthetic data; local use only - do not seed a public deployment).

## Vercel deployment
1. Create a Neon (neon.tech) project and copy its connection string (keep `?sslmode=require`).
2. Push this folder to GitHub, then "Add New Project" in Vercel and import it (framework: Other/Flask is auto-detected from `app.py`).
3. Environment Variables: `DATABASE_URL`, `SECRET_KEY` (random 32+ chars), `NVIDIA_API_KEY`, optionally `STUDYAI_GEN_MODEL`.
4. Deploy. Tables are created automatically on the first request. Open `/api/health`: it must show `"database":"postgres","db_ok":true`.
5. Optional first-time schema from your PC: set `DATABASE_URL` to the Neon string and run `python manage.py init-db`.
Without `DATABASE_URL`, Vercel would use a temporary `/tmp` SQLite file and lose data; `/api/health` warns about this.

## Troubleshooting
- **AI error 410 from NVIDIA:** the key works but hosted inference is not enabled for your NVIDIA organization; changing models won't help. Run `python test_nvidia.py` (200 on `/v1/models` + 410 on chat = account setting), enable Public API Endpoints in NVIDIA Build, create a new key, restart.
- **"NVIDIA_API_KEY is not configured":** fill `.env`, restart. **Session expired after resetting the database:** log in again.
- **Upload fails on Vercel:** request body limit is ~4.5 MB, so `MAX_UPLOAD_MB` defaults to 4 there. Scanned (image-only) PDFs have no text and are rejected.
- **psycopg install problems on Windows:** use Python 3.11-3.13 and `python -m pip install --upgrade pip` first.

## Limitations
- PostgreSQL support is implemented with the same SQL and migrations as SQLite, but was **not run against a live PostgreSQL server in the environment where this version was built** (no database server or package index available there). SQLite was fully tested. Run `python manage.py init-db && python manage.py seed && python -m unittest` against your Postgres once (set `DATABASE_URL`) before the demo.
- Docker files and the Vercel deployment were not executed here; `vercel.json` follows Vercel's Flask documentation.
- AI quality depends on the NVIDIA model; quiz/flashcard questions are validated for structure, not factual correctness.
- Retrieval is TF-IDF keyword matching (no embeddings). A request must finish within the 60 s function limit.
- No rate limiting on login, no email verification or password reset.

## Future scope
Embedding-based retrieval, OCR for scanned PDFs, object storage for original files, spaced-repetition scheduling, rate limiting, password reset.
