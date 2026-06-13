"""Progress reporting for geo sync (tqdm + throughput)."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field

from tqdm import tqdm


@dataclass
class SyncProgress:
    """Tracks elapsed time and row counts for summary output."""

    started_at: float = field(default_factory=time.perf_counter)
    countries_loaded: int = 0
    states_loaded: int = 0
    cities_loaded: int = 0
    cities_written: int = 0

    @property
    def elapsed_sec(self) -> float:
        return time.perf_counter() - self.started_at

    @property
    def rows_per_sec(self) -> float:
        total = self.countries_loaded + self.states_loaded + self.cities_written
        elapsed = self.elapsed_sec
        if elapsed <= 0:
            return 0.0
        return total / elapsed


class ProgressReporter:
    """Wraps tqdm bars for SDK load and DB write phases."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled

    def country_bar(self, total: int) -> tqdm:
        return tqdm(
            total=total,
            desc="Countries ",
            unit="row",
            disable=not self._enabled,
            file=sys.stdout,
            leave=True,
            bar_format="{desc}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        )

    def state_bar(self, total: int | None = None) -> tqdm:
        return tqdm(
            total=total,
            desc="States    ",
            unit="row",
            disable=not self._enabled,
            file=sys.stdout,
            leave=True,
            bar_format="{desc}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        )

    def city_load_bar(self) -> tqdm:
        return tqdm(
            desc="Cities    ",
            unit="row",
            disable=not self._enabled,
            file=sys.stdout,
            leave=True,
            bar_format="{desc}{bar}| {n_fmt} [{elapsed}, {rate_fmt}]",
        )

    def city_write_bar(self, total: int) -> tqdm:
        return tqdm(
            total=total,
            desc="Cities    ",
            unit="row",
            disable=not self._enabled,
            file=sys.stdout,
            leave=True,
            bar_format="{desc}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
        )

    @staticmethod
    def print_summary(
        *,
        countries: int,
        states: int,
        cities: int,
        duration_sec: float,
        redis_flushed: bool,
        redis_keys_deleted: int,
    ) -> None:
        """Print final sync summary block."""
        print()
        print("Countries Synced :", countries)
        print("States Synced    :", states)
        print("Cities Synced    :", cities)
        print(f"Duration         : {duration_sec:.1f}s")
        if redis_flushed:
            print(f"Redis Flushed    : Yes ({redis_keys_deleted} keys)")
        else:
            print("Redis Flushed    : No")
        print("-" * 22)
