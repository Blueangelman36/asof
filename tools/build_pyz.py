"""Build asof into one runnable file.

    python tools/build_pyz.py            # writes dist/asof.pyz
    python dist/asof.pyz check

Zero dependencies means the whole tool fits in a zipapp, which is the shortest
path into a repository that is not yours: one file to commit or fetch, no
install step, no virtualenv, no network at check time. That matters most for
automation and for agents working in someone else's project, where `pip install`
is a decision somebody has to make and copying a file is not.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
LAUNCHER = "from asof.cli import entrypoint\n\nentrypoint()\n"


def build(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        shutil.copytree(ROOT / "asof", stage / "asof", ignore=SKIP)
        (stage / "__main__.py").write_text(LAUNCHER, encoding="utf-8")
        zipapp.create_archive(stage, target, interpreter="/usr/bin/env python3")
    return target


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "dist" / "asof.pyz"
    built = build(target)
    size = built.stat().st_size
    print(f"{built.relative_to(ROOT) if built.is_relative_to(ROOT) else built}"
          f"  {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
