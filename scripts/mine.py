#!/usr/bin/env python3
"""Distill Claude Code transcripts into a searchable corpus and a digest of your corrections.

  mine.py mine     distill every main session into corpus/<machine>/<sid>.json (incremental). The corpus is
                   kept after Claude Code deletes old transcripts (cleanupPeriodDays), the transcripts are not.
  mine.py digest   write the material for /hindsight:learn: corrections since the last digest, with what
                   Claude had just said, plus project feedback memories written since, plus the weekly trend
  mine.py collect  mine + digest (what the learn skill runs)
  mine.py done     mark everything up to now as digested
  mine.py stats    share of your messages that correct Claude, per week (is it working?)
  mine.py pending  "<corrections> <feedback memories>" waiting since the last digest

Data: see paths.py. Secrets are redacted before anything is written.
"""
import collections, datetime as dt, glob, hashlib, json, os, re, socket, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from paths import CORPUS, DATA, HOME, private_dir, project_dirs  # noqa: E402
from signals import redact, score  # noqa: E402

STATE = os.path.join(DATA, "state.json")        # transcripts already distilled (by size)
MARK = os.path.join(DATA, "last_digest")        # when /learn last ran; kept apart so mining never overwrites it
STARTED = os.path.join(DATA, ".digest_started")  # when the current digest was made: `done` marks that, not "now"
SYS = ("<task-notification", "<system-reminder", "<local-command-stdout", "<local-command-caveat", "Caveat:",
       "<bash-stdout", "<bash-stderr", "[Image", "Base directory for this skill")
REJECT = re.compile(r"the user said:\s*(.*)", re.S)


def machine():
    return socket.gethostname().split(".")[0].lower()


def load_state():
    try:
        files = json.load(open(STATE)).get("files", {})
    except Exception:
        files = {}
    try:
        last = open(MARK).read().strip() or None
    except OSError:
        last = None
    return {"files": files, "last_digest": last}


def save_state(st):
    private_dir(DATA)
    tmp = f"{STATE}.{os.getpid()}.tmp"
    json.dump({"files": st["files"]}, open(tmp, "w"), indent=1)
    os.replace(tmp, STATE)


def lock(wait):
    """Several sessions start at once: one miner at a time; the background one gives up if another runs."""
    import fcntl
    private_dir(DATA)
    fd = open(os.path.join(DATA, ".lock"), "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
    except BlockingIOError:
        sys.exit(0)
    return fd


def roots():
    """(machine label, projects dir) for this machine and every extra directory."""
    out = []
    for i, d in enumerate(project_dirs()):
        if not os.path.isdir(d):
            continue
        name = machine()
        if i:  # ".../laptop/.claude/projects" -> "laptop" (a hidden label would be skipped by glob)
            up = os.path.dirname(d.rstrip("/"))
            name = (os.path.basename(up) if not os.path.basename(up).startswith(".") else os.path.basename(os.path.dirname(up))).lstrip(".") or f"extra{i}"
        out.append((name, d))
    return out


def _text(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(x.get("text", "") if x.get("type") == "text" else "[image]"
                     for x in content or [] if isinstance(x, dict) and x.get("type") in ("text", "image"))


def distill(path):
    """Ordered events of one session: A (Claude's last words), T (tools), U/Q (user), R (rejection), X (interrupt)."""
    ev, last, tools, meta = [], "", collections.Counter(), {"first": None, "last": None, "title": "", "cwd": ""}

    def flush():
        if last:
            ev.append(("A", redact(last.strip())[-600:]))
        if tools:
            ev.append(("T", ", ".join(f"{k}x{v}" for k, v in tools.most_common(8))))

    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        t, ts = d.get("type"), d.get("timestamp")
        if not isinstance(ts, str):          # everything downstream compares and slices timestamps as text
            ts = None
        if not isinstance(d.get("message"), dict):
            d["message"] = {}
        if ts:
            meta["first"] = meta["first"] or ts
            meta["last"] = ts
        if t == "ai-title" and not meta["title"]:
            title = d.get("title") or d.get("aiTitle") or ""
            meta["title"] = redact(title)[:200] if isinstance(title, str) else ""
        if isinstance(d.get("cwd"), str) and d["cwd"] and not meta["cwd"]:
            meta["cwd"] = d["cwd"]
        if t == "user" and str(d.get("entrypoint", "")).startswith("sdk"):
            meta["sdk"] = True
        if d.get("isSidechain"):
            continue
        if t == "assistant":
            for x in d["message"].get("content") if isinstance(d["message"].get("content"), list) else []:
                if not isinstance(x, dict):
                    continue
                if x.get("type") == "text" and x.get("text", "").strip():
                    last = x["text"]
                elif x.get("type") == "tool_use":
                    n = x.get("name", "?")
                    if n == "Bash":
                        c = ((x.get("input") or {}).get("command") or "").split()
                        n = "Bash:" + (c[0] if c and re.fullmatch(r"[\w./-]{1,30}", c[0]) else "...")
                    tools[n] += 1
        elif t == "user":
            c = d["message"].get("content")
            if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
                for x in c:
                    if not isinstance(x, dict) or x.get("type") != "tool_result":
                        continue
                    body = x.get("content")
                    body = body if isinstance(body, str) else _text(body) if body else ""
                    if "doesn't want to proceed" in body or "tool use was rejected" in body:
                        m = REJECT.search(body)
                        flush(); last = ""; tools.clear()
                        ev.append(("R", redact((m.group(1) if m else "(rejected, no reason given)").strip())[:1500], ts))
                continue
            if d.get("isMeta") or d.get("isCompactSummary"):
                continue
            txt = _text(c).strip()
            if not txt:
                continue
            if "[Request interrupted by user" in txt:
                ev.append(("X", "interrupted", ts))
                continue
            if txt.startswith(SYS) and "<command-name>" not in txt:
                continue
            m = re.search(r"<command-name>(.*?)</command-name>", txt, re.S)
            if m:
                a = re.search(r"<command-args>(.*?)</command-args>", txt, re.S)
                txt = f"{m.group(1).strip()} {a.group(1).strip() if a else ''}".strip()
            flush(); last = ""; tools.clear()
            ev.append(("U", redact(txt)[:2500], ts))
        elif t == "attachment" and (d.get("attachment") or {}).get("type") == "queued_command":
            p = d["attachment"].get("prompt")
            p = p if isinstance(p, str) else _text(p)
            if p and not p.lstrip().startswith(SYS):
                ev.append(("Q", redact(p)[:1500], ts))
    return ev, meta


def cmd_mine(quiet=False):
    st, n, since_save = load_state(), 0, 0
    try:
        for mach, root in roots():
            for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
                try:
                    size = os.path.getsize(f)
                    if st["files"].get(f) == size:
                        continue
                    ev, meta = distill(f)
                    st["files"][f] = size
                    if not any(e[0] in "UQR" for e in ev) or meta.get("sdk"):
                        continue
                    proj = (meta["cwd"] or os.path.basename(os.path.dirname(f))).replace(HOME, "~")
                    out = os.path.join(CORPUS, mach, os.path.basename(f)[:-6] + ".json")
                    private_dir(os.path.dirname(out))
                    tmp = f"{out}.{os.getpid()}.tmp"      # atomic: recall may kill the miner mid-write
                    with open(tmp, "w") as w:
                        json.dump({"machine": mach, "project": proj, "title": meta["title"], "first": meta["first"],
                                   "last": meta["last"], "events": ev}, w, ensure_ascii=False)
                    os.replace(tmp, out)
                    n += 1
                except Exception:       # one odd transcript must not stop the others
                    st["files"].pop(f, None)
                    continue
                since_save += 1
                if since_save >= 50:
                    save_state(st)
                    since_save = 0
    finally:
        save_state(st)
    if not quiet:
        print(f"{n} session(s) (re)distilled")


def corrections(since=None):
    """Yield (session, event, hits, claude_context) for every correction-looking event after `since`."""
    for f in glob.glob(os.path.join(CORPUS, "*", "*.json")):
        s = json.load(open(f))
        ev = s["events"]
        for i, e in enumerate(ev):
            if e[0] not in "UQRX" or (since and len(e) > 2 and e[2] and e[2] < since):
                continue
            sc, hits = score(e[1]) if e[0] in "UQ" else (3, [e[0]])
            if e[0] == "X":  # an interrupt only matters with the message that follows it
                nxt = next((x for x in ev[i + 1:] if x[0] in "UQ"), None)
                if not nxt:
                    continue
                e = ("X", f"[interrupted] {nxt[1]}", e[2] if len(e) > 2 else None)
            if sc < 2:
                continue
            ctx = next((x[1] for x in reversed(ev[:i]) if x[0] == "A"), "")
            yield s, e, hits, ctx


def memories_changed(since):
    """Project memories (feedback first) written since the last digest. A memory is dated by the first time its
    content was seen, so a synced copy with a fresh mtime is not listed twice."""
    seen_p = os.path.join(DATA, "memories-seen.json")
    try:
        seen = json.load(open(seen_p))
    except (OSError, ValueError):
        seen = {}
    out, listed = [], set()
    for mach, root in roots():
        for f in glob.glob(os.path.join(root, "*", "memory", "*.md")):
            if f.endswith("MEMORY.md"):
                continue
            body = open(f, errors="replace").read()
            h = hashlib.sha1(body.encode()).hexdigest()
            first = seen.setdefault(h, dt.datetime.fromtimestamp(os.path.getmtime(f), dt.timezone.utc).isoformat())
            if h in listed or (since and first < since):
                continue
            listed.add(h)
            kind = "feedback" if re.search(r"type:\s*feedback", body) else "other"
            out.append((kind, mach, os.path.basename(os.path.dirname(os.path.dirname(f))), f, body))
    private_dir(DATA)
    with open(seen_p + ".tmp", "w") as w:
        json.dump(seen, w)
    os.replace(seen_p + ".tmp", seen_p)
    return sorted(out, key=lambda x: x[0] != "feedback")


def weekly():
    """Per ISO week: (user messages, corrections). The ratio is the number to watch, not the count."""
    msgs, corr = collections.Counter(), collections.Counter()
    wk = lambda ts: (lambda d: (d - dt.timedelta(days=d.weekday())).isoformat())(dt.date.fromisoformat(ts[:10]))
    for f in glob.glob(os.path.join(CORPUS, "*", "*.json")):
        for e in json.load(open(f))["events"]:
            if e[0] in "UQ" and len(e) > 2 and e[2]:
                msgs[wk(e[2])] += 1
    for s, e, *_ in corrections():
        if e[0] in "UQ" and len(e) > 2 and e[2]:
            corr[wk(e[2])] += 1
    return [(w, msgs[w], corr[w]) for w in sorted(msgs)]


def cmd_digest():
    st = load_state()
    since = st.get("last_digest")
    private_dir(os.path.join(DATA, "digests"))
    open(STARTED, "w").write(dt.datetime.now(dt.timezone.utc).isoformat())
    path = os.path.join(DATA, "digests", dt.date.today().isoformat() + ".md")
    by_proj = collections.defaultdict(list)
    for s, e, hits, ctx in corrections(since):
        by_proj[s["project"]].append((s, e, hits, ctx))
    mems = memories_changed(since)
    with open(path, "w") as o:
        o.write(f"# Learning digest, since {since or 'the beginning'}\n\n")
        o.write("Share of messages that correct Claude, per week: "
                + " · ".join(f"{w[5:]} {100 * c // max(m, 1)}%" for w, m, c in weekly()[-10:]) + "\n\n")
        o.write(f"## 1. Detected corrections ({sum(map(len, by_proj.values()))})\n\n"
                "Broad regex filter: expect noise. `A` is what Claude had just said. `R` is a tool call you "
                "rejected, `X` an interruption.\n")
        for proj, items in sorted(by_proj.items(), key=lambda kv: -len(kv[1])):
            o.write(f"\n### {proj} ({len(items)})\n")
            for s, e, hits, ctx in sorted(items, key=lambda x: x[1][2] or ""):
                when = (e[2] or "")[:16].replace("T", " ")
                o.write(f"\n- **{e[0]}** {when} · {s['machine']} · \"{s['title'][:50]}\" · {', '.join(hits[:3])}\n")
                if ctx:
                    o.write(f"  - A: {ctx[-350:].replace(chr(10), ' ')}\n")
                o.write(f"  - {e[0]}: {e[1][:900].replace(chr(10), ' ')}\n")
        o.write(f"\n## 2. Project memories written since ({len(mems)})\n\n"
                "A `feedback` lesson that does not depend on its project moves up (skill, global CLAUDE.md or hook), "
                "then the project copy is removed.\n")
        for kind, mach, proj, f, body in mems:
            o.write(f"\n### [{kind}] {mach} · {proj} · {os.path.basename(f)}\n`{f.replace(HOME, '~')}`\n\n{redact(body.strip())[:1800]}\n")
        sig = os.path.join(DATA, "signals.jsonl")
        if os.path.exists(sig):
            o.write("\n## 3. Live signals (hook) not yet digested\n\n")
            for l in open(sig):
                try:
                    j = json.loads(l)
                except Exception:
                    continue
                if not since or j["ts"] >= since:
                    o.write(f"- {j['ts'][:16]} · {j['cwd'].replace(HOME, '~')} : {j['prompt'][:300]}\n")
    print(path)


def cmd_collect():
    cmd_mine()
    cmd_digest()


def cmd_pending():
    since = load_state().get("last_digest")
    n = sum(1 for _ in corrections(since))
    m = sum(1 for k, *_ in memories_changed(since) if k == "feedback")
    print(n, m)


def cmd_done():
    try:    # what the digest covered, so corrections made while you were reading it are not lost
        now = open(STARTED).read().strip() or dt.datetime.now(dt.timezone.utc).isoformat()
    except OSError:
        now = dt.datetime.now(dt.timezone.utc).isoformat()
    private_dir(DATA)
    open(MARK + ".tmp", "w").write(now)
    os.replace(MARK + ".tmp", MARK)
    print("digested up to", now[:16])


def cmd_stats():
    for w, m, c in weekly():
        r = 100 * c // max(m, 1)
        print(f"{w}  {r:>3}%  {'#' * (r // 2):<25} {c}/{m}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    cmds = {"mine": cmd_mine, "digest": cmd_digest, "done": cmd_done, "stats": cmd_stats,
            "collect": cmd_collect, "pending": cmd_pending}
    if cmd not in cmds:
        sys.exit(__doc__)
    if cmd in ("mine", "collect"):
        _lock = lock(wait=cmd != "mine")
    cmds[cmd]()
