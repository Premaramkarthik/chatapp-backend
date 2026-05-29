"""Tinode P2P topic naming tests."""

import base64
import struct

import pytest

from infrastructure.tinode.p2p_topic import TinodeUidError, compute_p2p_topic_names


def _usr(uid_int: int) -> str:
    raw = struct.pack(">Q", uid_int)
    return "usr" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_compute_p2p_topic_names_order_independent() -> None:
    a = _usr(100)
    b = _usr(200)
    names_ab = compute_p2p_topic_names(a, b)
    names_ba = compute_p2p_topic_names(b, a)
    assert names_ab.internal_topic_id == names_ba.internal_topic_id
    assert names_ab.internal_topic_id.startswith("p2p")
    assert names_ab.topic_for_user_a == b
    assert names_ab.topic_for_user_b == a


def test_invalid_uid_raises() -> None:
    with pytest.raises(TinodeUidError):
        compute_p2p_topic_names("bad", _usr(1))
