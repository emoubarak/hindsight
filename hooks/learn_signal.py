#!/usr/bin/env python3
"""UserPromptSubmit: when the user is correcting Claude, log it and remind Claude where a lesson belongs.

Silent on ordinary prompts. Never blocks, never fails the prompt.
"""
import datetime as dt, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import _common  # noqa: F401,E402

NUDGE = (
    "[hindsight] This message looks like a correction (approximate detection, ignore it if it is not one). "
    "Fix the problem first. Then, only if it is a way of working that will come back (not a tweak to this task), "
    "save it as a `feedback` memory for this project: first line \"scope: global\" or \"scope: project\", then the "
    "expected behaviour and why. If an existing rule (CLAUDE.md, skill, memory) already covered this point, write "
    "\"rule ignored: <where>\": it was not enough and /hindsight:learn will reinforce it. Do not edit the global "
    "CLAUDE.md for this unless the user asks (\"remember this\", \"add it to your rules\")."
)


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    prompt = d.get("prompt") or ""
    from signals import redact, score
    s, hits = score(prompt)
    if s < 2:
        return
    from paths import DATA
    from paths import private_dir
    private_dir(DATA)
    with open(os.path.join(DATA, "signals.jsonl"), "a") as f:
        f.write(json.dumps({"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "cwd": d.get("cwd", ""),
                            "session": d.get("session_id", ""), "hits": [redact(h) for h in hits[:4]], "prompt": redact(prompt)[:1500]},
                           ensure_ascii=False) + "\n")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": NUDGE}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
