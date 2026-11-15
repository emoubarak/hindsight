#!/usr/bin/env python3
"""Keep your skills current: which ones to check now against what changed outside, and whether copied skills moved
upstream.

  freshness.py due [--max N] [all | skill...]  skills used since their last check whose interval has passed, with
                                               their card. `all`: drop the usage filter. Skill names: those skills,
                                               with neither the usage nor the interval filter.
  freshness.py short                           the same in one line
  freshness.py upstream [all | skill...]       copied skills whose source repository moved since the copy (needs `gh`)
  freshness.py checked <skill>...              record in the cards that the check was done today
  freshness.py init                            write the cards file with its format and one line per installed skill

"Used" means: loaded through the Skill tool, typed as /<skill>, or one of its scripts run from Bash
(~/.claude/skills/<name>/...), in a session of the last 90 days, after the card's `checked:` date (the last 30 days
for a card never checked). A skill stays due until `checked` is recorded: neither a skipped pass nor --max forgets it.

Cards: $HINDSIGHT_FRESHNESS, default <data dir>/freshness.md (see paths.py). They are yours: plugin updates never
touch them; `checked` only rewrites the `checked:` line of a card. Skills used only inside sub-agents are not counted
(sub-agent transcripts are not read).
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from paths import CLAUDE, DATA, private_dir, project_dirs  # noqa: E402

CARDS = os.environ.get("HINDSIGHT_FRESHNESS") or os.path.join(DATA, "freshness.md")
CACHE = os.path.join(DATA, "freshness-usage.json")
SKILLS = os.path.join(CLAUDE, "skills")
INTERVAL, MAX, WINDOW, FRESH = 21, 8, 90, 30
HEAD = re.compile(r"##\s+(.+?)\s*$")
KEY = re.compile(r"([a-z][a-z ]{0,14}?)\s*:\s*(.*?)\s*$", re.I)
KEYS = {"what", "where", "files", "every", "checked", "upstream", "none", "watch"}
ISO = re.compile(r"\d{4}-\d{2}-\d{2}$")
CMD = re.compile(r"<command-name>/([\w:.-]+)</command-name>")
# A skill's script counts only in command position: at the start of a line or after ; & | `$(` `(`, past variable
# assignments and launchers (timeout, env, nohup, python3, bash, node, uv run...). `cat`, `sed`, `grep` of a skill's
# file, a path quoted in a heredoc or a commit message are not uses.
LAUNCH = (r"(?:/\S*/)?(?:timeout\s+\S+|nohup|exec|time|env|xargs(?:\s+-\S+)*|python3?(?:\s+-[a-zA-Z]+)*|bash|sh|zsh|node|deno"
          r"|uvx|uv\s+run(?:\s+--?[\w-]+(?:=\S+|\s+(?!\S*skills/)[^\s-]\S*)?)*)")
LEAD = r"(?:^|[;&|]|\$?\()\s*(?:\w+=\S*\s+)*(?:" + LAUNCH + r"\s+)*"
_DIRS = sorted({".claude/skills", os.path.join(CLAUDE, "skills").replace(os.path.expanduser("~"), "~"),
                os.path.join(CLAUDE, "skills"), "$CLAUDE_CONFIG_DIR/skills", "${CLAUDE_CONFIG_DIR}/skills"}, key=len)
SCRIPT = re.compile(LEAD + r"[\"']?\S*?(?:" + "|".join(re.escape(d) for d in reversed(_DIRS))
                    + r")/(\w[\w.-]*)/\S+", re.M)
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n\s*\2\s*(?=\n|$)", re.S)
SHELL_C = re.compile(r"\b(?:bash|sh)\s+-c\s+(?:\"((?:[^\"\\]|\\.)*)\"|'([^']*)')")
TEXT_ARG = re.compile(r"\s-(?:c|m|e|-message)\s+(?:\"(?:[^\"\\]|\\.)*\"|'[^']*')")
DETECTION = 3   # bump when the detection changes: cached results are recomputed

TEMPLATE = """# Skill freshness cards

Read by `freshness.py` (due, upstream, checked) and by `/hindsight:refresh`. One section per skill, headed by its
name; several names separated by commas share one card.

- `what:` what can go stale in the skill (model names, prices, a platform's rules, versions, URLs).
- `where:` sources to open: changelogs, docs, `llms.txt` indexes, subreddits, accounts on X. Each check removes the
  ones that gave nothing and adds the ones that helped.
- `files:` what the check reads in the skill before searching.
- `every:` days between two checks (21 by default). `checked:` date of the last one (YYYY-MM-DD), written by
  `freshness.py checked <skill>`, for the whole card.
- `upstream: owner/repo [path] @commit-or-copy-date`: a copied skill; `{skill}` stands for the skill's name. Compared
  with `gh api`.
- `none: reason`: nothing to watch (an internal convention, a method with no outside facts).
- `watch:` then lines `- date | finding | link`: seen but not mature yet, re-checked next time.
- Any other line is free text, passed to the check as is. A misspelled key is reported by `freshness.py due`.

Examples (a card starts with `## <skill name>`):

    ## deploy
    what: hosting provider's limits and prices, CLI flags of the deploy tool
    where: the provider's changelog, the CLI's release notes, r/devops
    files: SKILL.md
    every: 30

    ## design-guide
    upstream: owner/repo skills/{skill} @abc1234
"""


def _date(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def cards():
    """({skill: card}, [problems]). A heading may carry several names (`## a, b`): they share the card."""
    out, cur, problems = {}, None, []
    if not os.path.exists(CARDS):
        return out, [f"no cards file at {CARDS}: run `freshness.py init`"]
    try:
        with open(CARDS, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as ex:
        return out, [f"cannot read {CARDS}: {ex}"]
    for i, line in enumerate(lines):
        m = HEAD.match(line)
        if m:
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            cur = {"names": names, "line": i, "text": [], "upstream": [], "none": None, "every": INTERVAL,
                   "checked": None, "web": False}
            for n in names:
                if n in out:
                    problems.append(f"line {i + 1}: `{n}` already has a card")
                out[n] = cur
            continue
        if cur is None:
            continue
        cur["text"].append(line)
        m = KEY.match(line)
        if not m or m.group(2).startswith("//"):  # a bare URL is free text
            continue
        k, v = m.group(1).strip().lower(), m.group(2)
        if k not in KEYS:
            if line[:1].islower() and " " not in m.group(1).strip():  # "word: ..." unknown, not a sentence
                problems.append(f"line {i + 1} ({cur['names'][0]}): unknown key `{m.group(1)}`")
            continue
        if k == "upstream":
            cur["upstream"].append(v)
        elif k == "every":
            n = re.sub(r"\D", "", v)
            cur["every"] = int(n) if n else INTERVAL
            if not n:
                problems.append(f"line {i + 1} ({cur['names'][0]}): unreadable interval `{v}`")
        elif k == "checked":
            if ISO.match(v) and _date(v):
                cur["checked"] = v
            else:
                problems.append(f"line {i + 1} ({cur['names'][0]}): unreadable date `{v}` (expected YYYY-MM-DD)")
        elif k == "none":
            cur["none"] = v or "no reason given"
        elif k in ("what", "where") and v:
            cur["web"] = True
    for card in {id(c): c for c in out.values()}.values():
        if not (card["web"] or card["upstream"] or card["none"]):
            problems.append(f"line {card['line'] + 1} ({card['names'][0]}): empty card, fill `what`/`where` or "
                            f"write `none: reason`")
    return out, problems


def installed():
    """{name: where}: user skills, then plugin skills (as `plugin:name`)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(SKILLS, "*", "SKILL.md"))):
        out[os.path.basename(os.path.dirname(f))] = os.path.dirname(f)
    for f in sorted(glob.glob(os.path.join(CLAUDE, "plugins", "cache", "*", "*", "*", "skills", "*", "SKILL.md"))):
        parts = f.split(os.sep)
        out[f"{parts[-5]}:{parts[-2]}"] = os.path.dirname(f)  # cache/<marketplace>/<plugin>/<version>: last version wins
    return out


def _executed(cmd):
    """Skills whose script this Bash command runs. Reading or editing a skill's file is not using it."""
    cmd = HEREDOC.sub(lambda m: "<<" + m.group(2) + m.group(3), cmd)                # a heredoc body is text
    cmd = SHELL_C.sub(lambda m: "; " + (m.group(1) or m.group(2) or "") + " ;", cmd)  # bash -c "...": commands
    cmd = TEXT_ARG.sub(" ", cmd)                                                    # python -c, git commit -m: text
    return set(SCRIPT.findall(cmd))


def _hits(path, known):
    """{skill: last day used} in one transcript; {} for an SDK / `claude -p` session."""
    last = {}

    def add(name, ts):
        if ts and ts[:10] > last.get(name, ""):
            last[name] = ts[:10]

    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return {}
    with f:
        for line in f:
            if '"entrypoint"' in line and re.search(r'"entrypoint"\s*:\s*"sdk', line):
                return {}
            if '"Skill"' not in line and "<command-name>/" not in line and ".claude/skills/" not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("isSidechain"):
                continue
            ts = e.get("timestamp") or ""
            content = (e.get("message") or {}).get("content") or e.get("content")
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict) or c.get("type") != "tool_use":
                        continue
                    inp = c.get("input") or {}
                    if c.get("name") == "Skill" and inp.get("skill"):
                        add(inp["skill"], ts)
                    elif c.get("name") == "Bash":
                        for s in _executed(inp.get("command") or ""):
                            if s in known:  # a directory under skills/ that is not an installed skill is not one
                                add(s, ts)
            if e.get("type") in ("user", "system"):
                text = content if isinstance(content, str) else " ".join(
                    c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text")
                for name in CMD.findall(text):
                    if name in known or name.split(":")[-1] in known:  # a built-in command is not a skill
                        add(name, ts)
    return last


def usage():
    """{skill: [last day used, one per session]} over WINDOW days. Transcripts are cached by (path, size)."""
    known = set(installed())
    known |= {k.split(":")[-1] for k in known}
    stamp = [DETECTION, sorted(known)]  # new detection or a newly installed skill: recompute everything
    try:
        with open(CACHE) as f:
            saved = json.load(f)
        cache = saved["files"] if saved.get("stamp") == stamp and isinstance(saved.get("files"), dict) else {}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        cache = {}
    limit, fresh, out = time.time() - WINDOW * 86400, {}, {}
    for root in project_dirs():
        for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
            try:
                st = os.stat(f)
            except OSError:
                continue
            if st.st_mtime < limit:
                continue
            c = cache.get(f)
            if not (isinstance(c, list) and len(c) == 2 and c[0] == st.st_size and isinstance(c[1], dict)):
                c = [st.st_size, _hits(f, known)]
            fresh[f] = c
            for name, day in c[1].items():
                out.setdefault(name, []).append(day)
    try:
        private_dir(DATA)
        tmp = f"{CACHE}.{os.getpid()}.tmp"
        with open(tmp, "w") as w:
            json.dump({"stamp": stamp, "files": fresh}, w)
        os.replace(tmp, CACHE)
    except OSError:
        pass
    return out


def _name(raw, cs):
    """Count a user skill loaded with a plugin-style prefix under its short name; a real plugin keeps its prefix."""
    short = raw.split(":")[-1]
    return short if ":" not in raw or short in cs or os.path.isdir(os.path.join(SKILLS, short)) else raw


def state(names=(), every=False, mx=MAX):
    cs, problems = cards()
    today = dt.date.today()
    recent = (today - dt.timedelta(days=FRESH)).isoformat()
    use = {}
    for raw, days in usage().items():
        use.setdefault(_name(raw, cs), []).extend(days)

    def since(n, after, strict):
        return sum(1 for d in use.get(n, []) if (d > after if strict else d >= after))

    r = {"due": [], "upstream": [], "no_card": [], "not_due": [], "none": [], "plugins": [], "later": [],
         "problems": problems, "unknown": [n for n in names if n not in cs]}
    for n in sorted(use):
        if n not in cs and since(n, recent, False) and not names:
            (r["plugins"] if ":" in n else r["no_card"]).append(n)
    done = set()
    for card in cs.values():
        if id(card) in done or (names and not set(names) & set(card["names"])):
            continue
        done.add(id(card))
        after, strict = (card["checked"], True) if card["checked"] else (recent, False)  # used the day of a check: before it
        active = [x for x in card["names"] if since(x, after, strict)]
        if not (active or every or names):
            continue
        if card["none"]:
            r["none"] += active or card["names"]
            continue
        if not (card["web"] or card["upstream"]):
            r["no_card"] += active  # an empty card of a used skill: to fill, like a missing one
            continue
        age = (today - _date(card["checked"])).days if card["checked"] else None
        if age is not None and age < card["every"] and not names:
            r["not_due"].append(f"{', '.join(active or card['names'])} (checked {card['checked']})")
            continue
        item = {"name": card["names"][0], "group": card["names"], "card": card, "age": age,
                "n": sum(since(x, after, strict) for x in card["names"])}
        r["due" if card["web"] else "upstream"].append(item)
    r["due"].sort(key=lambda d: (d["age"] is not None, -(d["age"] or 0), -d["n"], d["name"]))
    r["due"], r["later"] = r["due"][:mx], r["due"][mx:]
    return r


def _copies(r):
    return r["upstream"] + [d for d in r["due"] + r["later"] if d["card"]["upstream"]]


def cmd_due(names, every, mx):
    r = state(names, every, mx)
    total, copies = len(r["due"]) + len(r["later"]), _copies(r)
    print(f"Skill freshness: {len(r['due'])} to check"
          + (f" out of {total} due (the rest next time)" if r["later"] else "")
          + f", {sum(len(d['group']) for d in copies)} copied skill(s) to compare with their source.\n")
    where = installed()
    for d in r["due"]:
        card = d["card"]
        print(f"### {', '.join(d['group'])} | {d['n']} session(s) "
              + (f"since the check of {card['checked']} ({d['age']} days ago)" if card["checked"]
                 else f"in the last {FRESH} days, never checked")
              + f" | {where.get(d['name'], 'not found in ' + SKILLS)}")
        print("\n".join(line for line in card["text"] if line.strip()) + "\n")
    if copies:
        print("Copied skills to compare (`freshness.py upstream`): " + " ; ".join(", ".join(d["group"]) for d in copies))
    for title, vals in (("Next pass (beyond --max, still due)", [d["name"] for d in r["later"]]),
                        ("No card yet: add one to " + CARDS + " (a card, or `none: reason`)", r["no_card"]),
                        ("Not due (checked within their interval)", r["not_due"]),
                        ("Nothing to watch (`none`)", r["none"]),
                        ("Plugins (updated by `claude plugin update`)", r["plugins"]),
                        ("Names without a card, ignored", r["unknown"]),
                        ("Cards to fix", r["problems"])):
        if vals:
            print(f"{title}: {', '.join(vals)}")


def cmd_short(names, every, mx):
    r = state(names, every, mx)
    due = r["due"] + r["later"]
    print(f"skill freshness: {len(due)} to check"
          + (f" ({', '.join(d['name'] for d in due[:10])}{'...' if len(due) > 10 else ''})" if due else "")
          + f", {sum(len(d['group']) for d in _copies(r))} copied skill(s) to compare, {len(r['no_card'])} without a card"
          + (f", {len(r['problems'])} card(s) to fix" if r["problems"] else "")
          + (": /hindsight:refresh" if due or _copies(r) or r["no_card"] else ""))


def _gh(path):
    p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=40)
    if p.returncode:
        msg = (p.stderr or p.stdout).strip().splitlines()
        raise RuntimeError(msg[-1][:120] if msg else "gh failed")
    return json.loads(p.stdout)


_DATES = {}


def _since(repo, ref):
    """Look from just after the copied commit, or from the start of the copy day (a same-day commit is shown, not
    missed)."""
    if ISO.match(ref):
        return ref + "T00:00:00Z"
    if (repo, ref) not in _DATES:
        d = _gh(f"repos/{repo}/commits/{ref}")["commit"]["committer"]["date"]
        t = dt.datetime.fromisoformat(d.replace("Z", "+00:00")) + dt.timedelta(seconds=1)
        _DATES[(repo, ref)] = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _DATES[(repo, ref)]


def cmd_upstream(names, every, mx):
    """For each `upstream: owner/repo [path] @ref` line: the commits that touched that path since. As soon as one
    skill of a shared card is due, every skill of the card is compared (`checked` dates the whole card)."""
    r = state(names, every, 10 ** 6)
    items = _copies(r)
    if not items:
        print("No copied skill to compare.")
    for d in items:
        for skill in ([n for n in d["group"] if n in names] if names else d["group"]):
            for line in d["card"]["upstream"]:
                m = re.match(r"([\w.-]+/[\w.-]+)(?:\s+(\S+))?\s+@([0-9a-f]{7,40}|\d{4}-\d{2}-\d{2})\s*$", line)
                if not m:
                    print(f"{skill}: unreadable upstream line (expected owner/repo [path] @<commit sha> or "
                          f"@<YYYY-MM-DD>, never a branch): {line}")
                    continue
                repo, path, ref = m.group(1), (m.group(2) or "").replace("{skill}", skill), m.group(3)
                try:
                    commits = _gh(f"repos/{repo}/commits?per_page=20&since={_since(repo, ref)}"
                                  + (f"&path={path}" if path else ""))
                    if not commits and path:  # a wrong path returns no commit: do not call it "unchanged"
                        _gh(f"repos/{repo}/contents/{path}")
                except Exception as ex:  # no gh, network, repo or path gone: said, never guessed
                    print(f"{skill}: not checked ({repo} {path} @{ref}: {ex})")
                    continue
                if not commits:
                    print(f"{skill}: unchanged ({repo} {path} since {ref})")
                    continue
                print(f"{skill}: {len(commits)}{'+' if len(commits) == 20 else ''} commit(s) upstream since {ref} "
                      f"({repo} {path})")
                for c in commits[:6]:
                    print(f"  - {c['sha'][:7]} {c['commit']['committer']['date'][:10]} "
                          f"{c['commit']['message'].splitlines()[0][:90]}")
    if r["problems"]:
        print("Cards to fix: " + ", ".join(r["problems"]))


def cmd_checked(names):
    cs, _ = cards()
    today, done, blocks = dt.date.today().isoformat(), [], {}
    for name in names:
        card = cs.get(name)
        if card is None:
            print(f"{name}: no card, nothing recorded")
        elif card["none"]:
            print(f"{name}: `none` card, nothing to record")
        else:
            blocks[card["line"]] = card
            done.append(", ".join(card["names"]))
    if not blocks:
        return
    with open(CARDS, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    for start in sorted(blocks, reverse=True):  # bottom up: line numbers above stay right
        end = next((i for i in range(start + 1, len(lines)) if HEAD.match(lines[i])), len(lines))
        seen = [i for i in range(start + 1, end) if re.match(r"checked\s*:", lines[i], re.I)]
        if seen:
            lines[seen[0]] = f"checked: {today}"
            for i in reversed(seen[1:]):
                del lines[i]
            continue
        before = next((i for i in range(start + 1, end) if lines[i].startswith("watch")), None)
        if before is None:
            before = max((i for i in range(start, end) if lines[i].strip()), default=start) + 1
        lines.insert(before, f"checked: {today}")
    real = os.path.realpath(CARDS)  # a symlinked cards file stays a symlink
    tmp = f"{real}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as o:
        o.write("\n".join(lines) + "\n")
    os.replace(tmp, real)
    print(f"checked on {today}: {' ; '.join(dict.fromkeys(done))}")


def cmd_init():
    if os.path.exists(CARDS):
        cs, _ = cards()
        missing = [n for n in installed() if ":" not in n and n not in cs]
        print(f"{CARDS} exists; skills without a card: {', '.join(missing) or 'none'}")
        return
    private_dir(os.path.dirname(CARDS))
    body = TEMPLATE + "".join(f"\n## {n}\nwhat: \nwhere: \nfiles: SKILL.md\n" for n in installed() if ":" not in n)
    with open(CARDS, "w", encoding="utf-8") as o:
        o.write(body)
    print(f"wrote {CARDS}: fill each card, or replace its lines with `none: reason`")


def main(argv):
    cmds = {"due": cmd_due, "short": cmd_short, "upstream": cmd_upstream}
    cmd, args = (argv[0] if argv else "due"), argv[1:]
    if cmd == "init":
        return cmd_init()
    if cmd not in cmds and cmd != "checked":
        sys.exit(__doc__.strip())
    mx, every, names = MAX, False, []
    it = iter(args)
    for a in it:
        if a == "--max":
            v = next(it, "")
            if not v.isdigit():
                sys.exit("--max takes a number")
            mx = int(v)
        elif a in ("all", "--all"):
            every = True
        elif a.startswith("-"):
            sys.exit(f"unknown option: {a}\n\n{__doc__.strip()}")
        else:
            names.append(a)
    if cmd == "checked":
        if not names:
            sys.exit("checked takes at least one skill name")
        return cmd_checked(names)
    cmds[cmd](names, every, mx)


if __name__ == "__main__":
    main(sys.argv[1:])
