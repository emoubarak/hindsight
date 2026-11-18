"""Your own setup on top of the engine: secret hashes, digest extensions, other machines.
Run with: python3 -m unittest discover -s tests -v   (no dependency; everything happens in a temp HOME)."""
import hashlib, json, os, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.cfg = os.path.join(self.home, "cfg")
        os.makedirs(self.cfg)
        self.env = {"PATH": os.environ["PATH"], "HOME": self.home, "HINDSIGHT_DATA": os.path.join(self.home, "data"),
                    "HINDSIGHT_CONFIG": self.cfg}

    def tearDown(self):
        self.tmp.cleanup()

    def mine(self, *args, stdin=None):
        return subprocess.run([PY, os.path.join(ROOT, "scripts", "mine.py"), *args], input=stdin,
                              capture_output=True, text=True, env=self.env, timeout=60)

    def session(self, root, text):
        d = os.path.join(root, "-tmp-demo")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "s1.jsonl"), "w") as f:
            f.write(json.dumps({"type": "user", "timestamp": "2026-09-01T10:00:00Z", "cwd": "/tmp/demo",
                                "message": {"role": "user", "content": text}}) + "\n")

    def test_secret_hash_erases_declared_secret(self):
        r = self.mine("secret", stdin="correct-horse-battery\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        h = open(os.path.join(self.cfg, "secret-hashes")).read().strip()
        self.assertEqual(h, hashlib.sha256(b"correct-horse-battery").hexdigest())
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.cfg, "secret-hashes")).st_mode), 0o600)
        self.session(os.path.join(self.home, ".claude", "projects"), "my login is correct-horse-battery ok")
        self.mine("mine")
        corpus = "".join(open(os.path.join(dp, f)).read()
                         for dp, _, fs in os.walk(os.path.join(self.home, "data", "corpus")) for f in fs)
        self.assertNotIn("correct-horse-battery", corpus)
        self.assertIn("[secret]", corpus)

    def test_secret_scrubs_existing_corpus_in_place(self):
        corpus = os.path.join(self.home, "data", "corpus", "laptop")
        os.makedirs(corpus)
        s = {"machine": "laptop", "project": "p", "title": "t", "first": "2026-01-01T00:00:00Z", "last": "2026-01-01T00:00:00Z",
             "events": [["U", "the vault phrase is correct-horse-battery today", "2026-01-01T00:00:00Z"]]}
        with open(os.path.join(corpus, "history-1.json"), "w") as f:
            json.dump(s, f)
        r = self.mine("secret", stdin="correct-horse-battery\n")
        self.assertIn("1 corpus file(s) scrubbed", r.stdout)
        with open(os.path.join(corpus, "history-1.json")) as f:
            body = f.read()
        self.assertNotIn("correct-horse-battery", body)

    def test_redact_catches_french_key_phrases_and_uuid_hex_keys(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from signals import redact
        for text, secret in (("la clé api c'est abcd1234efgh", "abcd1234efgh"),
                             ("token est zzzz9999yyyy", "zzzz9999yyyy"),
                             ("key 123e4567-e89b-12d3-a456-426614174000:0123456789abcdef0123", "0123456789abcdef0123")):
            self.assertNotIn(secret, redact(text), text)

    def test_policy_subcommand(self):
        self.assertIn("no policy file", self.mine("policy").stdout)
        with open(os.path.join(self.cfg, "policy.md"), "w") as f:
            f.write("Write rules in French.\n")
        self.assertIn("Write rules in French.", self.mine("policy").stdout)

    def test_digest_extension_is_appended_and_failures_are_one_line(self):
        d = os.path.join(self.cfg, "digest.d")
        os.makedirs(d)
        ok, bad, plain = (os.path.join(d, n) for n in ("10-ok", "20-bad", "30-plain"))
        open(ok, "w").write("#!/bin/sh\necho '## 9. Mine'; echo \"since=$HINDSIGHT_SINCE\"\n")
        open(bad, "w").write("#!/bin/sh\necho boom >&2; exit 3\n")
        open(plain, "w").write("not executable, ignored\n")
        os.chmod(ok, 0o755), os.chmod(bad, 0o755)
        self.session(os.path.join(self.home, ".claude", "projects"), "hello")
        self.mine("mine")
        path = self.mine("digest").stdout.strip().splitlines()[-1]
        body = open(path).read()
        self.assertIn("## 9. Mine", body)
        self.assertIn("20-bad failed: boom", body)
        self.assertNotIn("ignored", body)

    def test_custom_nudge_replaces_the_default(self):
        hook = os.path.join(ROOT, "hooks", "learn_signal.py")
        stdin = json.dumps({"prompt": "I told you not to do that, it's wrong", "cwd": "/tmp/x", "session_id": "s"})
        run = lambda: subprocess.run([PY, hook], input=stdin, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertIn("propose it", run().stdout)
        with open(os.path.join(self.cfg, "nudge.txt"), "w") as f:
            f.write("Write the memory yourself.\n")
        self.assertIn("Write the memory yourself.", run().stdout)

    def test_pull_reports_unreachable_machine_without_failing(self):
        open(os.path.join(self.cfg, "peers"), "w").write("# comment\nlaptop nobody@127.0.0.1.invalid\n")
        r = self.mine("pull")
        self.assertEqual(r.returncode, 0)
        self.assertIn("laptop: unreachable", r.stdout)

    def test_pulled_machine_is_mined_under_its_own_label(self):
        self.session(os.path.join(self.home, "data", "peers", "laptop", "projects"), "from the other machine")
        self.mine("mine")
        self.assertTrue(os.path.isdir(os.path.join(self.home, "data", "corpus", "laptop")))


if __name__ == "__main__":
    unittest.main()
