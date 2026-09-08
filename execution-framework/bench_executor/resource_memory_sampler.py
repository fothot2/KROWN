#!/usr/bin/env python3
"""Sample current process-tree RSS across named benchmark phases."""
from __future__ import annotations

import dataclasses
import threading
from collections.abc import Callable
from typing import Any


@dataclasses.dataclass
class _PhaseMemory:
    first_rss_bytes: int | None = None
    last_rss_bytes: int | None = None
    peak_rss_bytes: int | None = None
    sample_count: int = 0

    def add(self, value: int) -> None:
        if self.first_rss_bytes is None:
            self.first_rss_bytes = value
        self.last_rss_bytes = value
        self.peak_rss_bytes = value if self.peak_rss_bytes is None else max(
            self.peak_rss_bytes, value
        )
        self.sample_count += 1

    def to_dict(self) -> dict[str, int | None]:
        return dataclasses.asdict(self)


class PhaseAwareMemorySampler:
    """Sample one non-negative RSS probe without blocking benchmark work."""

    def __init__(
        self,
        probe: Callable[[], int | None],
        scope: str,
        interval_s: float = 0.01,
    ) -> None:
        if not callable(probe):
            raise TypeError('probe must be callable')
        if not isinstance(scope, str) or not scope:
            raise ValueError('scope must be a non-empty string')
        if interval_s <= 0:
            raise ValueError('interval_s must be greater than zero')
        self._probe = probe
        self._scope = scope
        self._interval_s = interval_s
        self._phase = 'pre_open'
        self._phases: dict[str, _PhaseMemory] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError('memory sampler is already started')
        self._sample()
        self._thread = threading.Thread(
            target=self._run, name='krown-rdf-memory-sampler', daemon=True
        )
        self._thread.start()

    def set_phase(self, phase: str) -> None:
        if not isinstance(phase, str) or not phase:
            raise ValueError('phase must be a non-empty string')
        with self._lock:
            self._phase = phase
        self._sample()

    def _sample(self) -> None:
        try:
            value = self._probe()
            if value is None:
                return
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError('memory probe must return non-negative bytes or None')
            with self._lock:
                self._phases.setdefault(self._phase, _PhaseMemory()).add(value)
        except (OSError, RuntimeError, TypeError, ValueError):
            with self._lock:
                self._errors += 1

    def _run(self) -> None:
        while not self._stop.wait(self._interval_s):
            self._sample()

    def _snapshot(self, *, sample: bool) -> dict[str, Any]:
        if sample:
            self._sample()
        with self._lock:
            phases = {
                name: value.to_dict()
                for name, value in self._phases.items()
            }
            errors = self._errors
        peaks = [value['peak_rss_bytes'] for value in phases.values()]
        peaks = [value for value in peaks if value is not None]
        return {
            'schema': 'rdf-phase-memory-metrics-v1',
            'scope': self._scope,
            'unit': 'bytes',
            'sampling_interval_ms': self._interval_s * 1000,
            'sample_errors': errors,
            'sample_count': sum(
                value['sample_count'] for value in phases.values()
            ),
            'peak_rss_bytes': max(peaks) if peaks else None,
            'phases': phases,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return a consistent copy without stopping the sampler."""
        if self._thread is None:
            raise RuntimeError('memory sampler is not started')
        return self._snapshot(sample=True)

    def stop(self) -> dict[str, Any]:
        thread = self._thread
        if thread is None:
            raise RuntimeError('memory sampler is not started')
        self._stop.set()
        thread.join(timeout=max(1.0, self._interval_s * 10))
        if thread.is_alive():
            raise RuntimeError('memory sampler thread did not stop')
        return self._snapshot(sample=False)
