#!/usr/bin/env python3
"""UserPromptSubmit: when the user is correcting Claude, log it and remind Claude where a lesson belongs.

Silent on ordinary prompts. Never blocks, never fails the prompt.
"""
import datetime as dt, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import _common  # noqa: F401,E402

NUDGE = (
    "[hindsight] This message looks like a correction (approximate detection, ignore it if it is not one). "
    "Fix the problem first. If it is a way of working that will come back, do not write the rule yourself: "
    "propose it, in one line, with where it would go (a `feedback` memory for this project, or a global rule), "
    "and wait for a yes. One correction in one repo is a project rule, never a global one, however strongly it "
    "is worded. If an existing rule (CLAUDE.md, skill, memory) already covered this point, write "
    "\"rule ignored: <where it is written>\" in the proposal and in the memory: it was not enough and "
    "/hindsight:learn will reinforce it."
)


def nudge():
    """Your own reminder, if you wrote one ($HINDSIGHT_CONFIG/nudge.txt): another language, or "write the memory
    yourself" instead of "propose it"."""
    from paths import CONFIG
    try:
        text = open(os.path.join(CONFIG, "nudge.txt"), encoding="utf-8").read().strip()
    except (OSError, ValueError):
        return NUDGE
    return text or NUDGE


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
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": nudge()}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
