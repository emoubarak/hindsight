"""Run with: python3 -m unittest discover -s tests -v   (no dependency; everything happens in a temp HOME)."""
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def write_session(projects, name, events):
    d = os.path.join(projects, "-tmp-demo-api")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".jsonl"), "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


def user(text, ts):
    return {"type": "user", "timestamp": ts, "cwd": "/tmp/demo-api", "message": {"role": "user", "content": text}}


def claude(text, ts):
    return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}}


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        self.projects = os.path.join(self.home, ".claude", "projects")
        self.env = {"PATH": os.environ["PATH"], "HOME": self.home, "HINDSIGHT_DATA": os.path.join(self.home, "data")}
        write_session(self.projects, "aaaa1111", [
            {"type": "ai-title", "title": "Staging deploy"},
            user("how do we deploy the api to staging?", "2026-09-01T10:00:00Z"),
            claude("Run `make deploy ENV=staging`; the key is read from the vault.", "2026-09-01T10:00:05Z"),
            user("the deploy password for staging is hunter2hunter2 by the way", "2026-09-01T10:01:00Z"),
        ])
        write_session(self.projects, "bbbb2222", [
            user("I told you not to add comments everywhere, that's wrong", "2026-09-02T09:00:00Z"),
            claude("Sorry, removing them.", "2026-09-02T09:00:05Z"),
            user("write the invoice export in csv", "2026-09-02T09:05:00Z"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def run_py(self, script, *args, stdin=None):
        return subprocess.run([PY, os.path.join(ROOT, script), *args], input=stdin, capture_output=True, text=True,
                              env=self.env, timeout=60)


class TestSignals(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        os.environ.pop("HINDSIGHT_LANGS", None)
        import signals
        self.s = signals

    def test_correction_detected(self):
        self.assertGreaterEqual(self.s.score("I told you not to do that, that's wrong")[0], 2)

    def test_plain_request_is_not_a_correction(self):
        self.assertLess(self.s.score("can you add a login page please?")[0], 2)

    def test_french_is_opt_in(self):
        self.assertEqual(self.s.score("c'est faux, je t'ai dit")[0], 0)
        os.environ["HINDSIGHT_LANGS"] = "en,fr"
        try:
            self.assertGreaterEqual(self.s.score("c'est faux, je t'ai dit")[0], 2)
        finally:
            os.environ.pop("HINDSIGHT_LANGS")

    def test_recall_phrase(self):
        self.assertTrue(self.s.is_recall("do you remember what we decided for the cache?"))
        self.assertFalse(self.s.is_recall("add a cache to the api"))

    def test_redact_more_forms(self):
        cases = ["DB_PASSWORD=hunter22xyz", "GITHUB_TOKEN=abcd1234efgh", '{"api_key": "abcdef123456"}',
                 "postgres://bob:s3cretpass@db/x", "Authorization: Bearer abc123def456ghi", "AIza" + "x" * 35,
                 "the password for the db is Sup3rS3cret!", "le mdp sudo c'est Zq81xPlm", "wifi password: Zq81xPlm", "login admin mdp Zq81xPlm9", "resend re_AbCdEfGh_" + "x" * 25, "GOCSPX-" + "k" * 28,
                 "bot 123456789:AAF" + "q" * 32, "DB_PASS=Zq81xPlm", "FTP_PASS=Zq81xPlm", "MYSQL_PWD=Zq81xPlm",
                 "SMTP_PASS: Zq81xPlm", "redis://:Zq81xPlm@host", '{"pass": "Zq81xPlm"}', 'PASSWORD="Zq81 xPlm Sup3rS3cret"',
                 "sshpass -p Zq81xPlm ssh host", "curl -u bob:Zq81xPlm https://x", "echo Zq81xPlm | sudo -S true",
                 "Authorization: Basic Zq81xPlmZq81xPlm", "PGPASSWORD=Zq81xPlm psql", "--token Zq81xPlm", "--password=Zq81xPlm",
                 "mysql -uroot -pZq81xPlm", '{"accessToken": "Zq81xPlm"}', "{'password': 'Zq81xPlm'}",
                 "https://hooks.slack.com/services/T000/B000/Zq81xPlm", "https://discord.com/api/webhooks/1/Zq81xPlm",
                 "hf_Zq81xPlm" + "a" * 30, "glpat-Zq81xPlm" + "b" * 12, "xoxb-Zq81xPlm-123456", "AKIAZQ81XPLMZQ81XPLM",
                 "aws secret Zq81xPlm" + "c" * 32, "the db password: Zq81xPlm"]
        for c in cases:
            r = self.s.redact(c)
            self.assertIn("[secret", r, c)
            for leak in ("hunter22xyz", "abcd1234efgh", "abcdef123456", "s3cretpass", "abc123def456ghi", "xxxxxxxx", "Sup3rS3cret", "Zq81xPlm", "AbCdEfGh_", "GOCSPX-k", "123456789:AAF", "AKIAZQ81"):
                self.assertNotIn(leak, r, c)

    def test_truncated_private_key_is_redacted(self):
        r = self.s.redact("-----BEGIN RSA PRIVATE KEY-----\nMIIEabc" + "a" * 300)
        self.assertEqual(r, "[private key]")

    def test_redact(self):
        r = self.s.redact("password is hunter2hunter2 and key sk-" + "a" * 30 + " ghp_" + "b" * 25)
        self.assertNotIn("hunter2", r)
        self.assertNotIn("aaaaaaaaaa", r)
        self.assertNotIn("bbbbbbbbbb", r)


class TestSearch(Env):
    def test_keyword_search_finds_session_and_redacts_secret(self):
        out = self.run_py("scripts/recall.py", "deploy staging", "--type", "msg,session")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)
        self.assertNotIn("hunter2", out.stdout)
        self.assertIn("demo-api", out.stdout)

    def test_no_result_is_explicit(self):
        out = self.run_py("scripts/recall.py", "zebra quantum")
        self.assertIn("no result", out.stdout)

    def test_session_view(self):
        self.run_py("scripts/recall.py", "--index")
        out = self.run_py("scripts/recall.py", "--session", "aaaa1111")
        self.assertIn("how do we deploy", out.stdout)

    def test_unreachable_embeddings_fall_back_to_keywords(self):
        self.env["HINDSIGHT_EMBED_URL"] = "http://127.0.0.1:9/v1/embeddings"
        out = self.run_py("scripts/recall.py", "deploy staging")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)


class TestSemantic(Env):
    """A fake OpenAI-compatible endpoint: hashed bag-of-words vectors, enough to exercise indexing and fusion."""
    def setUp(self):
        super().setUp()
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")
        import http.server, threading, zlib

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                data = []
                for i, t in enumerate(body["input"]):
                    v = [0.0] * 64
                    for w in t.lower().split():
                        v[zlib.crc32(w.encode()) % 64] += 1
                    data.append({"index": i, "embedding": v})
                out = json.dumps({"data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.env["HINDSIGHT_EMBED_URL"] = f"http://127.0.0.1:{self.srv.server_port}/v1/embeddings"

    def tearDown(self):
        self.srv.shutdown()
        super().tearDown()

    def test_hybrid_index_and_search(self):
        r = self.run_py("scripts/recall.py", "--index")
        self.assertIn("embedded", r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.env["HINDSIGHT_DATA"], "index", "vectors.npy")))
        out = self.run_py("scripts/recall.py", "deploy staging", "--type", "msg")
        self.assertIn("sim ", out.stdout)
        self.assertIn("make deploy ENV=staging", out.stdout)

    def test_switching_back_to_keywords_drops_stale_vectors(self):
        self.run_py("scripts/recall.py", "--index")
        del self.env["HINDSIGHT_EMBED_URL"]
        out = self.run_py("scripts/recall.py", "deploy staging")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.env["HINDSIGHT_DATA"], "index", "vectors.npy")))


    def test_embeddings_error_body_falls_back(self):
        self.run_py("scripts/recall.py", "--index")
        self.srv.RequestHandlerClass.do_POST = _bad_post
        out = self.run_py("scripts/recall.py", "deploy staging", "--mode", "hybrid")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)

    def test_model_change_reembeds(self):
        self.run_py("scripts/recall.py", "--index")
        vp = os.path.join(self.env["HINDSIGHT_DATA"], "index", "vectors.npy")
        import numpy as np
        old = np.load(vp)
        np.save(vp, np.zeros((len(old), 8), dtype=np.float16))   # as if another model (other dimension) built it
        out = self.run_py("scripts/recall.py", "deploy staging", "--type", "msg")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)
        self.assertEqual(np.load(vp).shape[1], 64)


def _bad_post(self):
    out = b'{"error": "model not loaded"}'
    self.rfile.read(int(self.headers["Content-Length"]))
    self.send_response(200)
    self.send_header("Content-Length", str(len(out)))
    self.end_headers()
    self.wfile.write(out)


class TestMine(Env):
    def test_digest_lists_correction_with_claude_context(self):
        out = self.run_py("scripts/mine.py", "collect")
        path = out.stdout.strip().splitlines()[-1]
        with open(path) as fh:
            digest = fh.read()
        self.assertIn("I told you not to add comments", digest)
        self.assertNotIn("hunter2", digest)
        self.assertEqual(self.run_py("scripts/mine.py", "pending").stdout.split()[0], "1")


class TestRobustness(Env):
    def test_odd_transcript_lines_do_not_stop_mining(self):
        d = os.path.join(self.projects, "-tmp-odd")
        os.makedirs(d)
        with open(os.path.join(d, "odd0000.jsonl"), "w") as f:
            for line in ["null", "[1,2]", '{"type":"user","message":null}', '{"type":"assistant","message":{"content":null}}',
                         '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":null}]}}',
                         '{"type":"attachment","attachment":null}', "not json"]:
                f.write(line + "\n")
        self.run_py("scripts/mine.py", "mine")
        out = self.run_py("scripts/recall.py", "deploy staging")
        self.assertIn("make deploy ENV=staging", out.stdout, out.stderr)

    def test_odd_types_do_not_break_search_or_digest(self):
        d = os.path.join(self.projects, "-tmp-odd2")
        os.makedirs(d)
        with open(os.path.join(d, "odd1111.jsonl"), "w") as f:
            for line in ['{"type":"ai-title","title":42}', '{"type":"user","timestamp":1760000000,"message":{"content":"rotate the backup keys"}}',
                         '{"type":"user","message":{"content":"no timestamp here, rotate keys"}}', '{"type":"user","message":"plain text"}',
                         '{"type":"user","timestamp":"2026-09-05T08:00:00Z","message":{"content":5}}']:
                f.write(line + "\n")
        self.assertEqual(self.run_py("scripts/mine.py", "collect").returncode, 0)
        self.assertEqual(self.run_py("scripts/mine.py", "stats").returncode, 0)
        out = self.run_py("scripts/recall.py", "rotate backup keys", "--project", "odd")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("rotate", out.stdout)

    def test_secret_in_title_is_redacted(self):
        write_session(self.projects, "eeee5555", [{"type": "ai-title", "title": "set password is Xq7vLm29 on staging"},
                                                  user("set the staging password", "2026-09-06T08:00:00Z")])
        self.run_py("scripts/mine.py", "collect")
        out = self.run_py("scripts/recall.py", "staging password")
        self.assertNotIn("Xq7vLm29", out.stdout)
        for dirpath, _, files in os.walk(self.env["HINDSIGHT_DATA"]):
            for n in files:
                with open(os.path.join(dirpath, n), errors="replace") as fh:
                    self.assertNotIn("Xq7vLm29", fh.read(), n)

    def test_extra_project_dir_under_hidden_folder(self):
        extra = os.path.join(self.home, "laptop", ".claude", "projects")
        write_session(extra, "cccc3333", [user("rotate the backup keys on friday", "2026-09-03T08:00:00Z")])
        self.env["HINDSIGHT_EXTRA_PROJECT_DIRS"] = extra
        out = self.run_py("scripts/recall.py", "rotate backup keys")
        self.assertIn("laptop/cccc3333", out.stdout, out.stderr)

    def test_data_dir_is_private(self):
        self.run_py("scripts/recall.py", "--index")
        for dirpath, dirs, files in os.walk(self.env["HINDSIGHT_DATA"]):
            for n in dirs + files:
                self.assertEqual(os.stat(os.path.join(dirpath, n)).st_mode & 0o077, 0, os.path.join(dirpath, n))

    def test_cut_off_key_never_reaches_the_corpus(self):
        key = "-----BEGIN RSA PRIVATE KEY-----\n" + "MIIEowIBAAKCAQEA" * 200
        write_session(self.projects, "dddd4444", [user("here is the key " + key, "2026-09-04T08:00:00Z")])
        self.run_py("scripts/mine.py", "mine")
        raw = ""
        for dirpath, _, files in os.walk(self.env["HINDSIGHT_DATA"]):
            for n in files:
                if n.endswith(".json"):
                    with open(os.path.join(dirpath, n)) as fh:
                        raw += fh.read()
        self.assertNotIn("MIIEowIBAAKCAQEA", raw)


class TestHooks(Env):
    def test_recall_hook_prompt_starting_with_dash(self):
        self.run_py("scripts/recall.py", "--index")
        r = self.run_py("hooks/recall_hook.py", stdin=json.dumps(
            {"prompt": "-- do you remember how we deploy the api to staging?", "session_id": "x"}))
        self.assertIn("make deploy", r.stdout)

    def hook(self, name, payload):
        return self.run_py(f"hooks/{name}.py", stdin=json.dumps(payload))

    def test_learn_signal_nudges_and_logs(self):
        r = self.hook("learn_signal", {"prompt": "I told you not to touch the config, that's wrong", "cwd": "/x", "session_id": "s"})
        self.assertIn("[hindsight]", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.env["HINDSIGHT_DATA"], "signals.jsonl")))

    def test_learn_signal_silent_on_normal_prompt(self):
        self.assertEqual(self.hook("learn_signal", {"prompt": "add a footer please"}).stdout, "")

    def test_recall_hook_injects_context(self):
        self.run_py("scripts/recall.py", "--index")
        r = self.hook("recall_hook", {"prompt": "do you remember how we deploy the api to staging?", "session_id": "other"})
        ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("make deploy ENV=staging", ctx)

    def test_hooks_fail_open_on_garbage(self):
        for name in ("learn_signal", "recall_hook", "session_start"):
            r = self.run_py(f"hooks/{name}.py", stdin="not json")
            self.assertEqual(r.returncode, 0, name)


if __name__ == "__main__":
    unittest.main()
