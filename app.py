"""StudyAI - Flask application. Also the Vercel entrypoint (module-level ``app``)."""
import datetime
import json
import logging
import os
import re
import threading
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

import db
import exports
import ingest
import llm_client
import quiz as quiz_module
import retrieval

load_dotenv()
ON_VERCEL = bool(os.getenv("VERCEL"))
ROOT = Path(__file__).parent
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "4" if ON_VERCEL else "20"))  # Vercel request limit is ~4.5 MB
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("studyai")

app = Flask(__name__, static_folder=str(ROOT / "public" / "static"), static_url_path="/static")
_secret = os.getenv("SECRET_KEY", "")
if ON_VERCEL and (len(_secret) < 16 or _secret.startswith("change-this")):
    raise RuntimeError("Set a long random SECRET_KEY in the Vercel environment variables.")
app.secret_key = _secret or "dev-only-secret-not-for-production"
app.config.update(
    MAX_CONTENT_LENGTH=(MAX_UPLOAD_MB + 1) * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=ON_VERCEL,
    PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=14), JSON_SORT_KEYS=False,
)

_schema_ready = False
_schema_lock = threading.Lock()


def ensure_schema():
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if not _schema_ready:
            version = db.migrate()
            log.info("database ready (schema v%s, %s)", version, "postgres" if db.is_postgres() else "sqlite")
            _schema_ready = True


# ----------------------------------------------------------------------------- plumbing
def fail(message, status=400):
    return jsonify({"error": message}), status


@app.before_request
def _open_db():
    if request.path.startswith("/api/") and request.path != "/api/health":
        ensure_schema()
        g.conn, g.token = db.open_request()


@app.teardown_request
def _close_db(exc):
    conn = g.pop("conn", None)
    token = g.pop("token", None)
    if conn is not None:
        db.close_request(conn, token, ok=exc is None and getattr(g, "ok", True))


@app.after_request
def _headers(resp):
    if 500 <= resp.status_code < 600:
        g.ok = False
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(HTTPException)
def _http_error(e):
    if request.path.startswith("/api/"):
        msg = {404: "Not found.", 405: "Method not allowed.",
               413: f"File too large. Maximum size is {MAX_UPLOAD_MB} MB."}.get(e.code, e.description)
        return fail(msg, e.code)
    return e


@app.errorhandler(llm_client.LLMError)
def _llm_error(e):
    return fail(str(e), 502)


@app.errorhandler(Exception)
def _unhandled(e):
    log.exception("unhandled error on %s", request.path)
    g.ok = False
    return fail("Something went wrong on the server. Please try again.", 500)


def uid():
    return session.get("user_id")


def tz():
    try:
        return max(-840, min(840, int(request.headers.get("X-TZ-Offset", "0"))))
    except ValueError:
        return 0


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not uid():
            return fail("Please log in first.", 401)
        if db.get_user(uid()) is None:  # stale cookie after a database reset
            session.clear()
            return fail("Your session expired. Please log in again.", 401)
        return fn(*a, **kw)
    return wrapper


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def to_int(value, default, lo, hi):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def need_doc(data=None, key="document_id"):
    raw = (data if data is not None else request.args).get(key)
    try:
        did = int(raw)
    except (TypeError, ValueError):
        raise ValueError("Please select a document first.")
    d = db.get_document(uid(), did)
    if not d:
        raise ValueError("Document not found.")
    return d


def context_for(did, query=None, limit=8):
    found = retrieval.query_index(did, query, limit) if query else []
    return found or db.get_chunks(did)[:limit]


def attachment(data, mime, filename):
    safe = re.sub(r'[^\w.\- ]+', "", filename).strip() or "download"
    return Response(data, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


# ----------------------------------------------------------------------------- pages / health
@app.get("/")
def index():
    return send_from_directory(ROOT / "public", "index.html")


@app.get("/api/health")
def health():
    info = {"status": "ok", "database": "postgres" if db.is_postgres() else "sqlite",
            "ai_configured": bool(llm_client.API_KEY), "max_upload_mb": MAX_UPLOAD_MB,
            "persistent_storage": db.is_postgres() or not ON_VERCEL}
    if not info["persistent_storage"]:
        info["warning"] = "Running on Vercel without DATABASE_URL: data lives in /tmp and will be lost. Set DATABASE_URL to a Postgres database."
    try:
        ensure_schema()
        with db.connection():
            db.ping()
        info["db_ok"] = True
    except Exception:
        log.exception("health check database failure")
        info.update(status="degraded", db_ok=False)
        return jsonify(info), 503
    return jsonify(info)


# ----------------------------------------------------------------------------- auth / profile
@app.post("/api/auth/signup")
def signup():
    data = body()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if len(name) < 2 or len(name) > 80:
        return fail("Please enter your name (2-80 characters).")
    if not EMAIL_RE.match(email) or len(email) > 200:
        return fail("Please enter a valid email address.")
    if len(password) < 8 or len(password) > 200:
        return fail("Password must be at least 8 characters.")
    if db.get_user_by_email(email):
        return fail("An account with this email already exists.", 409)
    new_id = db.create_user(name, email, generate_password_hash(password))
    session.clear()
    session.permanent = True
    session["user_id"] = new_id
    return jsonify({"ok": True, "user": {"id": new_id, "name": name, "email": email}}), 201


@app.post("/api/auth/login")
def login():
    data = body()
    u = db.get_user_by_email(data.get("email") or "")
    if not u or not check_password_hash(u["password_hash"], data.get("password") or ""):
        return fail("Invalid email or password.", 401)
    session.clear()
    session.permanent = True
    session["user_id"] = u["id"]
    return jsonify({"ok": True, "user": {"id": u["id"], "name": u["name"], "email": u["email"]}})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
@login_required
def me():
    u = db.get_user(uid())
    return jsonify({"user": {"id": u["id"], "name": u["name"], "email": u["email"]}, "profile": db.get_profile(uid())})


@app.put("/api/profile")
@app.post("/api/profile")
@login_required
def save_profile():
    data = body()
    exam = (data.get("exam_date") or "").strip()
    if exam:
        try:
            datetime.date.fromisoformat(exam)
        except ValueError:
            return fail("Exam date is not valid.")
    style = data.get("explanation_style") or "Detailed"
    if style not in ("Detailed", "Simple", "Exam-focused"):
        return fail("Choose a valid explanation style.")
    db.update_profile(uid(), {
        "course": (data.get("course") or "").strip()[:80] or "TYBSc CS",
        "preferred_language": (data.get("preferred_language") or "").strip()[:40] or "English",
        "explanation_style": style, "daily_minutes": to_int(data.get("daily_minutes"), 120, 10, 600),
        "exam_date": exam or None})
    return jsonify({"ok": True, "profile": db.get_profile(uid())})


# ----------------------------------------------------------------------------- documents
@app.get("/api/documents")
@login_required
def documents():
    return jsonify({"documents": db.list_documents(uid())})


@app.post("/api/upload")
@login_required
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("Choose a file to upload.")
    name = re.sub(r"[\x00-\x1f/\\]+", "", Path(f.filename).name).strip()[:120]
    if Path(name).suffix.lower() not in ingest.ALLOWED_EXTENSIONS:
        return fail("File type not supported. Upload a PDF, TXT or Markdown file.", 415)
    raw = f.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        return fail(f"File too large. Maximum size is {MAX_UPLOAD_MB} MB.", 413)
    if not raw:
        return fail("The file is empty.")
    try:
        chunks = ingest.chunk_text(ingest.extract_text(name, raw))
    except ValueError as e:
        return fail(str(e))
    if not chunks:
        return fail("No readable text was found. Scanned/image-only PDFs are not supported.")
    did = db.create_document(uid(), name)
    db.insert_chunks(did, chunks)
    retrieval.build_index(did)
    db.log_activity(uid(), "document_upload", did, minutes=2)
    return jsonify({"document_id": did, "title": name, "chunks": len(chunks)}), 201


@app.delete("/api/documents/<int:did>")
@login_required
def delete_document(did):
    if not db.delete_document(uid(), did):
        return fail("Document not found.", 404)
    return jsonify({"ok": True})


@app.get("/api/search")
@login_required
def search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"results": []})
    return jsonify({"results": db.search(uid(), q[:100])})


# ----------------------------------------------------------------------------- tutor
@app.post("/api/chat")
@login_required
def chat():
    data = body()
    question = (data.get("question") or "").strip()
    if not question:
        return fail("Please type a question.")
    if len(question) > 2000:
        return fail("Question is too long (max 2000 characters).")
    try:
        d = need_doc(data)
    except ValueError as e:
        return fail(str(e))
    chunks = context_for(d["id"], question, 8)
    answer = llm_client.tutor(question, [c["text"] for c in chunks], db.chat_history(uid(), d["id"]),
                              db.get_profile(uid()), data.get("mode", "normal"))
    db.add_chat(uid(), d["id"], "user", question)
    db.add_chat(uid(), d["id"], "assistant", answer)
    db.log_activity(uid(), "ai_tutor", d["id"], minutes=3)
    return jsonify({"answer": answer, "sources": [{"chunk_index": c["chunk_index"], "excerpt": c["text"][:240]} for c in chunks]})


@app.get("/api/chat/history")
@login_required
def chat_history():
    try:
        d = need_doc()
    except ValueError as e:
        return fail(str(e))
    return jsonify({"messages": db.chat_history(uid(), d["id"], 40)})


@app.delete("/api/chat")
@login_required
def chat_clear():
    try:
        d = need_doc()
    except ValueError as e:
        return fail(str(e))
    db.clear_chat(uid(), d["id"])
    return jsonify({"ok": True})


# ----------------------------------------------------------------------------- notes
@app.post("/api/notes")
@login_required
def notes_create():
    data = body()
    try:
        d = need_doc(data)
    except ValueError as e:
        return fail(str(e))
    req = (data.get("request") or "Create detailed study notes from this document.").strip()[:1000]
    chunks = context_for(d["id"], req, 10)
    content = llm_client.notes([c["text"] for c in chunks], req, db.get_profile(uid()))
    title = (data.get("title") or "").strip()[:150] or f"Notes - {d['title']}"
    nid = db.create_note(uid(), d["id"], title, content)
    db.log_activity(uid(), "notes_generated", d["id"], minutes=5)
    return jsonify({"id": nid, "title": title, "content": content}), 201


@app.get("/api/notes")
@login_required
def notes_list():
    return jsonify({"notes": db.list_notes(uid())})


@app.get("/api/notes/<int:nid>")
@login_required
def note_get(nid):
    n = db.get_note(uid(), nid)
    return jsonify(n) if n else fail("Note not found.", 404)


@app.delete("/api/notes/<int:nid>")
@login_required
def note_delete(nid):
    return jsonify({"ok": True}) if db.delete_note(uid(), nid) else fail("Note not found.", 404)


@app.get("/api/notes/<int:nid>/download")
@login_required
def note_download(nid):
    n = db.get_note(uid(), nid)
    if not n:
        return fail("Note not found.", 404)
    if request.args.get("format", "pdf").lower() == "docx":
        return attachment(exports.note_docx(n["title"], n["content"]),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document", n["title"] + ".docx")
    return attachment(exports.note_pdf(n["title"], n["content"]), "application/pdf", n["title"] + ".pdf")


# ----------------------------------------------------------------------------- flashcards
def clean_cards(items, limit):
    out = []
    for x in items if isinstance(items, list) else []:
        if not isinstance(x, dict):
            continue
        q, a = str(x.get("question") or "").strip(), str(x.get("answer") or "").strip()
        diff = x.get("difficulty") if x.get("difficulty") in ("easy", "medium", "hard") else "medium"
        if q and a:
            out.append({"question": q, "answer": a, "difficulty": diff})
    return out[:limit]


@app.post("/api/flashcards")
@login_required
def flashcards_create():
    data = body()
    try:
        d = need_doc(data)
    except ValueError as e:
        return fail(str(e))
    count = to_int(data.get("count"), 10, 5, 20)
    cards = clean_cards(llm_client.flashcards([c["text"] for c in context_for(d["id"], None, 14)], count), count)
    if not cards:
        return fail("The AI could not create valid flashcards. Please try again.", 502)
    deck_id = db.create_deck(uid(), d["id"], cards)
    db.log_activity(uid(), "flashcards_generated", d["id"], minutes=5)
    return jsonify({"deck_id": deck_id, "cards": cards}), 201


@app.get("/api/flashcards")
@login_required
def flashcards_list():
    return jsonify({"decks": db.list_decks(uid())})


@app.get("/api/flashcards/<int:deck_id>")
@login_required
def flashcards_get(deck_id):
    deck, cards = db.get_deck(uid(), deck_id)
    return jsonify({"deck_id": deck_id, "cards": cards}) if deck else fail("Deck not found.", 404)


@app.delete("/api/flashcards/<int:deck_id>")
@login_required
def flashcards_delete(deck_id):
    return jsonify({"ok": True}) if db.delete_deck(uid(), deck_id) else fail("Deck not found.", 404)


# ----------------------------------------------------------------------------- quiz
@app.post("/api/quiz/generate")
@login_required
def quiz_generate():
    data = body()
    try:
        d = need_doc(data)
        qid = quiz_module.generate(uid(), d["id"], to_int(data.get("count"), 10, 5, 20),
                                   data.get("difficulty") if data.get("difficulty") in ("easy", "medium", "hard") else "medium")
    except ValueError as e:
        return fail(str(e))
    db.log_activity(uid(), "quiz_generated", d["id"], minutes=2)
    return jsonify({"quiz_id": qid}), 201


@app.get("/api/quizzes")
@login_required
def quiz_list():
    rows = db.list_quizzes(uid())
    for r in rows:
        r["percentage"] = round(100 * r["correct"] / r["answered"]) if r["answered"] else None
    return jsonify({"quizzes": rows})


@app.get("/api/quiz/<int:qid>")
@login_required
def quiz_get(qid):
    quiz, qs = db.get_quiz(uid(), qid)
    if not quiz:
        return fail("Quiz not found.", 404)
    out = []
    for q in qs:
        item = {"id": q["id"], "question": q["question"], "options": json.loads(q["options_json"]),
                "answered": q["student_answer"] is not None}
        if item["answered"]:  # never reveal the answer before the student has committed
            item.update(student_answer=q["student_answer"], correct_index=q["correct_index"],
                        correct=bool(q["answered_correct"]), explanation=q["explanation"])
        out.append(item)
    return jsonify({"quiz_id": qid, "difficulty": quiz["difficulty"], "document_title": quiz["document_title"], "questions": out})


@app.post("/api/quiz/<int:qid>/answer")
@login_required
def quiz_answer(qid):
    data = body()
    try:
        ans, qn = int(data["answer"]), int(data["question_id"])
        if not 0 <= ans <= 3:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return fail("Choose one of the four options.")
    row = db.answer_question(uid(), qid, qn, ans)
    if row is None:
        return fail("Question not found.", 404)
    if row == "answered":
        return fail("This question was already answered.", 409)
    db.update_topic(uid(), row["topic"] or "General", row["correct"])
    db.log_activity(uid(), "quiz_answered", row["document_id"], topic=row["topic"] or "General", minutes=1)
    return jsonify({"correct": row["correct"], "correct_index": row["correct_index"], "explanation": row["explanation"]})


@app.get("/api/quiz/<int:qid>/result")
@login_required
def quiz_result(qid):
    quiz, qs = db.get_quiz(uid(), qid)
    if not quiz:
        return fail("Quiz not found.", 404)
    done = [q for q in qs if q["answered_correct"] is not None]
    correct = sum(q["answered_correct"] for q in done)
    return jsonify({"total": len(qs), "answered": len(done), "correct": correct,
                    "percentage": round(correct * 100 / len(done)) if done else 0,
                    "details": [{"id": q["id"], "question": q["question"], "options": json.loads(q["options_json"]),
                                 "correct_index": q["correct_index"], "student_answer": q["student_answer"],
                                 "correct": q["answered_correct"], "explanation": q["explanation"]}
                                for q in qs if q["student_answer"] is not None]})


@app.delete("/api/quiz/<int:qid>")
@login_required
def quiz_delete(qid):
    return jsonify({"ok": True}) if db.delete_quiz(uid(), qid) else fail("Quiz not found.", 404)


# ----------------------------------------------------------------------------- planner
@app.post("/api/planner")
@login_required
def planner():
    data = body()
    days, minutes = to_int(data.get("days"), 5, 1, 30), to_int(data.get("minutes"), 120, 10, 600)
    try:
        sd = datetime.date.fromisoformat(data.get("start_date") or "")
    except ValueError:
        return fail("Choose a valid start date.")
    if sd < datetime.date.today() - datetime.timedelta(days=1):  # 1 day grace for time zones
        return fail("Past dates cannot be selected.")
    try:
        d = need_doc(data)
    except ValueError as e:
        return fail(str(e))
    raw = llm_client.planner([c["text"] for c in context_for(d["id"], None, 14)], days, str(sd), minutes, db.get_profile(uid()))
    raw = raw if isinstance(raw, list) else []
    plan = []
    for i in range(days):
        item = raw[i] if i < len(raw) and isinstance(raw[i], dict) else {}
        tasks = [str(t).strip() for t in item.get("tasks") or [] if str(t).strip()] \
            if isinstance(item.get("tasks"), list) else []
        plan.append({"day": i + 1, "date": str(sd + datetime.timedelta(days=i)),
                     "title": str(item.get("title") or "Revision and practice")[:120], "minutes": minutes,
                     "tasks": [{"text": t[:300], "done": False} for t in (tasks or ["Review notes", "Practice questions", "Flashcards"])]})
    title = f"Study plan - {d['title']} ({days} days)"
    pid = db.create_plan(uid(), d["id"], str(sd), days, minutes, plan, title)
    db.log_activity(uid(), "planner_created", d["id"], minutes=2)
    return jsonify({"plan_id": pid, "title": title, "plan": plan}), 201


@app.get("/api/plans")
@login_required
def plans_list():
    return jsonify({"plans": db.list_plans(uid())})


@app.post("/api/plans/<int:pid>/tasks")
@login_required
def plan_task(pid):
    data = body()
    try:
        plan = db.set_task(uid(), pid, int(data["day"]), int(data["index"]), bool(data["done"]))
    except (KeyError, TypeError):
        return fail("Invalid task.")
    except ValueError as e:
        return fail(str(e), 404)
    if plan is None:
        return fail("Plan not found.", 404)
    if data["done"]:
        db.log_activity(uid(), "plan_task_done", minutes=int(data.get("minutes", 10)) if str(data.get("minutes", "")).isdigit() else 10)
    return jsonify({"plan": plan})


@app.delete("/api/plans/<int:pid>")
@login_required
def plan_delete(pid):
    return jsonify({"ok": True}) if db.delete_plan(uid(), pid) else fail("Plan not found.", 404)


@app.get("/api/plans/<int:pid>/download")
@login_required
def plan_download(pid):
    p = db.get_plan(uid(), pid)
    if not p:
        return fail("Plan not found.", 404)
    return attachment(exports.plan_pdf(p["title"] or "Study plan", p["plan"]), "application/pdf", "StudyAI_Study_Plan.pdf")


# ----------------------------------------------------------------------------- dashboard / coach
@app.get("/api/dashboard")
@login_required
def dashboard():
    return jsonify(db.dashboard(uid(), tz()))


@app.get("/api/topics")
@login_required
def topics():
    return jsonify({"topics": db.topic_stats(uid())})


@app.get("/api/coach")
@login_required
def coach():
    dash = db.dashboard(uid(), tz())
    brief = {k: dash[k] for k in ("documents", "study_minutes", "quiz_accuracy", "current_streak", "today_minutes")}
    text = llm_client.coach(db.get_profile(uid()), brief, db.topic_stats(uid()))
    db.log_activity(uid(), "ai_coach", minutes=2)
    return jsonify({"answer": text})


@app.get("/api/ai-status")
@login_required
def ai_status():
    return jsonify(llm_client.check_nvidia_access())


if __name__ == "__main__":
    app.run(debug=os.getenv("STUDYAI_DEBUG", "0") == "1", port=int(os.getenv("PORT", "5001")))
