"""Tinode P2P topic naming (matches server/types Uid + p2p prefix rules)."""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass


class TinodeUidError(ValueError):
    """Invalid Tinode user id format."""


@dataclass(frozen=True)
class P2pTopicNames:
    """Canonical internal topic id and per-user peer topic aliases."""

    internal_topic_id: str
    topic_for_user_a: str
    topic_for_user_b: str


def _decode_uid_bytes(tinode_user_id: str) -> bytes:
    """Decode ``usr<base64url>`` to eight big-endian uid bytes."""
    if not tinode_user_id.startswith("usr"):
        raise TinodeUidError(f"expected usr-prefixed id, got {tinode_user_id!r}")
    encoded = tinode_user_id[3:]
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode(encoded + padding)
    except Exception as exc:
        raise TinodeUidError(f"invalid tinode user id: {tinode_user_id!r}") from exc
    if len(raw) < 8:
        raise TinodeUidError(f"tinode uid payload too short: {tinode_user_id!r}")
    return raw[:8]


def _uid_uint64(tinode_user_id: str) -> int:
    return struct.unpack(">Q", _decode_uid_bytes(tinode_user_id))[0]


def compute_p2p_topic_names(tinode_uid_a: str, tinode_uid_b: str) -> P2pTopicNames:
    """Return internal ``p2p…`` id and each user's view of the peer topic."""
    a = _uid_uint64(tinode_uid_a)
    b = _uid_uint64(tinode_uid_b)
    low, high = (a, b) if a < b else (b, a)
    payload = struct.pack(">QQ", low, high)
    internal = "p2p" + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return P2pTopicNames(
        internal_topic_id=internal,
        topic_for_user_a=tinode_uid_b,
        topic_for_user_b=tinode_uid_a,
    )
