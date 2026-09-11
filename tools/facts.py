"""The commands behind this repo's own claims.

One subcommand per fact, each printing a single number. Keeping them here rather
than inline in asof.ini means they can be read, reviewed and run on their own -
which is the whole argument asof makes about numbers in documents.

    python tools/facts.py source-lines
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_lines() -> int:
    """Every line of Python in the repo, tests included."""
    total = 0
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in {".git", "build", "dist", "__pycache__"} for part in path.parts):
            continue
        total += len(path.read_text(encoding="utf-8").splitlines())
    return total


def test_count() -> int:
    """Asked of unittest, not grepped for."""
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    return suite.countTestCases()


def dependencies() -> int:
    """Third-party runtime dependencies declared in pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    if not match:
        return 0
    return len([item for item in match.group(1).split(",") if item.strip()])


FACTS = {
    "source-lines": source_lines,
    "test-count": test_count,
    "dependencies": dependencies,
}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in FACTS:
        print(f"usage: {argv[0]} {{{'|'.join(FACTS)}}}", file=sys.stderr)
        return 2
    print(FACTS[argv[1]]())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
