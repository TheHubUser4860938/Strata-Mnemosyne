#!/usr/bin/env python3
"""Coalescing idle-queue for the curation sweep.

Why (the shape is Hermes' agent/review_idle_queue.py:1-13): on one GPU the
background drain competes with the live turn. Hermes' answer is not "wait for
silence then start", it is a SLOT:

  * one slot per key, newest snapshot wins - a review replays the whole
    conversation, so coalescing is dedup, not loss;
  * idle truth is a SETTLE window, not the instant of quiet - two back-to-back
    prompts must not look idle, a coffee break must;
  * an aged item dispatches regardless of idleness, so a busy day drains
    eventually instead of starving;
  * best-effort: a queue that cannot be read is an empty queue, never a crash.

The sweep's 2026-10-16 gate (240 s of TOTAL engine silence) stays the law for
starting a batch. This module decides WHICH work is handed to the next batch,
so ten timer ticks that all want a drain cost one drain.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

SETTLE_S = 15.0          # quiet long enough to be worth starting: two back-to-back prompts must not qualify
POLL_S = 5.0             # caller's poll cadence while the queue is non-empty
MAX_AGE_S = 30 * 60.0    # dispatch regardless of idleness past this age


class IdleQueue:
    """One slot per key, newest payload wins, age measured from the first submit."""

    def __init__(self, path, settle: float = SETTLE_S, max_age: float = MAX_AGE_S,
                 clock: float = time.monotonic, wall=None):
        self.path = Path(path)
        self.settle = float(settle)
        self.max_age = float(max_age)
        self.clock = clock
        self.wall = wall or (lambda: time.time())
        self._slots: dict[str, dict] = {}
        self._seq = 0
        self._load()

    # -- persistence ---------------------------------------------------------
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            slots = raw.get("slots") or {}
            self._seq = int(raw.get("seq") or 0)
            self._slots = {str(k): v for k, v in slots.items()
                           if isinstance(v, dict) and "payload" in v}
        except (OSError, ValueError, AttributeError):
            self._slots, self._seq = {}, 0          # a corrupt queue is an empty queue

    def flush(self) -> None:
        """Atomic write: temp + rename, so a reader never sees half a queue."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".q_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"seq": self._seq, "saved_at": self.wall(), "slots": self._slots}, fh)
            os.replace(tmp, self.path)
        except OSError:
            pass                                     # best-effort, like the fork it serves

    # -- the queue -----------------------------------------------------------
    def submit(self, key: str, payload) -> dict:
        """Take the newest snapshot for a key. A second submit is dedup, not a queue."""
        key = str(key)
        self._seq += 1
        prior = self._slots.get(key)
        slot = {
            "payload": payload,
            "first_at": (prior or {}).get("first_at", self.wall()),
            "at": self.wall(),
            "seq": self._seq,
        }
        self._slots[key] = slot
        self.flush()
        return slot

    def pending(self) -> int:
        return len(self._slots)

    def snapshot(self) -> list[dict]:
        """Every slot, oldest-submission first: an aged job goes before a fresh one."""
        return sorted(
            ({"key": k, **v} for k, v in self._slots.items()),
            key=lambda r: (r.get("first_at", 0), r.get("seq", 0)),
        )

    def due(self, quiet_for: float | None = None, now: float | None = None) -> list[dict]:
        """Slots worth dispatching: settled-quiet, or aged out of the quiet gate.

        `quiet_for` is seconds of engine silence measured by the caller (the
        sweep reads the server's own activity.last_request_at). None means
        "unknown / engine free", which always dispatches.
        """
        out = []
        now = self.wall() if now is None else now
        for row in self.snapshot():
            age = max(0.0, now - float(row.get("first_at", now)))
            if quiet_for is None or quiet_for >= self.settle or age >= self.max_age:
                out.append(row)
        return out

    def take(self, key: str) -> dict | None:
        slot = self._slots.pop(str(key), None)
        if slot is not None:
            self.flush()
        return slot

    def clear(self) -> int:
        n = len(self._slots)
        self._slots = {}
        self.flush()
        return n
