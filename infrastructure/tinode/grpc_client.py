"""Tinode gRPC admin helpers (channel health + P2P topic metadata)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import grpc

from core.config.settings import settings
from infrastructure.tinode.p2p_topic import P2pTopicNames, compute_p2p_topic_names

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class P2pProvisionResult:
    """Outcome of P2P topic preparation for a connection."""

    names: P2pTopicNames
    grpc_reachable: bool
    trusted_public: dict[str, Any]


class TinodeGrpcError(RuntimeError):
    """gRPC connectivity or configuration failure."""


def _channel() -> grpc.aio.Channel:
    target = settings.tinode.grpc_host
    if not target.startswith("dns:") and ":" not in target:
        target = f"{target}:16060"
    return grpc.aio.insecure_channel(target)


async def check_grpc_reachable() -> bool:
    """Return True when the Tinode gRPC port accepts a channel."""
    if not settings.tinode.enabled:
        return False
    try:
        channel = _channel()
        await channel.channel_ready()
        await channel.close()
        return True
    except Exception as exc:
        logger.debug("tinode grpc unreachable: %s", exc)
        return False


async def prepare_p2p_conversation(
    *,
    tinode_uid_a: str,
    tinode_uid_b: str,
    connection_id: str,
    peer_display_name: str | None,
) -> P2pProvisionResult:
    """
    Compute canonical P2P topic identifiers and optional gRPC reachability.

    Tinode creates the underlying topic when a client subscribes to the peer
    ``usr…`` name; we persist the canonical ``p2p…`` id for inbox mapping.
    """
    names = compute_p2p_topic_names(tinode_uid_a, tinode_uid_b)
    trusted = {
        "paripath_connection_id": connection_id,
        "peer_display_name": peer_display_name or "",
    }
    reachable = await check_grpc_reachable()
    if settings.tinode.grpc_required and not reachable:
        raise TinodeGrpcError("Tinode gRPC endpoint is not reachable")
    return P2pProvisionResult(
        names=names,
        grpc_reachable=reachable,
        trusted_public=trusted,
    )


def trusted_public_json(result: P2pProvisionResult) -> str:
    """Serialize trusted public metadata for storage in topic aux if needed."""
    return json.dumps(result.trusted_public)
