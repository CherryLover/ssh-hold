"""Point the tests at this checkout, not at whatever is installed in ~/.local."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(os.environ.get("SSH_HOLD_BIN", ROOT / "bin" / "ssh-hold"))
LIB = Path(os.environ.get("SSH_HOLD_LIB", ROOT / "lib"))
# What `ssh-hold skill install` is expected to write, whatever build is under test.
SKILL = ROOT / "skill" / "SKILL.md"

if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))


def env(**overrides):
    """Base environment for subprocess runs.

    Normally pinned to this checkout's lib so a stale ~/.local install cannot be
    tested by mistake. When SSH_HOLD_BIN names a specific executable — the
    standalone build, say — leave it alone so it resolves its own runtime lib.
    """
    base = dict(os.environ, **overrides)
    if "SSH_HOLD_BIN" not in os.environ:
        base["SSH_HOLD_LIB"] = str(LIB)
    return base
