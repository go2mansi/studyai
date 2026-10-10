"""StudyAI database layer: one code base, two databases.

* SQLite     - default for local development (zero setup, file ``studyai.db``).
* PostgreSQL - used automatically when ``DATABASE_URL`` is set (Neon, local Postgres, Docker).

Schema changes are versioned in ``MIGRATIONS`` and applied by ``migrate()``.
SQL below is written once with ``?`` placeholders; the PostgreSQL path rewrites them to ``%s``.
"""
import contextlib
import contextvars
import datetime
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).parent


def database_url():
    url = (os.getenv("DATABASE_URL") or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def is_postgres():
    return database_url().startswith("postgresql://")


def sqlite_path():
    default = "/tmp/studyai.db" if os.getenv("VERCEL") else str(ROOT / "studyai.db")
    return os.getenv("SQLITE_PATH", default)


class Conn:
    """Minimal wrapper giving SQLite and psycopg the same tiny interface."""

    def __init__(self):
        self.pg = is_postgres()
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            # prepare_threshold=None: safe behind Neon's PgBouncer (transaction pooling) endpoint
            self.raw = psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10, prepare_threshold=None)
        else:
            self.raw = sqlite3.connect(sqlite_path())
            self.raw.row_factory = sqlite3.Row
            self.raw.execute("PRAGMA foreign_keys=ON")

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def _exec(self, sql, params=()):
        cur = self.raw.cursor()
        cur.execute(self._sql(sql), tuple(params))
        return cur

    def all(self, sql, params=()):
        cur = self._exec(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        cur.close()
        return rows

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def run(self, sql, params=()):
        cur = self._exec(sql, params)
        n = cur.rowcount
        cur.close()
        return n

    def insert(self, sql, params=()):
        """INSERT ... and return the new row id (both engines support RETURNING)."""
        cur = self._exec(sql + " RETURNING id", params)
        new_id = cur.fetchone()["id"]
        cur.close()
        return new_id

    def many(self, sql, rows):
        cur = self.raw.cursor()
        cur.executemany(self._sql(sql), rows)
        cur.close()

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        try:
            self.raw.close()
        except Exception:
            pass


_current = contextvars.ContextVar("studyai_conn", default=None)


def _c():
    c = _current.get()
    if c is None:
        raise RuntimeError("No database connection. Use `with db.connection():`.")
    return c


@contextlib.contextmanager
def connection():
    """Open one connection for a block (or one web request); commit on success."""
    c = Conn()
    token = _current.set(c)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        _current.reset(token)
        c.close()


def open_request():
    c = Conn()
    return c, _current.set(c)


def close_request(c, token, ok=True):
    try:
        c.commit() if ok else c.rollback()
    finally:
        _current.reset(token)
        c.close()


# --------------------------------------------------------------------------- schema
def _t(sql, pg):
    return (sql.replace("{PK}", "SERIAL PRIMARY KEY" if pg else "INTEGER PRIMARY KEY AUTOINCREMENT")
               .replace("{REAL}", "DOUBLE PRECISION" if pg else "REAL"))


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
 id {PK}, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS profiles (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 course TEXT DEFAULT 'TYBSc CS', preferred_language TEXT DEFAULT 'English',
 explanation_style TEXT DEFAULT 'Detailed', daily_minutes INTEGER DEFAULT 120, exam_date TEXT);
CREATE TABLE IF NOT EXISTS documents (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
 id {PK}, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 chunk_index INTEGER NOT NULL, text TEXT NOT NULL, tfidf_json TEXT);
CREATE TABLE IF NOT EXISTS chat_messages (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 role TEXT NOT NULL, content TEXT NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS notes (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 title TEXT NOT NULL, content TEXT NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS quizzes (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 difficulty TEXT NOT NULL, question_count INTEGER NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS quiz_questions (
 id {PK}, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
 question TEXT NOT NULL, options_json TEXT NOT NULL, correct_index INTEGER NOT NULL,
 explanation TEXT NOT NULL, topic TEXT, source_chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
 student_answer INTEGER, answered_correct INTEGER);
CREATE TABLE IF NOT EXISTS flashcards (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
 question TEXT NOT NULL, answer TEXT NOT NULL, difficulty TEXT DEFAULT 'medium', created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS study_plans (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 start_date TEXT NOT NULL, days INTEGER NOT NULL, daily_minutes INTEGER NOT NULL,
 content_json TEXT NOT NULL, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS activity_logs (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 activity_type TEXT NOT NULL, document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 topic TEXT, minutes INTEGER DEFAULT 0, metadata_json TEXT, created_at {REAL} NOT NULL);
CREATE TABLE IF NOT EXISTS badges (
 id {PK}, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, threshold INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS user_badges (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 badge_id INTEGER NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
 awarded_at {REAL} NOT NULL, PRIMARY KEY(user_id,badge_id));
CREATE TABLE IF NOT EXISTS topic_performance (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, attempted INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, UNIQUE(user_id,topic));
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS flashcard_decks (
 id {PK}, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE, created_at {REAL} NOT NULL);
CREATE INDEX IF NOT EXISTS ix_documents_user ON documents(user_id);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id, chunk_index);
CREATE INDEX IF NOT EXISTS ix_chat_user_doc ON chat_messages(user_id, document_id, created_at);
CREATE INDEX IF NOT EXISTS ix_notes_user ON notes(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_quizzes_user ON quizzes(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_qq_quiz ON quiz_questions(quiz_id);
CREATE INDEX IF NOT EXISTS ix_activity_user ON activity_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_plans_user ON study_plans(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_decks_user ON flashcard_decks(user_id, created_at);
"""

# (table, column, definition) added by v2 when missing (older StudyAI databases).
V2_COLUMNS = [("quiz_questions", "topic", "TEXT"),
              ("flashcards", "deck_id", "INTEGER REFERENCES flashcard_decks(id) ON DELETE CASCADE"),
              ("study_plans", "title", "TEXT")]

BADGES = [
    ("streak10", "Consistency Starter", "10 consecutive active days", 10),
    ("streak20", "Dedicated Learner", "20 consecutive active days", 20),
    ("streak30", "Study Champion", "30 consecutive active days", 30),
    ("quizmaster", "Quiz Master", "Average quiz accuracy of 90% or higher", 90),
]


def _script(sql, pg):
    return [s.strip() for s in _t(sql, pg).split(";") if s.strip()]


def schema_sql(pg=True):
    """Full schema as text (used to generate database/schema.sql)."""
    parts = _script(SCHEMA_V1, pg) + _script(SCHEMA_V2, pg)
    out = [p + ";" for p in parts]
    out += [f"-- v2 adds column: ALTER TABLE {t} ADD COLUMN {c} {d};" for t, c, d in V2_COLUMNS]
    return "\n\n".join(out) + "\n"


def _has_column(c, table, col):
    if c.pg:
        return c.one("SELECT 1 AS x FROM information_schema.columns WHERE table_name=? AND column_name=?",
                     (table, col)) is not None
    return any(r["name"] == col for r in c.all(f"PRAGMA table_info({table})"))


def migrate():
    """Create / upgrade tables. Safe to run repeatedly. Returns the schema version."""
    with connection() as c:
        pg = c.pg
        if pg:  # serialise concurrent cold starts
            c.run("SELECT pg_advisory_xact_lock(727274)")
        c.run("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at "
              + ("DOUBLE PRECISION" if pg else "REAL") + " NOT NULL)")
        done = {r["version"] for r in c.all("SELECT version FROM schema_migrations")}
        if 1 not in done:
            for stmt in _script(SCHEMA_V1, pg):
                c.run(stmt)
            c.run("INSERT INTO schema_migrations(version,applied_at) VALUES(1,?)", (time.time(),))
        if 2 not in done:
            for stmt in _script(SCHEMA_V2.split("CREATE INDEX")[0], pg):  # tables first
                c.run(stmt)
            for table, col, ddl in V2_COLUMNS:
                if not _has_column(c, table, col):
                    c.run(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            for stmt in _script("CREATE INDEX" + "CREATE INDEX".join(SCHEMA_V2.split("CREATE INDEX")[1:]), pg):
                c.run(stmt)
            c.run("INSERT INTO schema_migrations(version,applied_at) VALUES(2,?)", (time.time(),))
        for b in BADGES:
            c.run("INSERT INTO badges(code,name,description,threshold) VALUES(?,?,?,?) ON CONFLICT(code) DO NOTHING", b)
        return c.one("SELECT MAX(version) AS v FROM schema_migrations")["v"]


def ping():
    return _c().one("SELECT 1 AS ok")["ok"] == 1


# --------------------------------------------------------------------------- users
def create_user(name, email, password_hash):
    c = _c()
    uid = c.insert("INSERT INTO users(name,email,password_hash,created_at) VALUES(?,?,?,?)",
                   (name, email.lower().strip(), password_hash, time.time()))
    c.run("INSERT INTO profiles(user_id) VALUES(?)", (uid,))
    return uid


def get_user_by_email(email):
    return _c().one("SELECT * FROM users WHERE email=?", (email.lower().strip(),))


def get_user(uid):
    return _c().one("SELECT * FROM users WHERE id=?", (uid,))


def get_profile(uid):
    return _c().one("SELECT * FROM profiles WHERE user_id=?", (uid,))


def update_profile(uid, data):
    _c().run("""UPDATE profiles SET course=?,preferred_language=?,explanation_style=?,daily_minutes=?,exam_date=?
                WHERE user_id=?""",
             (data["course"], data["preferred_language"], data["explanation_style"],
              data["daily_minutes"], data.get("exam_date") or None, uid))


# --------------------------------------------------------------------------- documents
def create_document(uid, title):
    return _c().insert("INSERT INTO documents(user_id,title,created_at) VALUES(?,?,?)", (uid, title, time.time()))


def list_documents(uid):
    return _c().all("""SELECT d.id,d.title,d.created_at,
                       (SELECT COUNT(*) FROM chunks k WHERE k.document_id=d.id) AS chunks
                       FROM documents d WHERE d.user_id=? ORDER BY d.created_at DESC""", (uid,))


def get_document(uid, did):
    return _c().one("SELECT * FROM documents WHERE id=? AND user_id=?", (did, uid))


def delete_document(uid, did):
    return _c().run("DELETE FROM documents WHERE id=? AND user_id=?", (did, uid)) > 0


def insert_chunks(did, texts):
    _c().many("INSERT INTO chunks(document_id,chunk_index,text) VALUES(?,?,?)",
              [(did, i, t) for i, t in enumerate(texts)])


def get_chunks(did):
    return _c().all("SELECT * FROM chunks WHERE document_id=? ORDER BY chunk_index", (did,))


def save_chunk_vectors(pairs):
    _c().many("UPDATE chunks SET tfidf_json=? WHERE id=?", [(json.dumps(v), cid) for cid, v in pairs])


# --------------------------------------------------------------------------- chat
def add_chat(uid, did, role, content):
    _c().run("INSERT INTO chat_messages(user_id,document_id,role,content,created_at) VALUES(?,?,?,?,?)",
             (uid, did, role, content, time.time()))


def chat_history(uid, did, limit=12):
    rows = _c().all("""SELECT role,content,created_at FROM chat_messages WHERE user_id=? AND document_id=?
                       ORDER BY id DESC LIMIT ?""", (uid, did, limit))
    return list(reversed(rows))


def clear_chat(uid, did):
    _c().run("DELETE FROM chat_messages WHERE user_id=? AND document_id=?", (uid, did))


# --------------------------------------------------------------------------- notes
def create_note(uid, did, title, content):
    return _c().insert("INSERT INTO notes(user_id,document_id,title,content,created_at) VALUES(?,?,?,?,?)",
                       (uid, did, title, content, time.time()))


def list_notes(uid):
    return _c().all("""SELECT n.*,d.title AS document_title FROM notes n LEFT JOIN documents d ON d.id=n.document_id
                       WHERE n.user_id=? ORDER BY n.created_at DESC""", (uid,))


def get_note(uid, nid):
    return _c().one("SELECT * FROM notes WHERE id=? AND user_id=?", (nid, uid))


def delete_note(uid, nid):
    return _c().run("DELETE FROM notes WHERE id=? AND user_id=?", (nid, uid)) > 0


# --------------------------------------------------------------------------- quiz
def create_quiz(uid, did, difficulty, count):
    return _c().insert("INSERT INTO quizzes(user_id,document_id,difficulty,question_count,created_at) VALUES(?,?,?,?,?)",
                       (uid, did, difficulty, count, time.time()))


def insert_question(qid, q, options, correct, explanation, chunk_id, topic="General"):
    _c().run("""INSERT INTO quiz_questions(quiz_id,question,options_json,correct_index,explanation,topic,source_chunk_id)
                VALUES(?,?,?,?,?,?,?)""", (qid, q, json.dumps(options), correct, explanation, topic, chunk_id))


def get_quiz(uid, qid):
    quiz = _c().one("""SELECT q.*,d.title AS document_title FROM quizzes q JOIN documents d ON d.id=q.document_id
                       WHERE q.id=? AND q.user_id=?""", (qid, uid))
    if not quiz:
        return None, []
    return quiz, _c().all("SELECT * FROM quiz_questions WHERE quiz_id=? ORDER BY id", (qid,))


def list_quizzes(uid, limit=20):
    return _c().all("""SELECT q.id,q.difficulty,q.created_at,d.title AS document_title,
        (SELECT COUNT(*) FROM quiz_questions x WHERE x.quiz_id=q.id) AS total,
        (SELECT COUNT(*) FROM quiz_questions x WHERE x.quiz_id=q.id AND x.answered_correct IS NOT NULL) AS answered,
        (SELECT COALESCE(SUM(x.answered_correct),0) FROM quiz_questions x WHERE x.quiz_id=q.id) AS correct
        FROM quizzes q JOIN documents d ON d.id=q.document_id WHERE q.user_id=? ORDER BY q.created_at DESC LIMIT ?""",
                       (uid, limit))


def delete_quiz(uid, qid):
    return _c().run("DELETE FROM quizzes WHERE id=? AND user_id=?", (qid, uid)) > 0


def answer_question(uid, qid, question_id, answer):
    """Returns None (not found), 'answered' (already answered) or the question row with .correct."""
    row = _c().one("""SELECT qq.*,q.document_id FROM quiz_questions qq JOIN quizzes q ON q.id=qq.quiz_id
                      WHERE qq.id=? AND qq.quiz_id=? AND q.user_id=?""", (question_id, qid, uid))
    if not row:
        return None
    if row["student_answer"] is not None:
        return "answered"
    correct = int(answer) == int(row["correct_index"])
    _c().run("UPDATE quiz_questions SET student_answer=?,answered_correct=? WHERE id=?",
             (int(answer), int(correct), question_id))
    row["correct"] = correct
    return row


# --------------------------------------------------------------------------- flashcards
def create_deck(uid, did, cards):
    c = _c()
    deck_id = c.insert("INSERT INTO flashcard_decks(user_id,document_id,created_at) VALUES(?,?,?)",
                       (uid, did, time.time()))
    c.many("INSERT INTO flashcards(user_id,document_id,deck_id,question,answer,difficulty,created_at) VALUES(?,?,?,?,?,?,?)",
           [(uid, did, deck_id, x["question"], x["answer"], x["difficulty"], time.time()) for x in cards])
    return deck_id


def list_decks(uid):
    return _c().all("""SELECT k.id,k.created_at,d.title AS document_title,
                       (SELECT COUNT(*) FROM flashcards f WHERE f.deck_id=k.id) AS cards
                       FROM flashcard_decks k LEFT JOIN documents d ON d.id=k.document_id
                       WHERE k.user_id=? ORDER BY k.created_at DESC""", (uid,))


def get_deck(uid, deck_id):
    deck = _c().one("SELECT * FROM flashcard_decks WHERE id=? AND user_id=?", (deck_id, uid))
    if not deck:
        return None, []
    return deck, _c().all("SELECT question,answer,difficulty FROM flashcards WHERE deck_id=? ORDER BY id", (deck_id,))


def delete_deck(uid, deck_id):
    return _c().run("DELETE FROM flashcard_decks WHERE id=? AND user_id=?", (deck_id, uid)) > 0


# --------------------------------------------------------------------------- study plans
def create_plan(uid, did, start_date, days, minutes, plan, title):
    return _c().insert("""INSERT INTO study_plans(user_id,document_id,start_date,days,daily_minutes,content_json,title,created_at)
                          VALUES(?,?,?,?,?,?,?,?)""", (uid, did, start_date, days, minutes, json.dumps(plan), title, time.time()))


def _plan(row):
    row["plan"] = json.loads(row.pop("content_json"))
    return row


def list_plans(uid):
    rows = _c().all("""SELECT p.*,d.title AS document_title FROM study_plans p LEFT JOIN documents d ON d.id=p.document_id
                       WHERE p.user_id=? ORDER BY p.created_at DESC""", (uid,))
    return [_plan(r) for r in rows]


def get_plan(uid, pid):
    r = _c().one("SELECT * FROM study_plans WHERE id=? AND user_id=?", (pid, uid))
    return _plan(r) if r else None


def set_task(uid, pid, day, index, done):
    p = get_plan(uid, pid)
    if not p:
        return None
    try:
        task = p["plan"][day - 1]["tasks"][index]
    except (IndexError, KeyError):
        raise ValueError("Task not found.")
    task["done"] = bool(done)
    _c().run("UPDATE study_plans SET content_json=? WHERE id=? AND user_id=?", (json.dumps(p["plan"]), pid, uid))
    return p["plan"]


def delete_plan(uid, pid):
    return _c().run("DELETE FROM study_plans WHERE id=? AND user_id=?", (pid, uid)) > 0


# --------------------------------------------------------------------------- activity / stats
def log_activity(uid, typ, did=None, topic=None, minutes=0, metadata=None):
    _c().run("""INSERT INTO activity_logs(user_id,activity_type,document_id,topic,minutes,metadata_json,created_at)
                VALUES(?,?,?,?,?,?,?)""", (uid, typ, did, topic, minutes, json.dumps(metadata or {}), time.time()))


def update_topic(uid, topic, correct):
    if not topic:
        return
    _c().run("""INSERT INTO topic_performance(user_id,topic,attempted,correct) VALUES(?,?,1,?)
                ON CONFLICT(user_id,topic) DO UPDATE SET attempted=topic_performance.attempted+1,
                correct=topic_performance.correct+excluded.correct""", (uid, topic, int(correct)))


def topic_stats(uid):
    rows = _c().all("SELECT topic,attempted,correct FROM topic_performance WHERE user_id=?", (uid,))
    for r in rows:
        r["accuracy"] = round(100.0 * r["correct"] / r["attempted"], 1) if r["attempted"] else 0
    return sorted(rows, key=lambda r: r["accuracy"])


def _local_date(ts, tz_min):
    return (datetime.datetime.fromtimestamp(ts, datetime.timezone.utc) + datetime.timedelta(minutes=-tz_min)).date()


def _active_dates(uid, tz_min):
    rows = _c().all("SELECT created_at FROM activity_logs WHERE user_id=?", (uid,))
    return sorted({_local_date(r["created_at"], tz_min) for r in rows}, reverse=True)


def streak(uid, tz_min=0):
    ds = _active_dates(uid, tz_min)
    if not ds:
        return 0, 0
    today = _local_date(time.time(), tz_min)
    current = 0
    if ds[0] in (today, today - datetime.timedelta(days=1)):
        expected = ds[0]
        for d in ds:
            if d == expected:
                current += 1
                expected -= datetime.timedelta(days=1)
            else:
                break
    longest = run = 0
    prev = None
    for d in reversed(ds):
        run = run + 1 if prev is not None and d == prev + datetime.timedelta(days=1) else 1
        longest = max(longest, run)
        prev = d
    return current, longest


def quiz_accuracy(uid):
    r = _c().one("""SELECT COUNT(*) AS n, COALESCE(SUM(qq.answered_correct),0) AS ok FROM quiz_questions qq
                    JOIN quizzes q ON q.id=qq.quiz_id WHERE q.user_id=? AND qq.answered_correct IS NOT NULL""", (uid,))
    return (round(100 * r["ok"] / r["n"]) if r["n"] else 0), r["n"]


def award_badges(uid, tz_min=0):
    current, _ = streak(uid, tz_min)
    acc, answered = quiz_accuracy(uid)
    earned = [code for code, _n, _d, th in BADGES[:3] if current >= th]
    if answered >= 10 and acc >= 90:
        earned.append("quizmaster")
    for code in earned:
        b = _c().one("SELECT id FROM badges WHERE code=?", (code,))
        _c().run("INSERT INTO user_badges(user_id,badge_id,awarded_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                 (uid, b["id"], time.time()))


def badges(uid):
    return _c().all("""SELECT b.code,b.name,b.description,ub.awarded_at FROM user_badges ub
                       JOIN badges b ON b.id=ub.badge_id WHERE ub.user_id=? ORDER BY ub.awarded_at DESC""", (uid,))


def activity_series(uid, days=14, tz_min=0):
    today = _local_date(time.time(), tz_min)
    start = today - datetime.timedelta(days=days - 1)
    since = time.time() - (days + 2) * 86400
    rows = _c().all("SELECT created_at,minutes FROM activity_logs WHERE user_id=? AND created_at>=?", (uid, since))
    buckets = {start + datetime.timedelta(days=i): 0 for i in range(days)}
    for r in rows:
        d = _local_date(r["created_at"], tz_min)
        if d in buckets:
            buckets[d] += r["minutes"] or 0
    return [{"date": d.isoformat(), "minutes": m} for d, m in buckets.items()]


def recent_activity(uid, limit=8):
    return _c().all("""SELECT a.activity_type,a.topic,a.minutes,a.created_at,d.title AS document_title
                       FROM activity_logs a LEFT JOIN documents d ON d.id=a.document_id
                       WHERE a.user_id=? ORDER BY a.id DESC LIMIT ?""", (uid, limit))


def dashboard(uid, tz_min=0):
    c = _c()
    docs = c.one("SELECT COUNT(*) AS n FROM documents WHERE user_id=?", (uid,))["n"]
    questions = c.one("SELECT COUNT(*) AS n FROM chat_messages WHERE user_id=? AND role='user'", (uid,))["n"]
    minutes = c.one("SELECT COALESCE(SUM(minutes),0) AS n FROM activity_logs WHERE user_id=?", (uid,))["n"]
    acc, answered = quiz_accuracy(uid)
    cur, longest = streak(uid, tz_min)
    award_badges(uid, tz_min)
    series = activity_series(uid, 14, tz_min)
    today_minutes = series[-1]["minutes"]
    return {"documents": docs, "questions": questions, "study_minutes": minutes, "quiz_accuracy": acc,
            "quiz_answered": answered, "current_streak": cur, "longest_streak": longest,
            "today_minutes": today_minutes, "badges": badges(uid), "activity": series,
            "recent": recent_activity(uid)}


def search(uid, q, limit=20):
    like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    out = []
    for r in _c().all("SELECT id,title FROM documents WHERE user_id=? AND LOWER(title) LIKE LOWER(?) ESCAPE '\\' LIMIT ?",
                      (uid, like, limit)):
        out.append({"type": "document", "id": r["id"], "title": r["title"], "snippet": ""})
    for r in _c().all("""SELECT id,title,content FROM notes WHERE user_id=? AND
                         (LOWER(title) LIKE LOWER(?) ESCAPE '\\' OR LOWER(content) LIKE LOWER(?) ESCAPE '\\') LIMIT ?""",
                      (uid, like, like, limit)):
        out.append({"type": "note", "id": r["id"], "title": r["title"], "snippet": r["content"][:140]})
    for r in _c().all("""SELECT f.deck_id AS id,f.question FROM flashcards f WHERE f.user_id=? AND
                         (LOWER(f.question) LIKE LOWER(?) ESCAPE '\\' OR LOWER(f.answer) LIKE LOWER(?) ESCAPE '\\') LIMIT ?""",
                      (uid, like, like, limit)):
        out.append({"type": "flashcard", "id": r["id"], "title": r["question"][:90], "snippet": ""})
    return out[:limit]


def reset_user_data(uid):
    for t in ("documents", "notes", "study_plans", "flashcard_decks", "activity_logs", "topic_performance", "chat_messages"):
        _c().run(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    _c().run("DELETE FROM user_badges WHERE user_id=?", (uid,))
