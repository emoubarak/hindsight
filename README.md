<p align="center"><img src="docs/banner.svg" alt="Hindsight: memory for Claude Code" width="100%"></p>

**Hindsight gives Claude Code a memory of everything you already told it, and turns the things you keep correcting into rules it follows.**

Two problems, one plugin:

- **"Do you remember how we did this?"** Claude starts every session blank. Hindsight indexes your past sessions
  (user messages, Claude's replies, project memories, rules) and answers that question: a hook runs the search
  when you say "do you remember", "I told you", "where were we", and slips the best hits into the context.
- **"I told you not to do that."** You repeat the same corrections across projects. Hindsight spots them as you type,
  logs them, and `/hindsight:learn` digests them into the narrowest place that works: a hook, a skill,
  `CLAUDE.md`, or a project memory. A rule that was already written and still got ignored is flagged, because that
  is the one that needs to be made automatic.

<p align="center"><img src="docs/demo.svg" alt="A hook answers 'do you remember how we deploy to staging?' from a past session" width="86%"></p>

No server, no account, no required dependency: Python 3.9+ on macOS or Linux, and your own transcripts. Meaning-based search is
optional and works with any OpenAI-compatible embeddings endpoint, including a local one.

## Install

```
/plugin marketplace add emoubarak/hindsight
/plugin install hindsight@hindsight
```

Then restart Claude Code. The first search distills your existing transcripts (a few seconds for hundreds of
sessions) and indexes them.

## Use

| You do | What happens |
|---|---|
| Say "do you remember how we set up X?" | A hook searches your past sessions and memories and adds the top 3 hits to Claude's context. |
| Ask Claude to use the `recall` skill, or Claude decides to | Claude writes its own query (subject, project, exact words), filters by type, project or date, and opens the right session. |
| Correct Claude ("I told you not to...", "that's wrong") | A hook logs it (secrets redacted) and reminds Claude to save a `feedback` memory if it is a habit and not a one-off. |
| Run `/hindsight:learn` | Claude reads the digest of your corrections, checks which ones were already rules, and writes or reinforces rules in the right place. Shows the diff. |
| Start a session after a while | One line tells you if corrections are waiting for a digest. |

Run the search yourself, too. The scripts live in the plugin cache (`~/.claude/plugins/cache/hindsight/hindsight/<version>/scripts/`,
or `scripts/` in a clone); they all read and write the same data directory:

```bash
H=~/.claude/plugins/cache/hindsight/hindsight/*/scripts
python3 $H/recall.py "staging deploy password" --type msg,memory
python3 $H/recall.py "how did we handle rate limits" --project api --before 2026-09-01
python3 $H/recall.py --session 3f2a9c1e      # one session in full
python3 $H/mine.py stats                     # share of your messages that correct Claude, per week
```

## How it works

<p align="center"><img src="docs/how-it-works.svg" alt="Sessions are mined into a corpus and index; recall answers questions; learn turns corrections into rules" width="100%"></p>

1. **Mine.** `scripts/mine.py` distills each transcript in `~/.claude/projects` into a small JSON file: your messages,
   the last words of each Claude reply, tool names, rejected tool calls, interruptions. The corpus outlives Claude
   Code's own transcript cleanup (`cleanupPeriodDays`). Secrets are redacted before anything is written.
2. **Index.** `scripts/recall.py` builds one document per user message (with the two previous messages of the day,
   because "do the same for the footer" means nothing alone), one per session, one per project memory, one per section of each rule file.
   Ranking is BM25 over keywords; with an embeddings endpoint configured it is fused with cosine similarity
   (reciprocal rank fusion), which rescues paraphrases.
3. **Detect.** `signals.py` scores each prompt with a small list of correction patterns (strong ones count 2, weak ones 1,
   two or more is a correction). It is deliberately broad: a false positive costs one log line, a miss loses a lesson.
4. **Digest.** `/hindsight:learn` reads corrections since the last pass, together with what Claude had just said, and
   decides per item: noise, project lesson, or global lesson; then writes it where it will hold.

Every hook fails open: any error means silence, never a blocked prompt.

## Semantic search (optional)

Keyword search needs nothing. For search by meaning, install numpy for the `python3` that runs the hooks
(`apt install python3-numpy`, `dnf install python3-numpy`, `brew install numpy`, or `pip install --user numpy`;
recent distributions refuse a plain `pip install` outside a virtualenv) and point Hindsight at an embeddings endpoint:

```bash
# Ollama
export HINDSIGHT_EMBED_URL=http://localhost:11434/v1/embeddings
export HINDSIGHT_EMBED_MODEL=nomic-embed-text
# llama.cpp:  llama-server -m embeddinggemma-300m-Q8_0.gguf --embeddings --port 8080
export HINDSIGHT_EMBED_URL=http://localhost:8080/v1/embeddings
# a hosted API
export HINDSIGHT_EMBED_URL=https://api.openai.com/v1/embeddings HINDSIGHT_EMBED_MODEL=text-embedding-3-small HINDSIGHT_EMBED_KEY=...
```

If the endpoint stops answering (or takes longer than `HINDSIGHT_QUERY_TIMEOUT`, 6 s), search falls back to keywords and
says so; documents without a vector are retried on the next search. Changing the model re-embeds everything.

> With a hosted endpoint, the text of your messages (already redacted) is sent to that provider. Use a local endpoint
> if your sessions are sensitive.

## Configuration

| Variable | Default | What it does |
|---|---|---|
| `HINDSIGHT_EMBED_URL`, `HINDSIGHT_EMBED_MODEL`, `HINDSIGHT_EMBED_KEY` | unset | Embeddings endpoint (see above). |
| `HINDSIGHT_LANGS` | `en` | Languages of the correction and recall patterns: `en`, `fr`, or `en,fr`. Patterns live in `scripts/signals.py`; adding a language is one dict entry. |
| `HINDSIGHT_DOC_DIRS` | unset | Colon-separated directories whose `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/**/*.md` are indexed too (up to 4 levels deep; `SKILL.md` files included). |
| `HINDSIGHT_EXTRA_PROJECT_DIRS` | unset | Colon-separated extra `projects` directories (e.g. another machine's `~/.claude/projects`, synced). |
| `HINDSIGHT_DATA` | `~/.local/share/hindsight` | Where the corpus, index and signals live (one directory, mode 700, whichever process asks). |
| `HINDSIGHT_QUERY_TIMEOUT` | `6` | Seconds to wait for the embeddings endpoint when searching. |

## Privacy

Everything stays on your machine, in a directory only your user can read (everything the plugin writes is created with umask 077),
unless you configure a remote embeddings endpoint.
Redaction runs when a transcript is distilled and again when a document is indexed, always before anything is truncated.
It masks passwords written in prose ("password is ...", "the db password: ..."), `KEY=value` / `key: value` / JSON / quoted
forms whose name carries a secret word (`DB_PASS`, `PGPASSWORD`, `accessToken`...), `--token`/`--password` flags, `mysql -p`,
`sshpass -p`, `curl -u`, URLs with credentials, `Bearer`/`Basic` headers, Slack and Discord webhooks, well-known vendor
token shapes (`sk-`, `ghp_`, `AKIA`, `AIza`, `GOCSPX-`, `xox*`, `hf_`, `glpat-`, bot tokens, JWTs...), private keys
(even cut off), and long hex strings (git hashes included). Session titles, hook logs and search queries sent to an
embeddings endpoint are redacted too. The test suite checks each of these forms. It is a safety net, not a guarantee: do not rely on it to make a shared machine safe.

## Limits

- Claude's replies are kept only as their last 600 characters. For the rest, `recall.py --session` points to the raw
  transcript, until Claude Code deletes it.
- The correction detector is regex-based. It has no idea about sarcasm, and it only knows the languages you enable.
- Search quality with keywords alone depends on you using the same words. The recall skill tells Claude to
  reformulate for that reason; semantic search helps further.
- Transcripts of sessions run through the SDK or `claude -p` are skipped on purpose.

## Related work

- [Claude Code's built-in memory](https://code.claude.com/docs/en/memory) (`CLAUDE.md` and auto memory) stores what
  Claude decides to write down. Hindsight is the layer around it: it searches everything that was said, and it
  works on the rules themselves.
- [nicknisi/sessions](https://github.com/nicknisi/sessions) is a CLI that searches and mines sessions across several
  coding agents. Hindsight lives inside Claude Code instead (hooks inject results, skills drive the learning loop).

## Develop

```bash
python3 -m unittest discover -s tests -v          # no dependency
uv run --with numpy python -m unittest discover -s tests -v   # also runs the embeddings tests (fake endpoint)
claude plugin validate .
claude --plugin-dir .                              # try it without installing
```

MIT licensed. Contributions welcome, especially pattern lists for more languages.
