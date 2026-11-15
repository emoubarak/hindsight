"""Run with: python3 -m unittest discover -s tests -v   (no dependency; everything happens in a temp HOME)."""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
TODAY = dt.date.today()


def day(n):
    """ISO timestamp n days ago."""
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def skill_call(name, ts):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "tool_use", "id": "t" + name + ts, "name": "Skill", "input": {"skill": name}}]}}


def bash(cmd, ts):
    return {"type": "assistant", "timestamp": ts,
            "message": {"content": [{"type": "tool_use", "id": "b" + ts, "name": "Bash", "input": {"command": cmd}}]}}


def slash(name, ts):
    return {"type": "user", "timestamp": ts,
            "message": {"role": "user", "content": f"<command-name>/{name}</command-name>"}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.claude = os.path.join(self.home, ".claude")
        self.cards = os.path.join(self.home, "data", "freshness.md")
        for s in ("deploy", "shared-a", "shared-b", "notes", "scripted", "old"):
            os.makedirs(os.path.join(self.claude, "skills", s))
            open(os.path.join(self.claude, "skills", s, "SKILL.md"), "w").close()
        self.env = {"PATH": os.environ["PATH"], "HOME": self.home, "HINDSIGHT_DATA": os.path.join(self.home, "data")}
        os.makedirs(os.path.dirname(self.cards))
        self.session("s1", [skill_call("deploy", day(2)), slash("shared-a", day(3)), slash("model", day(3))])
        self.session("s2", [bash(f"python3 {self.claude}/skills/scripted/run.py --x", day(1)),
                            bash(f"cat {self.claude}/skills/notes/SKILL.md", day(1)),
                            skill_call("old", day(50))])
        self.session("s3", [{"type": "user", "timestamp": day(1), "entrypoint": "sdk-cli",
                             "message": {"role": "user", "content": "x"}}, skill_call("notes", day(1))])

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, events):
        d = os.path.join(self.claude, "projects", "-tmp-demo")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name + ".jsonl"), "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def write_cards(self, body):
        with open(self.cards, "w") as f:
            f.write(body)

    def run_(self, *args, ok=True):
        p = subprocess.run([PY, os.path.join(ROOT, "scripts", "freshness.py"), *args], env=self.env,
                           capture_output=True, text=True, timeout=60)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout + p.stderr



class Freshness(Base):
    CARDS = """# cards

## deploy
what: hosting limits
where: the provider's changelog

## shared-a, shared-b
what: a shared fact
Every: 10

## notes
none: internal convention

## scripted
what: a tool's flags
checked: {recent}

## old
what: something
"""

    def test_due_counts_tool_slash_and_script_but_not_reads_or_sdk(self):
        self.write_cards(self.CARDS.format(recent=(TODAY - dt.timedelta(days=5)).isoformat()))
        out = self.run_("due")
        self.assertIn("### deploy | 1 session(s) in the last", out)
        self.assertIn("### shared-a, shared-b | 1 session(s) in the last", out)    # a /command of an installed skill
        self.assertIn("scripted (checked", out)                        # used, but checked within its interval
        self.assertNotIn("### scripted", out)
        self.assertNotIn("### old", out)                               # used 50 days ago only: not due
        self.assertNotIn("notes", out.split("Nothing to watch")[0])    # `cat` of its file and an sdk session
        self.assertNotIn("model", out)                                 # a built-in command is not a skill

    def test_card_problems_are_reported(self):
        self.write_cards("## a\nwhat: x\nchecked: 15/11/2026\nwhre: typo\n")
        out = self.run_("due", "a")
        self.assertIn("unreadable date `15/11/2026`", out)
        self.assertIn("unknown key `whre`", out)

    def test_empty_card_is_not_due_but_reported(self):
        self.write_cards("## deploy\nwhat: \nwhere: \nfiles: SKILL.md\n")
        out = self.run_("due")
        self.assertNotIn("### deploy", out)
        self.assertIn("empty card", out)

    def test_used_skill_without_card_is_listed(self):
        self.write_cards("## other\nwhat: x\n")
        self.assertIn("No card yet", self.run_("due"))
        self.assertIn("deploy", self.run_("due").split("No card yet")[1])

    def test_checked_inserts_then_replaces_and_dates_the_whole_card(self):
        self.write_cards(self.CARDS.format(recent="2020-01-01"))
        self.run_("checked", "shared-b", "notes", "missing")
        with open(self.cards) as f:
            body = f.read()
        self.assertEqual(body.count(f"checked: {TODAY.isoformat()}"), 1)
        self.assertIn("## notes\nnone: internal convention\n", body)   # a `none` card gets no date
        self.run_("checked", "scripted")
        with open(self.cards) as f:
            body = f.read()
        self.assertNotIn("2020-01-01", body)
        self.assertEqual(body.count(f"checked: {TODAY.isoformat()}"), 2)
        out = self.run_("due")
        self.assertNotIn("### shared-a", out)

    def test_max_keeps_the_rest_due(self):
        self.write_cards(self.CARDS.format(recent="2020-01-01"))
        out = self.run_("due", "--max", "1")
        self.assertIn("Next pass (beyond --max, still due)", out)
        self.assertEqual(out.count("### "), 1)

    def test_upstream_without_gh_says_not_checked(self):
        self.write_cards("## copied\nupstream: owner/repo skills/{skill} @abc1234\n")
        self.env["PATH"] = os.path.join(self.home, "empty")            # no gh on the PATH
        out = self.run_("upstream", "copied")
        self.assertIn("copied: not checked", out)
        self.assertNotIn("unchanged", out)

    def test_init_writes_a_card_per_installed_skill_and_bad_args_fail(self):
        out = self.run_("init")
        self.assertIn("wrote", out)
        with open(self.cards) as f:
            body = f.read()
        for s in ("deploy", "shared-a", "notes"):
            self.assertIn(f"\n## {s}\n", body)
        self.assertIn("exists", self.run_("init"))
        self.assertIn("unknown option", self.run_("due", "--bogus", ok=False))
        self.assertIn("--max takes a number", self.run_("due", "--max", ok=False))


class Detection(unittest.TestCase):
    """Which Bash commands count as running a skill's script."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import freshness
        cls.f = freshness

    def test_runs(self):
        for cmd in ("python3 ~/.claude/skills/x/run.py --a",
                    "bash ~/.claude/skills/x/go.sh",
                    "timeout 60 uv run --with numpy ~/.claude/skills/x/run.py",
                    "cd /tmp && FOO=1 python3 -I $HOME/.claude/skills/x/run.py",
                    "ls; ~/.claude/skills/x/scripts/tool arg",
                    'bash -c "python3 ~/.claude/skills/x/run.py"',
                    "/usr/bin/python3 -I ~/.claude/skills/x/run.py"):
            self.assertEqual(self.f._executed(cmd), {"x"}, cmd)

    def test_reads_are_not_runs(self):
        for cmd in ("cat ~/.claude/skills/x/SKILL.md",
                    'grep -n "a\\|b" ~/.claude/skills/x/SKILL.md',
                    "cd ~/.claude/skills/x/scripts; sed -n 1,5p run.py",
                    "chmod +x ~/.claude/skills/x/run.sh",
                    "git commit -m 'edit ~/.claude/skills/x/run.py'",
                    "python3 -c 'open(\"~/.claude/skills/x/a\")'",
                    "cat > /tmp/a <<'EOF'\npython3 ~/.claude/skills/x/run.py\nEOF"):
            self.assertEqual(self.f._executed(cmd), set(), cmd)


class Flow(Base):
    def fake_gh(self, script):
        b = os.path.join(self.home, "bin")
        os.makedirs(b, exist_ok=True)
        with open(os.path.join(b, "gh"), "w") as f:
            f.write("#!" + PY + "\nimport sys, json\n" + script)
        os.chmod(os.path.join(b, "gh"), 0o755)
        self.env["PATH"] = b + os.pathsep + self.env["PATH"]

    def test_init_then_due_lists_used_skills_to_fill(self):
        self.run_("init")
        out = self.run_("due")
        self.assertIn("No card yet", out)
        self.assertIn("deploy", out.split("No card yet")[1])
        self.assertIn("/hindsight:refresh", self.run_("short"))
        self.assertNotIn("example", self.run_("due", "all"))      # the examples in the template are not cards

    def test_used_the_day_of_the_check_is_not_due(self):
        self.write_cards("## deploy\nwhat: x\nevery: 1\nchecked: " + day(2)[:10] + "\n")
        self.assertNotIn("### deploy", self.run_("due"))

    def test_sdk_session_is_not_counted(self):
        self.write_cards("## notes\nwhat: x\n")
        self.assertNotIn("### notes", self.run_("due"))

    def test_cache_is_recomputed_when_a_skill_is_installed(self):
        self.session("s4", [slash("newskill", day(1))])
        self.write_cards("## newskill\nwhat: x\n")
        self.assertNotIn("### newskill", self.run_("due"))         # not installed yet: a built-in for all we know
        os.makedirs(os.path.join(self.claude, "skills", "newskill"))
        open(os.path.join(self.claude, "skills", "newskill", "SKILL.md"), "w").close()
        self.assertIn("### newskill", self.run_("due"))

    def test_checked_keeps_a_symlink(self):
        real = os.path.join(self.home, "real.md")
        with open(real, "w") as f:
            f.write("## deploy\nwhat: x\n")
        os.symlink(real, self.cards)
        self.run_("checked", "deploy")
        self.assertTrue(os.path.islink(self.cards))
        with open(real) as f:
            self.assertIn("checked: " + TODAY.isoformat(), f.read())

    def test_upstream_with_gh(self):
        self.fake_gh("p = sys.argv[2]\n"
                     "if p.startswith('repos/o/r/commits/'): print(json.dumps({'commit': {'committer': {'date': '2026-01-01T00:00:00Z'}}}))\n"
                     "elif 'path=moved' in p: print(json.dumps([{'sha': 'abcdef1234', 'commit': {'committer': {'date': '2026-02-01T00:00:00Z'}, 'message': 'Fix it'}}]))\n"
                     "elif 'commits?' in p: print('[]')\n"
                     "elif 'contents/gone' in p: sys.exit(1)\n"
                     "else: print('{}')\n")
        self.write_cards("## moved\nupstream: o/r moved @abc1234\n\n## same\nupstream: o/r same @2026-01-01\n\n"
                         "## gone\nupstream: o/r gone @abc1234\n\n## branch\nupstream: o/r x @main\n")
        out = self.run_("upstream", "moved", "same", "gone", "branch")
        self.assertIn("moved: 1 commit(s) upstream", out)
        self.assertIn("same: unchanged", out)
        self.assertIn("gone: not checked", out)
        self.assertIn("branch: unreadable upstream line", out)


if __name__ == "__main__":
    unittest.main()
