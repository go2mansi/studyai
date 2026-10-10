import db
import llm_client


def generate(uid, did, count, difficulty):
    chunks = db.get_chunks(did)
    if not chunks:
        raise ValueError("This document has no readable content.")
    selected = chunks[:min(len(chunks), max(8, count))]
    items = llm_client.quiz([c["text"] for c in selected], count, difficulty)
    if not isinstance(items, list):
        raise ValueError("The AI returned an invalid quiz. Please try again.")
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        opts = item.get("options")
        ci = item.get("correct_index")
        question = str(item.get("question") or "").strip()
        if (not question or not isinstance(opts, list) or len(opts) != 4 or len({str(o) for o in opts}) != 4
                or isinstance(ci, bool) or not isinstance(ci, int) or not 0 <= ci < 4):
            continue
        valid.append((question, [str(o) for o in opts], ci, str(item.get("explanation") or ""),
                      str(item.get("topic") or "General")[:80]))
        if len(valid) >= count:
            break
    if not valid:
        raise ValueError("The AI could not create valid questions. Try again.")
    qid = db.create_quiz(uid, did, difficulty, len(valid))
    for i, (q, opts, ci, expl, topic) in enumerate(valid):
        db.insert_question(qid, q, opts, ci, expl, selected[min(i, len(selected) - 1)]["id"], topic)
    return qid
