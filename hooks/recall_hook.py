#!/usr/bin/env python3
"""UserPromptSubmit: when the user appeals to a memory ("do you remember", "where were we", "like last time"),
run recall on their sentence and slip the top 3 results into the context.

Silent on other messages. Never blocks: if recall is absent, slow or failing, nothing is added.
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import _common  # noqa: E402


def main():
    try:
        d = json.load(sys.stdin)
    except Exception:
        return
    prompt = (d.get("prompt") or "").strip()
    from signals import is_recall
    if not prompt or not is_recall(prompt):
        return
    recall = os.path.join(_common.SCRIPTS, "recall.py")
    # Index as it is (a full reindex could take minutes and this hook would be killed every time);
    # the refresh runs in the background for the next call.
    try:
        subprocess.Popen([sys.executable, recall, "--index", "--nowait"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        pass
    cmd = [sys.executable, recall, "--type", "msg,session,memory", "-k", "3", "--no-update"]
    if d.get("session_id"):
        cmd += ["--exclude", d["session_id"]]
    cmd += ["--", prompt[:1000]]        # "--": a prompt starting with "-" is a question, not an option
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=8).stdout.strip()
    except Exception:
        return
    if not out or out.startswith("recall: no result"):
        return
    ctx = ("[hindsight] The user's message appeals to a memory. Automatic search on their raw sentence "
           "(past sessions and memories, top 3):\n" + out[:2500] +
           "\nIf this does not answer, run the recall skill with your own query (subject, project, exact words) "
           "before asking them to repeat anything.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}},
                     ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
