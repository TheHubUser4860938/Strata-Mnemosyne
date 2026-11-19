#!/usr/bin/env python3
"""The idle-queue contract: one slot per key, newest wins, age beats quiet.

Run: python3 -m unittest tools.test_curate_idle -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from idle_queue import IdleQueue  # noqa: E402


class Clock:
    """A wall clock the test drives, so no test sleeps."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def q(dirpath, settle=15.0, max_age=1800.0, clock=None):
    return IdleQueue(Path(dirpath) / "queue.json", settle=settle, max_age=max_age,
                     clock=clock or (lambda: 0.0), wall=clock)


class TestCoalescing(unittest.TestCase):
    def test_newest_snapshot_wins(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, clock=c)
            k.submit("drain", {"turns": 120})
            c.advance(5)
            k.submit("drain", {"turns": 340})
            due = k.due(quiet_for=60)
            self.assertEqual(len(due), 1, "two submits are one job")
            self.assertEqual(due[0]["payload"], {"turns": 340})

    def test_keys_are_independent_slots(self):
        with tempfile.TemporaryDirectory() as d:
            k = q(d, clock=Clock(1000.0))
            k.submit("drain", 1)
            k.submit("curate", 2)
            self.assertEqual(k.pending(), 2)
            self.assertEqual({r["key"] for r in k.due(quiet_for=60)}, {"drain", "curate"})

    def test_oldest_submission_dispatches_first(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, clock=c)
            k.submit("b", 1)
            c.advance(100)
            k.submit("a", 2)
            self.assertEqual([r["key"] for r in k.snapshot()], ["b", "a"])

    def test_first_at_survives_a_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, max_age=50.0, clock=c)
            k.submit("drain", 1)
            c.advance(40)
            k.submit("drain", 2)          # fresh payload, old age
            c.advance(15)
            due = k.due(quiet_for=0)      # engine busy: only age can free it
            self.assertEqual([r["key"] for r in due], ["drain"], "age is measured from the FIRST submit")


class TestIdleGate(unittest.TestCase):
    def test_quiet_below_the_settle_window_waits(self):
        with tempfile.TemporaryDirectory() as d:
            k = q(d, settle=15.0, clock=Clock(1000.0))
            k.submit("drain", 1)
            self.assertEqual(k.due(quiet_for=14.9), [])
            self.assertEqual(len(k.due(quiet_for=15.0)), 1)

    def test_none_quiet_means_the_engine_is_free(self):
        with tempfile.TemporaryDirectory() as d:
            k = q(d, clock=Clock(1000.0))
            k.submit("drain", 1)
            self.assertEqual(len(k.due(None)), 1)

    def test_aged_items_dispatch_through_a_busy_spell(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, settle=15.0, max_age=60.0, clock=c)
            k.submit("drain", 1)
            self.assertEqual(k.due(quiet_for=0), [])
            c.advance(61)
            self.assertEqual(len(k.due(quiet_for=0)), 1, "a busy day must still drain")

    def test_take_removes_the_slot(self):
        with tempfile.TemporaryDirectory() as d:
            k = q(d, clock=Clock(1000.0))
            k.submit("drain", {"n": 3})
            got = k.take("drain")
            self.assertEqual(got["payload"], {"n": 3})
            self.assertEqual(k.pending(), 0)
            self.assertIsNone(k.take("drain"))
            self.assertEqual(k.due(quiet_for=99), [])


class TestPersistence(unittest.TestCase):
    def test_a_slot_survives_a_new_process(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            a = q(d, clock=c)
            a.submit("drain", {"turns": 5})
            b = q(d, clock=c)                     # the next systemd tick
            due = b.due(quiet_for=60)
            self.assertEqual(len(due), 1)
            self.assertEqual(due[0]["payload"], {"turns": 5})
            self.assertEqual(b._seq, 1, "the sequence continues across processes")

    def test_a_corrupt_queue_is_an_empty_queue_not_a_crash(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "queue.json"
            p.write_text('{"slots": {"a": {"payload": 1}, "b": "not-a-slot"', encoding="utf-8")
            k = q(d, clock=Clock(1000.0))
            self.assertEqual(k.pending(), 0)
            k.submit("drain", 1)                  # and it is usable afterwards
            self.assertEqual(k.pending(), 1)

    def test_an_unwritable_store_never_breaks_a_drain(self):
        with tempfile.TemporaryDirectory() as d:
            k = IdleQueue(Path(d) / "nope" / "deep" / "queue.json", clock=Clock(1000.0), wall=Clock(1000.0))
            k.submit("drain", 1)                   # mkdirs on flush
            self.assertEqual(len(k.due(quiet_for=60)), 1)
            blocker = Path(d) / "blocked"
            blocker.write_text("file, not dir", encoding="utf-8")
            k2 = IdleQueue(blocker / "q.json", clock=Clock(1000.0), wall=Clock(1000.0))
            k2.submit("drain", 1)                  # flush must swallow the OSError
            self.assertEqual(k2.pending(), 1)

    def test_the_file_is_valid_json_at_every_step(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, clock=c)
            for i in range(20):
                c.advance(1)
                k.submit(f"k{i % 3}", i)
                json.loads((Path(d) / "queue.json").read_text())   # no torn reads
            self.assertEqual(k.pending(), 3)


class TestKeys(unittest.TestCase):
    def test_odd_keys_are_stringified_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            k = q(d, clock=Clock(1000.0))
            for bad in (7, ("a",), None, Path("/tmp/x")):
                k.submit(bad, 1)
            self.assertEqual(k.pending(), 4)
            self.assertIsNotNone(k.take("7"))


class TestSabotage(unittest.TestCase):
    """Each sabotage bites at least one test - a green suite that passes for
    the wrong reason is not evidence."""

    def test_coalescing_is_replacement_not_accumulation(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, clock=c)
            k.submit("drain", 1)
            k.submit("drain", 2)
            self.assertEqual(k.pending(), 1)
            self.assertEqual(k.due(quiet_for=60)[0]["payload"], 2)

    def test_age_is_not_measured_from_the_last_touch(self):
        with tempfile.TemporaryDirectory() as d:
            c = Clock(1000.0)
            k = q(d, max_age=50.0, clock=c)
            k.submit("drain", 1)
            c.advance(49)
            k.submit("drain", 2)
            c.advance(2)
            self.assertEqual(len(k.due(quiet_for=0)), 1, "a busy day must still drain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
