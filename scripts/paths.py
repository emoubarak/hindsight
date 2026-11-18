"""Where things live: ~/.local/share/hindsight, or HINDSIGHT_DATA. One directory, whichever process asks (hook,
skill command, your shell), so the corpus, the index and the signals never split in two.

Everything this plugin writes is private to your user (umask 077)."""
import glob, os

os.umask(0o077)

HOME = os.path.expanduser("~")
CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(HOME, ".claude")
DATA = os.environ.get("HINDSIGHT_DATA") or os.path.join(HOME, ".local/share/hindsight")
CORPUS = os.path.join(DATA, "corpus")
CONFIG = os.environ.get("HINDSIGHT_CONFIG") or os.path.join(HOME, ".config/hindsight")
PEERS = os.path.join(DATA, "peers")           # transcripts and memories pulled from other machines (`mine.py pull`)


def project_dirs():
    """Every `projects` directory to read transcripts and memories from: this machine's, plus any listed in
    HINDSIGHT_EXTRA_PROJECT_DIRS (colon-separated; e.g. a synced copy of another machine's ~/.claude/projects),
    plus the machines pulled by `mine.py pull` (see CONFIG/peers)."""
    out = [os.path.join(CLAUDE, "projects")]
    out += [p for p in os.environ.get("HINDSIGHT_EXTRA_PROJECT_DIRS", "").split(":") if p]
    out += sorted(glob.glob(os.path.join(PEERS, "*", "projects")))
    return out


def private_dir(path):
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path
