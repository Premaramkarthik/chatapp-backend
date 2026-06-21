"""Dramatiq Redis broker configuration."""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from core.config.settings import settings

broker = RedisBroker(url=settings.redis.url)
dramatiq.set_broker(broker)
