import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("DATABASE_URL", None)
os.environ.pop("VERCEL", None)

import app as app_module  # noqa: E402
import llm_client  # noqa: E402

SAMPLE = ("Paging divides memory into fixed-size frames. A page table maps virtual pages to frames. "
          "Segmentation divides memory by logical units. Deadlock needs mutual exclusion, hold and wait, "
          "no preemption and circular wait. ") * 12


def fake_call(system, user, max_tokens=3000, json_schema=None, temperature=0.2):
    """Stands in for the HTTP call to NVIDIA; parsing/validation code above it is the real code."""
    if json_schema and "correct_index" in json.dumps(json_schema):
        return json.dumps([
            {"question": "What does a page table do?", "options": ["Maps pages to frames", "Stores files", "Schedules CPU", "Encrypts data"],
             "correct_index": 0, "explanation": "It maps virtual pages to frames.", "topic": "Paging"},
            {"question": "Bad: duplicate options", "options": ["a", "a", "b", "c"], "correct_index": 1, "explanation": "x", "topic": "X"},
            {"question": "Which is NOT a deadlock condition?", "options": ["Circular wait", "Hold and wait", "Preemption", "Mutual exclusion"],
             "correct_index": 2, "explanation": "Deadlock requires NO preemption.", "topic": "Deadlock"}])
    if json_schema and "answer" in json.dumps(json_schema):
        return '```json\n[{"question":"Define paging","answer":"Fixed-size memory frames","difficulty":"easy"},{"question":"","answer":"skip"}]\n```'
    if json_schema:
        return json.dumps([{"day": 1, "date": "x", "title": "Basics", "minutes": 1, "tasks": ["Read chapter", "Quiz"]}])
    return "## Answer\nPaging maps pages to frames."


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SQLITE_PATH"] = str(Path(self.tmp.name) / "t.db")
        app_module._schema_ready = False
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.patch = mock.patch.object(llm_client, "_call", fake_call)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def signup(self, client=None, email="stu@example.com"):
        c = client or self.client
        r = c.post("/api/auth/signup", json={"name": "Stu Dent", "email": email, "password": "password123"})
        assert r.status_code == 201, r.get_json()
        return c

    def upload(self, client=None, name="os.txt", data=SAMPLE.encode()):
        import io
        c = client or self.client
        return c.post("/api/upload", data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
