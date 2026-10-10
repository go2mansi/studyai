import io
import unittest
from unittest import mock

import db
import llm_client
from tests.helpers import AppCase, SAMPLE


class HealthAndAuth(AppCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["db_ok"])

    def test_requires_login(self):
        for path in ("/api/me", "/api/documents", "/api/dashboard", "/api/notes", "/api/plans"):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_signup_validation(self):
        bad = [{"name": "A", "email": "a@x.com", "password": "password123"},
               {"name": "Ann", "email": "not-an-email", "password": "password123"},
               {"name": "Ann", "email": "a@x.com", "password": "short"}, {}]
        for payload in bad:
            self.assertEqual(self.client.post("/api/auth/signup", json=payload).status_code, 400, payload)

    def test_signup_login_logout_duplicate(self):
        self.signup()
        self.assertEqual(self.client.get("/api/me").get_json()["user"]["email"], "stu@example.com")
        self.assertEqual(self.client.post("/api/auth/signup", json={"name": "Stu", "email": "STU@example.com", "password": "password123"}).status_code, 409)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/me").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "stu@example.com", "password": "wrong-pass"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "stu@example.com", "password": "password123"}).status_code, 200)

    def test_password_is_hashed(self):
        self.signup()
        with db.connection():
            h = db.get_user_by_email("stu@example.com")["password_hash"]
        self.assertNotIn("password123", h)

    def test_profile_update(self):
        self.signup()
        r = self.client.put("/api/profile", json={"course": "MSc", "preferred_language": "Hindi", "explanation_style": "Simple", "daily_minutes": 99999})
        self.assertEqual(r.get_json()["profile"]["daily_minutes"], 600)
        self.assertEqual(self.client.put("/api/profile", json={"explanation_style": "Weird"}).status_code, 400)
        self.assertEqual(self.client.put("/api/profile", json={"exam_date": "nope"}).status_code, 400)


class Documents(AppCase):
    def test_upload_list_delete(self):
        self.signup()
        r = self.upload()
        self.assertEqual(r.status_code, 201)
        did = r.get_json()["document_id"]
        docs = self.client.get("/api/documents").get_json()["documents"]
        self.assertEqual(docs[0]["title"], "os.txt")
        self.assertGreater(docs[0]["chunks"], 0)
        self.assertEqual(self.client.delete(f"/api/documents/{did}").status_code, 200)
        self.assertEqual(self.client.get("/api/documents").get_json()["documents"], [])
        self.assertEqual(self.client.delete(f"/api/documents/{did}").status_code, 404)

    def test_upload_rejections(self):
        self.signup()
        self.assertEqual(self.upload(name="x.exe", data=b"MZ").status_code, 415)
        self.assertEqual(self.upload(name="e.txt", data=b"").status_code, 400)
        self.assertEqual(self.upload(name="bad.pdf", data=b"not a pdf").status_code, 400)
        self.assertEqual(self.client.post("/api/upload", data={}, content_type="multipart/form-data").status_code, 400)

    def test_users_are_isolated(self):
        self.signup()
        did = self.upload().get_json()["document_id"]
        other = self.signup(self.client.application.test_client(), "other@example.com")
        self.assertEqual(other.get("/api/documents").get_json()["documents"], [])
        self.assertEqual(other.delete(f"/api/documents/{did}").status_code, 404)
        r = other.post("/api/chat", json={"document_id": did, "question": "hi"})
        self.assertEqual(r.status_code, 400)

    def test_search(self):
        self.signup()
        self.upload(name="operating-systems.txt")
        r = self.client.get("/api/search?q=operating").get_json()["results"]
        self.assertEqual(r[0]["type"], "document")
        self.assertEqual(self.client.get("/api/search?q=zzzzzz").get_json()["results"], [])
        self.assertEqual(self.client.get("/api/search?q=%25").get_json()["results"], [])  # % is literal, not a wildcard


class AIFeatures(AppCase):
    def setUp(self):
        super().setUp()
        self.signup()
        self.did = self.upload().get_json()["document_id"]

    def test_chat_persists_history(self):
        r = self.client.post("/api/chat", json={"document_id": self.did, "question": "What is paging?"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Paging", r.get_json()["answer"])
        self.assertTrue(r.get_json()["sources"])
        hist = self.client.get(f"/api/chat/history?document_id={self.did}").get_json()["messages"]
        self.assertEqual([m["role"] for m in hist], ["user", "assistant"])
        self.client.delete(f"/api/chat?document_id={self.did}")
        self.assertEqual(self.client.get(f"/api/chat/history?document_id={self.did}").get_json()["messages"], [])

    def test_chat_validation(self):
        self.assertEqual(self.client.post("/api/chat", json={"document_id": self.did, "question": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/api/chat", json={"question": "x"}).status_code, 400)

    def test_ai_failure_is_friendly_502(self):
        with mock.patch.object(llm_client, "_call", side_effect=llm_client.LLMError("NVIDIA_API_KEY is not configured.")):
            r = self.client.post("/api/chat", json={"document_id": self.did, "question": "hi"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("NVIDIA_API_KEY", r.get_json()["error"])
        self.assertEqual(self.client.get(f"/api/chat/history?document_id={self.did}").get_json()["messages"], [])

    def test_notes_crud_and_export(self):
        r = self.client.post("/api/notes", json={"document_id": self.did, "request": "paging"})
        nid = r.get_json()["id"]
        self.assertEqual(len(self.client.get("/api/notes").get_json()["notes"]), 1)
        pdf = self.client.get(f"/api/notes/{nid}/download?format=pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        docx = self.client.get(f"/api/notes/{nid}/download?format=docx")
        self.assertTrue(docx.data.startswith(b"PK"))
        self.assertEqual(self.client.delete(f"/api/notes/{nid}").status_code, 200)
        self.assertEqual(self.client.get(f"/api/notes/{nid}").status_code, 404)

    def test_flashcards_validated_and_saved(self):
        r = self.client.post("/api/flashcards", json={"document_id": self.did, "count": 5})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.get_json()["cards"]), 1)  # the card with an empty question was dropped
        deck = r.get_json()["deck_id"]
        self.assertEqual(self.client.get("/api/flashcards").get_json()["decks"][0]["cards"], 1)
        self.assertEqual(self.client.get(f"/api/flashcards/{deck}").get_json()["cards"][0]["question"], "Define paging")
        self.assertEqual(self.client.delete(f"/api/flashcards/{deck}").status_code, 200)

    def test_quiz_full_flow(self):
        qid = self.client.post("/api/quiz/generate", json={"document_id": self.did, "count": 5}).get_json()["quiz_id"]
        quiz = self.client.get(f"/api/quiz/{qid}").get_json()
        self.assertEqual(len(quiz["questions"]), 2)  # the duplicate-option question was rejected
        self.assertNotIn("correct_index", quiz["questions"][0])  # no answer leak before answering
        q1 = quiz["questions"][0]
        a = self.client.post(f"/api/quiz/{qid}/answer", json={"question_id": q1["id"], "answer": 0}).get_json()
        self.assertTrue(a["correct"])
        self.assertEqual(self.client.post(f"/api/quiz/{qid}/answer", json={"question_id": q1["id"], "answer": 1}).status_code, 409)
        q2 = quiz["questions"][1]
        self.assertFalse(self.client.post(f"/api/quiz/{qid}/answer", json={"question_id": q2["id"], "answer": 0}).get_json()["correct"])
        self.assertEqual(self.client.post(f"/api/quiz/{qid}/answer", json={"question_id": q2["id"], "answer": 9}).status_code, 400)
        res = self.client.get(f"/api/quiz/{qid}/result").get_json()
        self.assertEqual((res["correct"], res["answered"], res["percentage"]), (1, 2, 50))
        topics = {t["topic"]: t for t in self.client.get("/api/topics").get_json()["topics"]}
        self.assertEqual(topics["Deadlock"]["accuracy"], 0)
        self.assertEqual(topics["Paging"]["accuracy"], 100)
        self.assertEqual(self.client.get("/api/quizzes").get_json()["quizzes"][0]["percentage"], 50)
        self.assertEqual(self.client.delete(f"/api/quiz/{qid}").status_code, 200)

    def test_quiz_other_user_cannot_answer(self):
        qid = self.client.post("/api/quiz/generate", json={"document_id": self.did}).get_json()["quiz_id"]
        qq = self.client.get(f"/api/quiz/{qid}").get_json()["questions"][0]["id"]
        other = self.signup(self.client.application.test_client(), "o@example.com")
        self.assertEqual(other.post(f"/api/quiz/{qid}/answer", json={"question_id": qq, "answer": 0}).status_code, 404)

    def test_planner(self):
        import datetime
        start = str(datetime.date.today() + datetime.timedelta(days=1))
        r = self.client.post("/api/planner", json={"document_id": self.did, "days": 3, "start_date": start, "minutes": 60})
        self.assertEqual(r.status_code, 201)
        plan = r.get_json()["plan"]
        self.assertEqual([d["date"] for d in plan][0], start)
        self.assertEqual(len(plan), 3)
        self.assertEqual(plan[2]["title"], "Revision and practice")  # model returned 1 day, rest filled safely
        pid = r.get_json()["plan_id"]
        t = self.client.post(f"/api/plans/{pid}/tasks", json={"day": 1, "index": 0, "done": True})
        self.assertTrue(t.get_json()["plan"][0]["tasks"][0]["done"])
        self.assertTrue(self.client.get("/api/plans").get_json()["plans"][0]["plan"][0]["tasks"][0]["done"])
        self.assertEqual(self.client.post(f"/api/plans/{pid}/tasks", json={"day": 9, "index": 0, "done": True}).status_code, 404)
        self.assertTrue(self.client.get(f"/api/plans/{pid}/download").data.startswith(b"%PDF"))
        bad = self.client.post("/api/planner", json={"document_id": self.did, "days": 3, "start_date": "2020-01-01"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.delete(f"/api/plans/{pid}").status_code, 200)

    def test_dashboard_reflects_activity(self):
        self.client.post("/api/chat", json={"document_id": self.did, "question": "What is paging?"})
        d = self.client.get("/api/dashboard", headers={"X-TZ-Offset": "-330"}).get_json()
        self.assertEqual(d["documents"], 1)
        self.assertEqual(d["questions"], 1)
        self.assertEqual(d["current_streak"], 1)
        self.assertGreaterEqual(d["today_minutes"], 5)
        self.assertEqual(len(d["activity"]), 14)
        self.assertTrue(d["recent"])

    def test_coach(self):
        self.assertEqual(self.client.get("/api/coach").status_code, 200)


class LLMClient(unittest.TestCase):
    def _resp(self, status, payload=None, text=""):
        r = mock.Mock(status_code=status, text=text, headers={})
        r.json.return_value = payload
        return r

    def test_410_stops_and_explains(self):
        with mock.patch.object(llm_client, "API_KEY", "k"), \
             mock.patch("requests.post", return_value=self._resp(410, text="Gone: public api endpoint")) as post:
            with self.assertRaises(llm_client.LLMError) as cm:
                llm_client._call("s", "u")
        self.assertIn("410", str(cm.exception))
        self.assertEqual(post.call_count, 1)

    def test_falls_back_to_next_model_on_server_error(self):
        ok = self._resp(200, {"choices": [{"message": {"content": " hello "}}]})
        with mock.patch.object(llm_client, "API_KEY", "k"), \
             mock.patch("requests.post", side_effect=[self._resp(503, text="x"), ok]):
            self.assertEqual(llm_client._call("s", "u"), "hello")

    def test_missing_key(self):
        with mock.patch.object(llm_client, "API_KEY", ""):
            with self.assertRaises(llm_client.LLMError):
                llm_client._call("s", "u")

    def test_clean_json(self):
        self.assertEqual(llm_client._clean_json('Sure!\n```json\n[{"a":1}]\n```'), [{"a": 1}])
        with self.assertRaises(llm_client.LLMError):
            llm_client._clean_json("no json here")


class Retrieval(AppCase):
    def test_tfidf_ranks_relevant_chunk_first(self):
        import retrieval
        db.migrate()
        with db.connection():
            u = db.create_user("A", "a@x.com", "h")
            did = db.create_document(u, "d")
            db.insert_chunks(did, ["bananas and apples are fruit", "paging maps virtual pages to physical frames", "the weather is nice"])
            retrieval.build_index(did)
            top = retrieval.query_index(did, "virtual memory paging frames", 2)
        self.assertEqual(top[0]["chunk_index"], 1)


class Migrations(AppCase):
    def test_upgrades_old_database(self):
        import sqlite3
        path = db.sqlite_path()
        con = sqlite3.connect(path)
        con.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,password_hash TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE documents(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,document_id INTEGER NOT NULL,chunk_index INTEGER NOT NULL,text TEXT NOT NULL,tfidf_json TEXT);
        CREATE TABLE quizzes(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,document_id INTEGER NOT NULL,difficulty TEXT NOT NULL,question_count INTEGER NOT NULL,created_at REAL NOT NULL);
        CREATE TABLE quiz_questions(id INTEGER PRIMARY KEY AUTOINCREMENT,quiz_id INTEGER NOT NULL,question TEXT NOT NULL,options_json TEXT NOT NULL,correct_index INTEGER NOT NULL,explanation TEXT NOT NULL,source_chunk_id INTEGER,student_answer INTEGER,answered_correct INTEGER);
        CREATE TABLE flashcards(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,document_id INTEGER,question TEXT NOT NULL,answer TEXT NOT NULL,difficulty TEXT,created_at REAL NOT NULL);
        CREATE TABLE study_plans(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,document_id INTEGER,start_date TEXT NOT NULL,days INTEGER NOT NULL,daily_minutes INTEGER NOT NULL,content_json TEXT NOT NULL,created_at REAL NOT NULL);
        INSERT INTO users(name,email,password_hash,created_at) VALUES('Old','old@x.com','h',1);""")
        con.commit(); con.close()
        self.assertEqual(db.migrate(), 2)
        with db.connection() as c:
            cols = {r["name"] for r in c.all("PRAGMA table_info(quiz_questions)")}
            self.assertIn("topic", cols)
            self.assertEqual(db.get_user_by_email("old@x.com")["name"], "Old")
        self.assertEqual(db.migrate(), 2)  # idempotent


if __name__ == "__main__":
    unittest.main()
