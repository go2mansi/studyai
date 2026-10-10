"""Tiny local stand-in for NVIDIA's chat-completions endpoint. TEST/UI-CHECK USE ONLY.

    python tests/fake_nvidia.py 9100
Then run the app with NVIDIA_API_KEY=test NVIDIA_API_BASE=http://127.0.0.1:9100/v1/chat/completions
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        user = req["messages"][-1]["content"]
        if "correct_index" in user:
            out = json.dumps([{"question": f"Sample question {i}?", "options": [f"A{i}", f"B{i}", f"C{i}", f"D{i}"], "correct_index": i % 4,
                               "explanation": "Because of the source.", "topic": "Paging" if i % 2 else "Deadlock"} for i in range(1, 4)])
        elif "OUTPUT FORMAT" in user and '"answer"' in user:
            out = json.dumps([{"question": "What is paging?", "answer": "Fixed-size frames.", "difficulty": "easy"}, {"question": "What is TLB?", "answer": "Translation cache.", "difficulty": "medium"}])
        elif "OUTPUT FORMAT" in user:
            out = json.dumps([{"day": 1, "date": "x", "title": "Basics", "minutes": 60, "tasks": ["Read", "Practice"]}])
        else:
            out = "## Answer\n- **Paging** maps pages to frames.\n\n| A | B |\n|---|---|\n| 1 | 2 |"
        body = json.dumps({"choices": [{"message": {"content": out}}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 9100), H).serve_forever()
