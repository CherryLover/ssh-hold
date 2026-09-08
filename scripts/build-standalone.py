#!/usr/bin/env python3
"""Fold bin/ssh-hold and lib/ into one executable file.

The result behaves exactly like the installed layout: on the code paths that
actually need the runtime library (`start --password-stdin` and `paste`) it
writes the embedded copies into a per-version cache directory and uses those.
Every other command never touches disk.

Usage: build-standalone.py <version> <output-path>
"""

import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parent.parent
EMBED = re.compile(r"^# >>> EMBED_START.*?^# <<< EMBED_END$", re.DOTALL | re.MULTILINE)
VERSION_LINE = re.compile(r'^VERSION="[^"]*"$', re.MULTILINE)

# (source path in the repo, name in the cache directory, mode there)
PAYLOAD = (
    ("lib/askpass", "askpass", 0o700),
    ("lib/paste.py", "paste.py", 0o600),
    ("skill/SKILL.md", "SKILL.md", 0o600),
)


def heredoc(name, text, mode):
    marker = "SSH_HOLD_EMBED_" + re.sub(r"\W", "_", name).upper()
    if marker in text:
        raise SystemExit(f"{name} contains the heredoc marker {marker}")
    if not text.endswith("\n"):
        text += "\n"
    return (f"  cat >\"$1/{name}\" <<'{marker}'\n"
            f"{text}"
            f"{marker}\n"
            f"  chmod {mode:o} \"$1/{name}\"\n")


def build(version, output):
    script = (ROOT / "bin" / "ssh-hold").read_text(encoding="utf-8")

    if not VERSION_LINE.search(script):
        raise SystemExit("bin/ssh-hold has no VERSION= line to stamp")
    script = VERSION_LINE.sub(f'VERSION="{version}"', script, count=1)

    body = "".join(heredoc(name, (ROOT / source).read_text(encoding="utf-8"), mode)
                   for source, name, mode in PAYLOAD)
    embedded = ("# >>> EMBED_START  由 scripts/build-standalone.py 生成，请勿手工编辑。\n"
                "HAS_EMBEDDED=1\n"
                "embedded_lib() {\n"
                f"{body}"
                "  return 0\n"
                "}\n"
                "# <<< EMBED_END")

    if not EMBED.search(script):
        raise SystemExit("bin/ssh-hold has no EMBED_START/EMBED_END block")
    # A literal backslash in the payload must survive re.sub's replacement parsing.
    script = EMBED.sub(lambda _: embedded, script, count=1)

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(script, encoding="utf-8")
    output.chmod(output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"{output} ({output.stat().st_size} bytes, version {version})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__.strip().splitlines()[-1])
    build(sys.argv[1], sys.argv[2])
