-- SQLite schema (generated)

CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS profiles (
 user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 course TEXT DEFAULT 'TYBSc CS', preferred_language TEXT DEFAULT 'English',
 explanation_style TEXT DEFAULT 'Detailed', daily_minutes INTEGER DEFAULT 120, exam_date TEXT);

CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 title TEXT NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 chunk_index INTEGER NOT NULL, text TEXT NOT NULL, tfidf_json TEXT);

CREATE TABLE IF NOT EXISTS chat_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 role TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 title TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS quizzes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
 difficulty TEXT NOT NULL, question_count INTEGER NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS quiz_questions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
 question TEXT NOT NULL, options_json TEXT NOT NULL, correct_index INTEGER NOT NULL,
 explanation TEXT NOT NULL, topic TEXT, source_chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
 student_answer INTEGER, answered_correct INTEGER);

CREATE TABLE IF NOT EXISTS flashcards (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
 question TEXT NOT NULL, answer TEXT NOT NULL, difficulty TEXT DEFAULT 'medium', created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS study_plans (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 start_date TEXT NOT NULL, days INTEGER NOT NULL, daily_minutes INTEGER NOT NULL,
 content_json TEXT NOT NULL, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS activity_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 activity_type TEXT NOT NULL, document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
 topic TEXT, minutes INTEGER DEFAULT 0, metadata_json TEXT, created_at REAL NOT NULL);

CREATE TABLE IF NOT EXISTS badges (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, description TEXT NOT NULL, threshold INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS user_badges (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 badge_id INTEGER NOT NULL REFERENCES badges(id) ON DELETE CASCADE,
 awarded_at REAL NOT NULL, PRIMARY KEY(user_id,badge_id));

CREATE TABLE IF NOT EXISTS topic_performance (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 topic TEXT NOT NULL, attempted INTEGER DEFAULT 0, correct INTEGER DEFAULT 0, UNIQUE(user_id,topic));

CREATE TABLE IF NOT EXISTS flashcard_decks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE, created_at REAL NOT NULL);

CREATE INDEX IF NOT EXISTS ix_documents_user ON documents(user_id);

CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id, chunk_index);

CREATE INDEX IF NOT EXISTS ix_chat_user_doc ON chat_messages(user_id, document_id, created_at);

CREATE INDEX IF NOT EXISTS ix_notes_user ON notes(user_id, created_at);

CREATE INDEX IF NOT EXISTS ix_quizzes_user ON quizzes(user_id, created_at);

CREATE INDEX IF NOT EXISTS ix_qq_quiz ON quiz_questions(quiz_id);

CREATE INDEX IF NOT EXISTS ix_activity_user ON activity_logs(user_id, created_at);

CREATE INDEX IF NOT EXISTS ix_plans_user ON study_plans(user_id, created_at);

CREATE INDEX IF NOT EXISTS ix_decks_user ON flashcard_decks(user_id, created_at);

-- v2 adds column: ALTER TABLE quiz_questions ADD COLUMN topic TEXT;

-- v2 adds column: ALTER TABLE flashcards ADD COLUMN deck_id INTEGER REFERENCES flashcard_decks(id) ON DELETE CASCADE;

-- v2 adds column: ALTER TABLE study_plans ADD COLUMN title TEXT;
