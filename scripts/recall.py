#!/usr/bin/env python3
"""Search what you already said, did and wrote: past Claude Code sessions, project memories, rules, docs.

  recall.py "how did we set up the staging deploy"      search (refreshes the index first)
  recall.py "..." -k 15 --project api --before 2026-09-01 --type msg,memory
  recall.py --index                                      refresh the index only
  recall.py --session <sid>                              print one distilled session in full

Keyword search (BM25) works out of the box with no dependency. Add meaning-based search by pointing
HINDSIGHT_EMBED_URL at any OpenAI-compatible /v1/embeddings endpoint (llama.cpp, Ollama, vLLM, OpenAI...) and
installing numpy; the two rankings are then fused (reciprocal rank fusion).

Environment:
  HINDSIGHT_EMBED_URL / HINDSIGHT_EMBED_MODEL / HINDSIGHT_EMBED_KEY   optional embeddings endpoint
  HINDSIGHT_DOC_DIRS    colon-separated directories whose README/CLAUDE.md/docs/*.md are indexed too
  HINDSIGHT_DATA     where state lives (default: ~/.local/share/hindsight)
  HINDSIGHT_QUERY_TIMEOUT   seconds to wait for the embeddings endpoint when searching (default 6)
"""
import argparse, collections, fcntl, glob, hashlib, json, math, os, re, subprocess, sys, tempfile, unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from paths import CLAUDE, CORPUS, DATA, HOME, private_dir, project_dirs  # noqa: E402
from signals import redact  # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None

EMBED_URL = os.environ.get("HINDSIGHT_EMBED_URL", "")
EMBED_MODEL = os.environ.get("HINDSIGHT_EMBED_MODEL", "")
EMBED_KEY = os.environ.get("HINDSIGHT_EMBED_KEY", "")
INDEX_DIR = os.path.join(DATA, "index")
MAX_CHARS = 3000
BATCH_CHARS = 60000
# Messages injected into the user turn that the user did not write (other agents, command output).
NOT_USER = re.compile(r"\s*<(agent-message|cross-session-message|local-command-std|task-notification)")
VERSION = f"{EMBED_MODEL}|{MAX_CHARS}|v1"
ENDPOINT_DOWN = False                       # set when indexing could not reach the endpoint: the query skips it too   # a different model or chunking re-embeds everything


def semantic_enabled():
    return bool(EMBED_URL and np is not None)


# ---------------------------------------------------------------- documents
def docs():
    """One document per user message (with Claude's reply), one per session, one per memory / rule / doc."""
    for f in sorted(glob.glob(os.path.join(CORPUS, "*", "*.json"))):
        try:
            s = json.load(open(f))
        except Exception:
            continue
        mach, sid = f.split("/")[-2], os.path.basename(f)[:-5]
        title = redact(s["title"]) if isinstance(s.get("title"), str) else ""
        proj = s["project"] if isinstance(s.get("project"), str) else ""
        name = f"{title} ({proj})" if title else proj
        ev, firsts, prev = s.get("events", []), [], []
        for i, e in enumerate(ev):
            if e[0] not in "UQ" or len(e[1].strip()) < 3 or NOT_USER.match(e[1]):
                continue
            ts = e[2] if len(e) > 2 and isinstance(e[2], str) else s.get("first")
            date = (ts if isinstance(ts, str) else "")[:10]
            cur = e[1][:300]
            if prev and prev[-1][1] == cur:      # queued (Q) then delivered (U): same text, one document
                continue
            ctx = [p for d, p in prev[-2:] if d == date]   # "do the same for the footer" needs what came before
            prev.append((date, cur))
            after = []
            for x in ev[i + 1:]:
                if x[0] in "UQ":
                    break
                if x[0] == "A":
                    after.append("Claude: " + x[1])
                elif x[0] == "R":
                    after.append("Rejected by user: " + x[1])
            body = "User: " + e[1] + "\n" + "\n".join(after)
            if ctx:
                body = "Just before: " + " / ".join(ctx) + "\n" + body
            firsts.append(e[1][:400])
            yield {"id": f"{mach}/{sid}#{i}", "kind": "msg", "machine": mach, "sid": sid, "i": i, "date": date,
                   "project": proj, "title": title, "text": redact(f"title: {name} | text: {body}")[:MAX_CHARS]}
        if firsts:
            body = "\n".join(firsts[:6])[:MAX_CHARS]
            yield {"id": f"{mach}/{sid}", "kind": "session", "machine": mach, "sid": sid, "i": -1,
                   "date": (s["first"] if isinstance(s.get("first"), str) else "")[:10], "project": proj, "title": title,
                   "text": redact(f"title: {name} | text: {body}")}
    seen = set()
    for root in project_dirs():
        for f in sorted(glob.glob(os.path.join(root, "*", "memory", "*.md"))):
            if os.path.basename(f) == "MEMORY.md":    # an index of links, the content is in the files
                continue
            try:
                txt = open(f, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            h = hashlib.sha1(txt.encode()).hexdigest()
            if h in seen:
                continue
            seen.add(h)
            proj = os.path.basename(os.path.dirname(os.path.dirname(f))).replace(HOME.replace("/", "-"), "~")
            m = re.search(r"^name:\s*(.+)$", txt, re.M)
            name = m.group(1).strip() if m else os.path.basename(f)[:-3]
            yield {"id": "mem:" + f.replace(HOME, "~"), "kind": "memory", "machine": "", "sid": "", "i": -1,
                   "date": "", "project": proj, "title": name,
                   "text": redact(f"title: memory {name} ({proj}) | text: {txt}")[:MAX_CHARS]}
    yield from md_docs()


def sections(path, size=2500):
    """Split a markdown file by headings, 2500 characters at most, keeping the start line."""
    try:
        lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        return
    head, buf, start = "", [], 1
    for n, l in enumerate(lines + ["# "], 1):
        new = re.match(r"#{1,4} ", l) or sum(map(len, buf)) > size
        if new and "".join(buf).strip():
            yield start, head, "\n".join(buf)
            buf, start = [], n
        if re.match(r"#{1,4} ", l):
            head = l.lstrip("# ").strip()
        buf.append(l)


def doc_files():
    files = [(os.path.join(CLAUDE, "CLAUDE.md"), "rule")]
    files += [(f, "rule") for f in sorted(glob.glob(os.path.join(CLAUDE, "skills", "*", "SKILL.md")))]
    for base in [d for d in os.environ.get("HINDSIGHT_DOC_DIRS", "").split(":") if d]:
        base = os.path.expanduser(base)
        for dirpath, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "vendor", "dist", "build", ".venv")]
            if dirpath[len(base):].count(os.sep) > 4:
                dirs[:] = []
            for n in names:
                p = os.path.join(dirpath, n)
                if n in ("CLAUDE.md", "AGENTS.md", "SKILL.md"):
                    files.append((p, "rule"))
                elif n.endswith(".md") and (n == "README.md" or os.sep + "docs" + os.sep in p):
                    files.append((p, "doc"))
    return files


def md_docs():
    for f, kind in doc_files():
        if not os.path.isfile(f):
            continue
        rel = f.replace(HOME, "~")
        for line, head, body in sections(f):
            yield {"id": f"{kind}:{rel}:{line}", "kind": kind, "machine": "", "sid": "", "i": -1, "date": "",
                   "project": os.path.basename(os.path.dirname(f)), "title": head, "path": f"{rel}:{line}",
                   "text": redact(f"title: {rel} > {head} | text: {body}")[:MAX_CHARS]}


# ---------------------------------------------------------------- embeddings
def embed(texts, timeout=300):
    texts = [t.split(" | text: ", 1)[-1] for t in texts]
    headers = {"Content-Type": "application/json"}
    if EMBED_KEY:
        headers["Authorization"] = "Bearer " + EMBED_KEY
    body = {"input": texts}
    if EMBED_MODEL:
        body["model"] = EMBED_MODEL
    req = urllib.request.Request(EMBED_URL, json.dumps(body).encode(), headers)
    d = None
    try:
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
        v = np.array([x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])], dtype=np.float32)
        if v.ndim != 2 or len(v) != len(texts):
            raise ValueError("unexpected number of vectors")
    except Exception as e:
        detail = d["error"] if isinstance(d, dict) and d.get("error") else e
        raise RuntimeError(f"embeddings endpoint failed ({EMBED_URL}): {detail}")
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)


def load():
    """(meta, vectors). Vectors may be None (keyword-only index)."""
    try:
        meta = json.load(open(os.path.join(INDEX_DIR, "meta.json")))
    except Exception:
        return [], None
    vec = None
    if np is not None and os.path.exists(os.path.join(INDEX_DIR, "vectors.npy")):
        try:
            vec = np.load(os.path.join(INDEX_DIR, "vectors.npy"))
            if len(vec) != len(meta):
                vec = None
        except Exception:
            vec = None
    return meta, vec


def refresh_corpus():
    mine = os.path.join(os.path.dirname(os.path.realpath(__file__)), "mine.py")
    try:
        subprocess.run([sys.executable, mine, "mine"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except Exception:
        pass


def _atomic(path, write):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp.")
    with os.fdopen(fd, "wb") as f:
        write(f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def update(quiet=False, nowait=False, force=False):
    """Incremental: only new or changed documents go through the model. If the endpoint dies midway, what is done
    is kept and the rest has a zero vector (keyword-findable) and is retried on the next search."""
    private_dir(INDEX_DIR)
    with open(os.path.join(DATA, ".index.lock"), "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | (fcntl.LOCK_NB if nowait else 0))
        except BlockingIOError:
            return load()               # another indexer is running: it will do the work
        meta, vec = load()
        if force:
            vec = None
        sem = semantic_enabled()
        old = {m["id"]: (m["h"], k) for k, m in enumerate(meta)}
        new_meta, rows, todo = [], [], []
        for d in docs():
            d["h"] = hashlib.sha1((VERSION + d["text"]).encode()).hexdigest()[:16]
            prev = old.get(d["id"])
            if prev and prev[0] == d["h"] and (vec is not None or not sem):
                rows.append(vec[prev[1]] if vec is not None and sem else None)
            else:
                rows.append(None)
                if sem:
                    todo.append(len(new_meta))
            new_meta.append(d)
        if not todo and [m["id"] for m in meta] == [d["id"] for d in new_meta] and (vec is not None) == sem:
            if sem and vec is not None and len(vec) and not force:
                # nothing changed in the texts, but the model behind the endpoint may have: compare dimensions
                try:
                    probe = embed([new_meta[0]["text"]], timeout=6)
                except RuntimeError:
                    probe = None
                if probe is not None and probe.shape[1] != vec.shape[1]:
                    lk.close()
                    return update(quiet, nowait, force=True)
            return meta, vec
        done, err, batch, size = 0, None, [], 0
        if todo:
            # a quick probe first: an endpoint that accepts connections but never answers must not stall indexing
            try:
                embed([new_meta[todo[0]]["text"]], timeout=float(os.environ.get("HINDSIGHT_QUERY_TIMEOUT", "6")))
            except RuntimeError as e:
                err = e
        for k in todo + [None]:
            if k is not None and (size + len(new_meta[k]["text"]) < BATCH_CHARS or not batch):
                batch.append(k)
                size += len(new_meta[k]["text"])
                continue
            if batch and not err:
                try:
                    for j, v in zip(batch, embed([new_meta[j]["text"] for j in batch])):
                        rows[j] = v.astype(np.float16)
                    done += len(batch)
                except RuntimeError as e:
                    err = e
            if k is not None:
                batch, size = [k], len(new_meta[k]["text"])
        new_dim = next((rows[k].shape[0] for k in todo if rows[k] is not None), None)
        if sem and vec is not None and new_dim and vec.shape[1] != new_dim and not force:
            # the model behind the endpoint changed (same URL, same or unset model name): start over
            lk.close()
            return update(quiet, nowait, force=True)
        vec = None
        if sem:
            dim = next((r.shape[0] for r in rows if r is not None), None)
            if dim:
                for j, r in enumerate(rows):
                    if r is None:
                        rows[j] = np.zeros(dim, dtype=np.float16)
                        new_meta[j]["h"] = ""        # retried next time
                vec = np.stack(rows)
        _atomic(os.path.join(INDEX_DIR, "meta.json"), lambda f: f.write(json.dumps(new_meta, ensure_ascii=False).encode()))
        vp = os.path.join(INDEX_DIR, "vectors.npy")
        if vec is not None:
            _atomic(vp, lambda f: np.save(f, vec))
        elif os.path.exists(vp):
            os.unlink(vp)                            # stale vectors from a previous configuration
    if err:
        global ENDPOINT_DOWN
        ENDPOINT_DOWN = True
        print(f"recall: {err}\n  {len(todo) - done} document(s) without a vector (keyword search only), retried next time",
              file=sys.stderr)
    elif not quiet:
        print(f"recall: {done} document(s) embedded, {len(new_meta)} indexed", file=sys.stderr)
    return new_meta, vec


# ---------------------------------------------------------------- search
STOP = set("the and for are but not you all can had her was one our out has have this that with from they been were "
           "what when will your into than then them these those would could should about there their which while "
           "les des une pour que qui dans sur avec pas est ont son ses aux par mais comme tout fait cette ces".split())


def toks(s):
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return [w for w in re.findall(r"[a-z0-9$]{3,}", s) if w not in STOP]


class BM25:
    """Ranked keywords (about grep, sorted by relevance): safe when the query contains the exact word."""
    def __init__(self, texts, k1=1.2, b=0.75):
        self.d = [collections.Counter(toks(t)) for t in texts]
        self.l = [sum(c.values()) for c in self.d]
        self.avg = (sum(self.l) / len(self.l)) if self.l else 1
        self.post = collections.defaultdict(list)
        for j, c in enumerate(self.d):
            for w, f in c.items():
                self.post[w].append((j, f))
        n = len(texts)
        self.idf = {w: math.log(1 + (n - len(p) + .5) / (len(p) + .5)) for w, p in self.post.items()}
        self.k1, self.b = k1, b

    def score(self, q):
        out = [0.0] * len(self.d)
        for w in set(toks(q)):
            for j, f in self.post.get(w, ()):
                out[j] += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.l[j] / self.avg))
        return out


def ranks(scores, keep):
    order = sorted((j for j in range(len(scores)) if keep[j]), key=lambda j: -scores[j])
    r = {j: n for n, j in enumerate(order)}
    return r


def search(query, meta, vec, k=10, project=None, before=None, mode="auto", types=None, exclude=None):
    keep = []
    for m in meta:
        ok = True
        if project and project.lower() not in (m["project"] + " " + m["title"]).lower():
            ok = False
        elif before and m["date"] and m["date"] >= before:
            ok = False
        elif types and m["kind"] not in types:
            ok = False
        elif exclude and m["sid"] == exclude:
            ok = False
        keep.append(ok)
    if mode == "auto":
        mode = "hybrid" if vec is not None and semantic_enabled() else "keyword"
    sem = None
    if mode in ("hybrid", "semantic"):
        if ENDPOINT_DOWN:
            mode = "keyword"
        elif vec is None or not semantic_enabled():
            print("recall: semantic search is not configured (HINDSIGHT_EMBED_URL + numpy); using keywords", file=sys.stderr)
            mode = "keyword"
        else:
            try:
                q = embed([redact(query)], timeout=float(os.environ.get("HINDSIGHT_QUERY_TIMEOUT", "6")))[0]
                sem = (vec.astype(np.float32) @ q).tolist()
            except (RuntimeError, ValueError) as e:
                print(f"recall: {e}\n  falling back to keywords", file=sys.stderr)
                mode = "keyword"
    idx = [j for j, ok in enumerate(keep) if ok]
    lex = [0.0] * len(meta)
    if mode != "semantic" and idx:
        for j, s in zip(idx, BM25([meta[j]["text"] for j in idx]).score(query)):
            lex[j] = s
    if mode == "semantic":
        score = sem
    elif mode == "keyword":
        score = lex
    else:
        rs, rl = ranks(sem, keep), ranks(lex, keep)
        score = [(1 / (60 + rs[j]) if j in rs else 0) + (1 / (60 + rl[j]) if lex[j] > 0 and j in rl else 0)
                 for j in range(len(meta))]
    out, per = [], {}
    for j in sorted(idx, key=lambda j: -score[j]):
        if len(out) >= k or (score[j] <= 0 and mode == "keyword"):
            break
        m = meta[j]
        key = m["sid"] or m["id"]
        if m["kind"] == "session":           # the session card only stands in when none of its messages matched
            if per.get(key, 0) or any(o[0]["sid"] == key for o in out):
                continue
            out.append((m, sem[j] if sem is not None else None))
            continue
        if per.get(key, 0) >= 2:             # at most two excerpts per session: more different sessions
            continue
        out = [o for o in out if not (o[0]["kind"] == "session" and o[0]["sid"] == key)]
        per[key] = per.get(key, 0) + 1
        out.append((m, sem[j] if sem is not None else None))
    return out


def show(hits):
    if not hits:
        print("recall: no result")
    for n, (m, cos) in enumerate(hits, 1):
        txt = m["text"].split(" | text: ", 1)[-1]
        where = f"{m['machine']}/{m['sid'][:8]} #{m['i']}" if m["sid"] else m.get("path") or m["id"]
        sim = f" sim {cos:.2f}" if cos is not None else ""
        print(f"{n}.{sim} {m['date']} {m['project']} · {m['title']} ({m['kind']}, {where})")
        print("   " + re.sub(r"\s+", " ", txt)[:400] + "\n")


def session(sid):
    f = [p for p in glob.glob(os.path.join(CORPUS, "*", "*.json")) if os.path.basename(p).startswith(sid)]
    if not f:
        sys.exit(f"recall: session {sid} is not in the corpus")
    s = json.load(open(f[0]))
    print(f"{s['title']} - {s['project']} - {s['first']} -> {s['last']} ({f[0]})")
    raw = []
    for root in project_dirs():
        raw += glob.glob(os.path.join(root, "*", os.path.basename(f[0])[:-5] + ".jsonl"))
    if raw:
        print(f"full transcript: {raw[0]}")
    for i, e in enumerate(s["events"]):
        print(f"#{i} {e[0]} {e[2][:16] if len(e) > 2 else ''}  {e[1]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--project", help="substring of the project path or session title")
    ap.add_argument("--before", help="YYYY-MM-DD: only what precedes this date")
    ap.add_argument("--mode", choices=["auto", "hybrid", "semantic", "keyword"], default="auto")
    ap.add_argument("--type", help="comma-separated: msg,session,memory,doc,rule")
    ap.add_argument("--exclude", help="session id to ignore (the current one, for the hook)")
    ap.add_argument("--no-update", action="store_true", help="search the index as it is (the hook: sub-second)")
    ap.add_argument("--index", action="store_true", help="refresh the index and exit")
    ap.add_argument("--nowait", action="store_true", help="with --index: do nothing if another indexer is running")
    ap.add_argument("--session")
    a = ap.parse_args()
    if a.session:
        return session(a.session)
    if a.no_update:
        meta, vec = load()
    else:
        refresh_corpus()
        meta, vec = update(quiet=not a.index, nowait=a.nowait)
    if a.query:
        show(search(a.query, meta, vec, a.k, a.project, a.before, a.mode, a.type.split(",") if a.type else None,
                    a.exclude))


if __name__ == "__main__":
    main()
