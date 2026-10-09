#!/usr/bin/env python3
"""SessionStart (startup): refresh the corpus in the background; print one line only when there is something
to know (corrections waiting to be digested). Silent otherwise."""
import datetime as dt, json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import _common  # noqa: E402


def main():
    from paths import DATA
    # raw transcripts expire (cleanupPeriodDays), the distilled corpus stays
    subprocess.Popen([sys.executable, os.path.join(_common.SCRIPTS, "mine.py"), "mine"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        last = open(os.path.join(DATA, "last_digest")).read().strip()
    except OSError:
        last = ""
    n, first = 0, None
    try:
        for line in open(os.path.join(DATA, "signals.jsonl")):
            ts = json.loads(line)["ts"]
            if ts > last:
                n += 1
                first = first or ts
    except Exception:
        pass
    days = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)).days if last else 99
    if n >= 20 or (n >= 4 and days >= 10):
        since = dt.datetime.fromisoformat(first).strftime("%Y-%m-%d")
        print(json.dumps({"systemMessage": f"hindsight: {n} corrections since {since} not digested yet "
                                           f"(run /hindsight:learn)."}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
