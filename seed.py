"""Synthetic demo data so every screen has content right after setup.

Everything here is written by hand for demonstration. It is NOT produced by the AI model and the
numbers are not real study statistics. Run:  python manage.py seed
"""
import datetime
import json
import random
import time

import db
import ingest
import retrieval
from werkzeug.security import generate_password_hash

DEMO_EMAIL = "demo@studyai.local"
DEMO_PASSWORD = "Demo@12345"

OS_TEXT = """Operating Systems - Sample Notes (synthetic demo material)

Process scheduling. The CPU scheduler selects which ready process runs next. First-Come First-Served runs processes in arrival order and suffers from the convoy effect. Shortest Job First minimises average waiting time but needs burst-time estimates and can starve long jobs. Round Robin gives each process a fixed time quantum; a very large quantum behaves like FCFS and a very small quantum wastes time on context switches. Priority scheduling can starve low priority processes, which aging solves by gradually raising priority.

Deadlocks. A deadlock needs four conditions at once: mutual exclusion, hold and wait, no preemption and circular wait. Prevention removes one condition. Avoidance, such as the Banker's algorithm, grants a request only if the system stays in a safe state. Detection builds a resource allocation graph and looks for cycles. Recovery terminates processes or preempts resources.

Memory management. Paging divides physical memory into fixed-size frames and logical memory into pages. A page table maps each page to a frame, and a translation lookaside buffer caches recent translations. Segmentation divides memory into logical units such as code and stack. Virtual memory lets a program use more memory than is physically installed; a page fault loads the missing page from disk. Page replacement policies include FIFO, LRU and Optimal. Thrashing happens when a process spends more time paging than executing.

File systems. A file system organises data into files and directories. Allocation methods are contiguous, linked and indexed. An inode stores file metadata and block pointers. Journaling records intended changes first so the file system can recover after a crash."""

DBMS_TEXT = """Database Management Systems - Sample Notes (synthetic demo material)

Normalisation. First normal form requires atomic values. Second normal form removes partial dependencies on part of a composite key. Third normal form removes transitive dependencies. Boyce-Codd normal form requires every determinant to be a candidate key. Normalisation reduces redundancy and update anomalies.

Transactions. A transaction is a logical unit of work with the ACID properties: atomicity, consistency, isolation and durability. Concurrency control uses locking or timestamps. Two-phase locking guarantees serialisability but can deadlock. Isolation levels such as read committed and serializable trade correctness against concurrency.

Indexing. A B-tree index keeps keys sorted and supports range queries in logarithmic time. A hash index supports equality lookups only. A clustered index determines physical row order, so a table has at most one."""

NOTE_MD = """# Round Robin vs FCFS (sample note)

## Key points
- **FCFS** runs processes in arrival order; simple but suffers from the **convoy effect**.
- **Round Robin** gives each process a time quantum, improving response time.

## Exam tip
A very large quantum makes Round Robin behave like FCFS; a very small quantum wastes time on context switches.
"""

QUIZ = [
    ("Which scheduling algorithm can starve long jobs?", ["Shortest Job First", "Round Robin", "FCFS", "Multilevel feedback with aging"], 0, "SJF always prefers short jobs, so long jobs may wait forever.", "Scheduling"),
    ("What does aging do in priority scheduling?", ["Raises waiting process priority", "Lowers quantum", "Kills old processes", "Adds more RAM"], 0, "Aging gradually raises the priority of waiting processes to prevent starvation.", "Scheduling"),
    ("Which is NOT a necessary condition for deadlock?", ["Preemption", "Mutual exclusion", "Hold and wait", "Circular wait"], 0, "Deadlock needs NO preemption.", "Deadlock"),
    ("The Banker's algorithm is used for deadlock...", ["Avoidance", "Detection", "Ignoring", "Recovery"], 0, "It grants requests only if the system stays in a safe state.", "Deadlock"),
    ("What does a page table map?", ["Pages to frames", "Files to inodes", "Processes to CPUs", "Keys to rows"], 0, "It maps logical pages to physical frames.", "Paging"),
    ("Thrashing occurs when...", ["Paging dominates execution time", "The CPU overheats", "Disk is full", "Cache is empty"], 0, "The process spends more time paging than executing.", "Paging"),
]
CARDS = [("What is the convoy effect?", "Short processes wait behind one long process under FCFS.", "easy"),
         ("Name the four deadlock conditions.", "Mutual exclusion, hold and wait, no preemption, circular wait.", "medium"),
         ("What is a TLB?", "A cache of recent page-table translations.", "medium"),
         ("What does 2NF remove?", "Partial dependencies on part of a composite key.", "hard"),
         ("What does ACID stand for?", "Atomicity, Consistency, Isolation, Durability.", "easy")]


def seed(reset=True):
    """Create (or recreate) the demo account. Must run inside ``db.connection()``."""
    random.seed(7)
    old = db.get_user_by_email(DEMO_EMAIL)
    if old and not reset:
        return old["id"]
    if old:
        db._c().run("DELETE FROM users WHERE id=?", (old["id"],))
    uid = db.create_user("Demo Student", DEMO_EMAIL, generate_password_hash(DEMO_PASSWORD))
    db.update_profile(uid, {"course": "TYBSc CS", "preferred_language": "English", "explanation_style": "Detailed",
                            "daily_minutes": 90, "exam_date": str(datetime.date.today() + datetime.timedelta(days=30))})
    docs = []
    for title, text in (("Operating Systems - sample notes.txt", OS_TEXT), ("DBMS - sample notes.txt", DBMS_TEXT)):
        did = db.create_document(uid, title)
        db.insert_chunks(did, ingest.chunk_text(text))
        retrieval.build_index(did)
        docs.append(did)
    db.create_note(uid, docs[0], "Round Robin vs FCFS (sample)", NOTE_MD)
    # a finished quiz with a realistic mix of right and wrong answers
    qid = db.create_quiz(uid, docs[0], "medium", len(QUIZ))
    wrong = {1, 3, 5}
    for i, (q, opts, ci, expl, topic) in enumerate(QUIZ):
        db.insert_question(qid, q, opts, ci, expl, None, topic)
    for i, row in enumerate(db.get_quiz(uid, qid)[1]):
        ok = i not in wrong
        db._c().run("UPDATE quiz_questions SET student_answer=?,answered_correct=? WHERE id=?",
                    (row["correct_index"] if ok else (row["correct_index"] + 1) % 4, int(ok), row["id"]))
        db.update_topic(uid, row["topic"], ok)
    db.create_deck(uid, docs[0], [{"question": q, "answer": a, "difficulty": d} for q, a, d in CARDS])
    start = datetime.date.today()
    plan = [{"day": i + 1, "date": str(start + datetime.timedelta(days=i)), "title": t, "minutes": 90,
             "tasks": [{"text": x, "done": i == 0} for x in tasks]}
            for i, (t, tasks) in enumerate([("Scheduling and deadlocks", ["Read scheduling notes", "Solve 5 Round Robin problems"]),
                                            ("Memory management", ["Revise paging", "Quiz on page replacement"]),
                                            ("Revision", ["Flashcards", "Full practice quiz"])])]
    db.create_plan(uid, docs[0], str(start), 3, 90, plan, "Study plan - Operating Systems (3 days) (sample)")
    now = time.time()
    for back in range(13, -1, -1):  # 14 days of synthetic activity with a few gaps
        if back in (9, 6):
            continue
        for kind, mins in random.sample([("ai_tutor", 3), ("quiz_answered", 1), ("notes_generated", 5), ("document_upload", 2)], 2):
            db._c().run("""INSERT INTO activity_logs(user_id,activity_type,document_id,topic,minutes,metadata_json,created_at)
                           VALUES(?,?,?,?,?,?,?)""", (uid, kind, docs[0], None, mins * random.randint(3, 8), "{}",
                                                      now - back * 86400 - random.randint(0, 3600)))
    msgs = [("user", "What is the convoy effect?"), ("assistant", "**Convoy effect** (sample answer): under FCFS, short processes queue behind one long CPU-bound process, which lowers utilisation.")]
    for role, content in msgs:
        db.add_chat(uid, docs[0], role, content)
    return uid
