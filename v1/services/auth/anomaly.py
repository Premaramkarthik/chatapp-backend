"""Lightweight auth anomaly classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AuthRiskLevel(StrEnum):
    """Risk level for auth anomaly signals."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class AuthAnomaly:
    """An auth anomaly signal."""

    name: str
    level: AuthRiskLevel
    detail: str


def classify_refresh_failure(*, failure_count: int) -> AuthAnomaly | None:
    """Classify excessive refresh failures."""
    if failure_count >= 10:
        return AuthAnomaly(
            name="excessive_refresh_failures",
            level=AuthRiskLevel.HIGH,
            detail="Refresh failures exceeded high-risk threshold.",
        )
    if failure_count >= 3:
        return AuthAnomaly(
            name="excessive_refresh_failures",
            level=AuthRiskLevel.MEDIUM,
            detail="Refresh failures exceeded medium-risk threshold.",
        )
    return None


def classify_device_change(*, known_device: bool) -> AuthAnomaly | None:
    """Classify suspicious device changes."""
    if known_device:
        return None
    return AuthAnomaly(
        name="suspicious_device_change",
        level=AuthRiskLevel.LOW,
        detail="User authenticated from a new device fingerprint.",
    )
