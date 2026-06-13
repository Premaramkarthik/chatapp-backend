"""CLI argument parsing for geo sync."""

from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse geo sync CLI options."""
    parser = argparse.ArgumentParser(description="Sync geo_* master tables from CSC dataset")
    parser.add_argument("--database-url", default=None, help="Override DB DSN")
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate geo master tables before load (fastest path)",
    )
    parser.add_argument(
        "--flush-redis",
        action="store_true",
        help="Flush geo:* Redis keys after successful sync",
    )
    parser.add_argument(
        "--limit-countries",
        type=int,
        default=None,
        help="Sync only the first N countries (smoke testing)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="City batch size for COPY/upsert (default: 5000)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)
