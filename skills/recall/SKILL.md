---
name: recall
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/recall.py" *), Read, Grep
description: Search what the user already said, did or wrote - past Claude Code sessions, project memories, rules and docs. Use before asking them to repeat anything, when they say "do you remember", "I told you", "where were we", "like last time", "we already did X", when a fact (a decision, a setting, a URL, a name) obviously comes from an earlier conversation, before claiming "we never did X", and before writing a new memory (is it a duplicate?).
---

# Search what we already did

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/recall.py" "<query>" [--type msg,session,memory,doc,rule] [-k 10] [--project <path fragment>] [--before YYYY-MM-DD]
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/recall.py" --session <sid>     # one session in full, with the path of the raw transcript
```

Each result gives date, project, title and where it lives: `machine/sid #i` (an event of a session) or `path:line`
(doc, rule, memory). The search first refreshes the corpus and the index (under a second when little changed).

| Need | `--type` |
|---|---|
| Recall a conversation ("do you remember", a decision, something they gave you) | `msg,session,memory` |
| How another project solved the same problem | `doc,rule`, then `memory` |
| Did a rule already exist (before writing a memory, in `/hindsight:learn`) | `rule,memory` |
| Nothing certain | no `--type` |

Without the filter, project docs push conversation hits down the list.

## Method

1. **Write your own query**, do not only paste their sentence: the subject, the project and the exact words they
   probably used ("staging deploy password for the api project"). Their raw sentence is the second attempt.
2. Pass `--project` as soon as the project is known; `-k 20` when nothing stands out.
3. Open the right hit: `--session <sid>` and read around `#i` (what follows often holds the final decision), or read
   the file at the given line.
4. The corpus keeps user messages up to 2500 characters but only the last 600 characters of each Claude reply, and replaces
   secrets with `[secret]`. For the detail or a value, read the raw transcript that `--session` points to. A secret
   you find is used, never displayed.
5. Nothing convincing: say so, with the queries you tried, and `grep` the raw transcripts
   (`~/.claude/projects/*/*.jsonl`) before concluding there is nothing.

The `UserPromptSubmit` hook already runs a search (their raw sentence, sessions and memories) when the message
contains a recall phrase, and puts the top 3 results in context. If they answer, use them; otherwise run the
reworded search above.

## Modes

Keyword search (BM25) works with no setup. For meaning-based search, point `HINDSIGHT_EMBED_URL` at any
OpenAI-compatible embeddings endpoint (and `HINDSIGHT_EMBED_MODEL`, `HINDSIGHT_EMBED_KEY` if needed) and install numpy;
`--mode hybrid` (default when configured) fuses both rankings, `semantic` and `keyword` use one. If the endpoint
does not answer, the search falls back to keywords and says so.

## What is indexed

- The corpus `mine.py` distills from your transcripts: one document per user message (with the two previous
  messages of the same day and the Claude reply that follows) and one per session (title and first messages).
- Project memories (`~/.claude/projects/*/memory/*.md`, not the `MEMORY.md` indexes).
- Rules: `~/.claude/CLAUDE.md` and every `SKILL.md` there. Add docs with `HINDSIGHT_DOC_DIRS=dir1:dir2` (their
  `README.md`, `CLAUDE.md`, `AGENTS.md`, `docs/**/*.md`).
- Secrets are masked at indexing time (passwords, tokens, private keys, long hex strings).
- Index: `index/` in `~/.local/share/hindsight` (or `HINDSIGHT_DATA`), private (mode 700/600).
