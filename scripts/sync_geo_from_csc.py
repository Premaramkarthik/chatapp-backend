"""Load geo master tables from countrystatecity-countries SDK."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = Path(__file__).resolve().parent
for path in (REPO_ROOT, SCRIPTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from geo_sync.cli import parse_args  # noqa: E402
from geo_sync.orchestrator import main_async  # noqa: E402


def main() -> None:
    """CLI entry for geo CSC sync."""
    raise SystemExit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
