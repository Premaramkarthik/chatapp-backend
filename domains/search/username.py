"""Username slug helpers aligned with Typesense user documents."""

from __future__ import annotations

import re


def slugify_username(display_name: str | None) -> str | None:
    """Derive a username slug from display_name."""
    if not display_name:
        return None
    slug = re.sub(r"[^a-zA-Z0-9]+", "", display_name.lower())[:64]
    return slug or None
