"""Where things live: ~/.local/share/hindsight, or HINDSIGHT_DATA. One directory, whichever process asks (hook,
skill command, your shell), so the corpus, the index and the signals never split in two.

Everything this plugin writes is private to your user (umask 077)."""
import os

os.umask(0o077)

HOME = os.path.expanduser("~")
CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
DATA = os.environ.get("HINDSIGHT_DATA") or os.path.join(HOME, ".local/share/hindsight")
CORPUS = os.path.join(DATA, "corpus")


def project_dirs():
    """Every `projects` directory to read transcripts and memories from: this machine's, plus any listed in
    HINDSIGHT_EXTRA_PROJECT_DIRS (colon-separated; e.g. a synced copy of another machine's ~/.claude/projects)."""
    out = [os.path.join(CLAUDE, "projects")]
    out += [p for p in os.environ.get("HINDSIGHT_EXTRA_PROJECT_DIRS", "").split(":") if p]
    return out


def private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path
