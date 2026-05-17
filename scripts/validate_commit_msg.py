"""Small conventional-commit validator used by pre-commit."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)" r"(\([a-z0-9_.-]+\))?!?: .+"
)


def main() -> int:
    if len(sys.argv) < 2:
        return 0
    message = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()[0].strip()
    if PATTERN.match(message):
        return 0
    print("Commit message must follow Conventional Commits, e.g. feat(api): add health")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
