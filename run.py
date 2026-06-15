#!/usr/bin/env python3
"""Run AI News Finder from the news-update project root."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "ai_news_finder"
MAIN = PKG / "ai_news_finder.py"


def main() -> int:
    if not MAIN.is_file():
        print(f"Error: missing {MAIN}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, str(MAIN), *sys.argv[1:]],
        cwd=str(PKG),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
