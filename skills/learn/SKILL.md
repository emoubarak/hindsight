---
name: learn
description: Digest the user's corrections collected from their Claude Code sessions and turn them into durable rules in the right place, reinforcing the ones that did not hold. Run with /hindsight:learn.
disable-model-invocation: true
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mine.py" *), Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/recall.py" *), Read, Grep
argument-hint: "[topic or project to focus on]"
---

# Learn from corrections

Goal: the user should never have to say the same thing twice. Fewer rules, and rules that hold, not a list that
keeps growing. Focus for this pass: $ARGUMENTS

## Material (collected before you read this)

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mine.py" collect`

Read the digest whose path is printed above. It contains, since the last pass: (1) messages that look like
corrections, with what Claude had just said (`A:`), including tool calls the user rejected (`R`) and
interruptions (`X`); (2) project memories written since; (3) signals captured live by the hook. The filter is
broad: expect noise. If the digest is over ~150 KB, have sub-agents triage it per project and return only the
lessons, with quotes.

## Triage each item

- **Noise** (not a correction) or a **one-off tweak** ("move it 2px") -> nothing.
- **Project lesson** -> that project's `CLAUDE.md` (or its memory when it is a fact more than an instruction).
- **Global lesson**: seen in at least two projects or sessions, or stated as universal ("always", "whatever the
  project") -> see the ladder below.
- **Ignored rule**: the correction is about a point already written somewhere (a memory marked "rule ignored",
  or one you find: for each retained correction run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/recall.py" "<the lesson in one sentence>" --type rule,memory -k 5`).
  This is the most important signal: the rule failed. Do not copy it again. Make it more concrete, put it at the
  moment the mistake happens (a step in a skill), or make it automatic (a hook).

## Where to write: the narrowest place that works

1. **Automatic** if a machine can check it: a hook in your settings that denies or warns. A hook must fail open
   (any error means silence) and stay fast; test it with a sample input before relying on it.
2. **A skill** if it only concerns one kind of task: add the step or the trap at the right place. A task type that
   came back three times without a skill -> create the skill.
3. **Global `~/.claude/CLAUDE.md`** only if true in every session. Keep it short; merge or shorten before adding.
4. **Project**: its `CLAUDE.md` or memory.

A global lesson found in a project memory moves up, and the project copy is deleted or cut down to what is
specific to the project. Two contradicting instructions: the most recent and explicit wins; fix the stale one.

## Writing a rule

The expected behaviour, its limit and why, in one or two lines, with a concrete example from their own words if
it helps. No shouting, no "CRITICAL": the reason does the work. Never copy a secret.

## Finish

1. Show the diff of what you wrote and remove anything that is not crisp.
2. `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mine.py" done`
3. Report in a few lines: each lesson kept (with their sentence), where it is written, what was reinforced or
   automated, what was ignored and why. Then the trend from
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mine.py" stats` (share of messages that correct Claude, per week).
   It is approximate: watch the direction, not the number.
