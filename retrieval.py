import math, re, json
from collections import Counter
import db

TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

def tokenize(text):
    return TOKEN_RE.findall(text.lower())

def build_index(document_id):
    chunks = db.get_chunks(document_id)
    if not chunks:
        return
    tokenized = [tokenize(c["text"]) for c in chunks]
    df = Counter()
    for toks in tokenized:
        df.update(set(toks))
    n = len(chunks)
    idf = {t: math.log((1+n)/(1+freq))+1 for t, freq in df.items()}
    pairs = []
    for chunk, toks in zip(chunks, tokenized):
        tf = Counter(toks)
        length = max(1, len(toks))
        pairs.append((chunk["id"], {t: (count/length)*idf[t] for t, count in tf.items()}))
    db.save_chunk_vectors(pairs)

def _cosine(a, b):
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[t]*b[t] for t in common)
    na = math.sqrt(sum(v*v for v in a.values())) or 1
    nb = math.sqrt(sum(v*v for v in b.values())) or 1
    return dot/(na*nb)

def query_index(document_id, query, top_k=7):
    chunks = db.get_chunks(document_id)
    q = Counter(tokenize(query))
    qlen = max(1, sum(q.values()))
    qvec = {t:c/qlen for t,c in q.items()}
    scored = []
    for c in chunks:
        if not c["tfidf_json"]:
            continue
        score = _cosine(qvec, json.loads(c["tfidf_json"]))
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x:x[0], reverse=True)
    return [c for _,c in scored[:top_k]]
