#!/usr/bin/env python3
"""The batch contract: validate the whole plan, apply in order, roll back as one.

Run: python3 -m unittest tools.test_curate_batch -v

No engine needed: `post` is injected, so every test drives the wire shape
directly and the fakes record what a real server would have received.
"""
from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_batch import CEILING, apply_operations, plan  # noqa: E402


class FakeServer:
    """A stand-in for POST /memory, shaped by the real route (server.py:10241-10252):
    remember lands a row, correct lands a NEW row that supersedes one,
    invalidate takes a row out of recall and keeps the history."""

    def __init__(self, fail_at=None, status=500, error="shelf locked"):
        self.calls: list[dict] = []
        self.retired: list[int] = []      # invalidate calls, in the order they landed
        self.supersede: list[tuple] = []  # (new_id, old_id)
        self.fail_at = fail_at            # index of the call that fails
        self.status = status
        self.error = error
        self._next = 900

    def __call__(self, body):
        i = len(self.calls)
        self.calls.append(body)
        if self.fail_at == i:
            if self.status == 0:
                raise urllib.error.URLError("connection reset by peer")
            return self.status, {"error": self.error}
        if body["op"] == "invalidate":
            self.retired.append(body["id"])
            return 200, {"ok": True, "invalidated": True, "id": body["id"]}
        self._next += 1
        # a real server answers bare: {"ok": true, "id": <the row it wrote>, ...}
        # and a correct names the row it superseded (memory.py:1840 correct())
        answer = {"ok": True, "id": self._next, "deduped": False}
        if body["op"] == "correct":
            self.supersede.append((self._next, body["id"]))
            answer["invalidated"] = body["id"]
        return 200, answer


class TestPlan(unittest.TestCase):
    def test_the_ceiling_is_measured_on_the_final_normalized_text(self):
        # the receipt's point: whitespace is collapsed BEFORE the budget is judged
        text = "one\n\n  two   " + "x" * (CEILING - 12)
        ops = plan([{"action": "add", "text": text}])
        self.assertLessEqual(len(ops[0]["text"]), CEILING)
        self.assertEqual(ops[0]["text"], "one two " + "x" * (CEILING - 12))

    def test_an_over_budget_add_is_refused_before_anything_is_written(self):
        srv = FakeServer()
        with self.assertRaises(ValueError) as cm:
            apply_operations([{"action": "add", "text": "y" * (CEILING + 1)}], srv)
        self.assertIn(f"{CEILING}-char row ceiling", str(cm.exception))
        self.assertEqual(srv.calls, [], "a refused plan costs zero round trips")

    def test_the_refusal_names_the_op_and_asks_for_one_batch(self):
        with self.assertRaises(ValueError) as cm:
            plan([{"action": "add", "text": "small"}, {"action": "add", "text": "z" * 4001}])
        msg = str(cm.exception)
        self.assertIn("op 1", msg)
        self.assertIn("one call", msg)

    def test_actions_and_required_fields_are_checked(self):
        for bad in (
            [{"action": "delete", "text": "x"}],
            [{"action": "add", "text": "   "}],
            [{"action": "amend", "text": "x"}],           # no id
            [{"action": "retire"}],                        # no id
            [],
        ):
            with self.assertRaises(ValueError):
                plan(bad)

    def test_a_non_object_op_is_a_plan_error(self):
        with self.assertRaises(ValueError):
            plan(["just a string"])


class TestApply(unittest.TestCase):
    def test_a_clean_batch_lands_in_order_and_reports_the_ids(self):
        srv = FakeServer()
        r = apply_operations(
            [
                {"action": "retire", "id": 12},
                {"action": "add", "text": "the clerk lives in curate_loop.py", "klass": "TECH/CLERK"},
                {"action": "amend", "id": 44, "text": "the shelf ceiling is 4000 chars"},
            ],
            srv,
            source="curate",
        )
        self.assertEqual(r["ok"], True)
        self.assertEqual(r["applied"], 3)
        self.assertEqual(r["rolled_back"], False)
        self.assertEqual([c["op"] for c in srv.calls], ["invalidate", "remember", "correct"])
        self.assertEqual(srv.calls[1]["class"], "TECH/CLERK", "the wire key is class, not klass")
        self.assertEqual(srv.calls[2]["id"], 44, "a correct names the row it supersedes")
        self.assertEqual(srv.supersede, [(902, 44)], "the correction lands as a new row on the chain")
        self.assertEqual(len(r["ids"]), 2, "a retire has no new row to report")
        self.assertEqual(len(r["receipts"]), 3, "every op's answer rides the result")
        self.assertEqual(r["receipts"][2]["invalidated"], 44,
                         "a clerk can see what a correction superseded without a second call")

    def test_the_first_failure_retires_what_landed_in_reverse_order(self):
        srv = FakeServer(fail_at=2)
        r = apply_operations(
            [
                {"action": "add", "text": "first fact"},
                {"action": "add", "text": "second fact"},
                {"action": "add", "text": "third fact"},
            ],
            srv,
        )
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["failed_index"], 2, "the failing op is identified")
        self.assertEqual(r["applied"], 0)
        self.assertEqual(r["rolled_back"], True)
        self.assertEqual(srv.retired, [902, 901], "newest first, and only the adds")
        self.assertEqual(r["retired"], [902, 901])

    def test_a_transport_failure_rolls_back_the_same_way(self):
        srv = FakeServer(fail_at=1, status=0)
        r = apply_operations([{"action": "add", "text": "a"}, {"action": "add", "text": "b"}], srv)
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["failed_index"], 1)
        self.assertIn("transport: URLError", r["error"])
        self.assertEqual(srv.retired, [901], "the op that landed is retired, not deleted")

    def test_a_500_response_is_a_failure_with_the_servers_message(self):
        srv = FakeServer(fail_at=0, status=500, error="deadlock detected")
        r = apply_operations([{"action": "add", "text": "a"}, {"action": "add", "text": "b"}], srv)
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["failed_index"], 0)
        self.assertIn("deadlock detected", r["error"])
        self.assertEqual(srv.retired, [], "nothing landed, so nothing to undo")

    def test_a_failing_rollback_does_not_swallow_the_original_error(self):
        class HalfDead(FakeServer):
            def __call__(self, body):
                if body["op"] == "invalidate":
                    raise RuntimeError("the port is down")
                return super().__call__(body)

        srv = HalfDead(fail_at=1)
        r = apply_operations([{"action": "add", "text": "a"}, {"action": "add", "text": "b"}], srv)
        self.assertEqual(r["ok"], False)
        self.assertIn("op 1 add", r["error"], "the cause is reported, not the rollback's complaint")
        self.assertEqual(r["retired"], [], "a rollback that fails is reported as such")

    def test_scopes_and_provenance_ride_the_wire(self):
        srv = FakeServer()
        apply_operations(
            [{"action": "add", "text": "the venue box is a separate store",
              "scope": "venue", "klass": "OPS/BOX", "provenance": {"corpus": "harness"}}],
            srv,
        )
        self.assertEqual(srv.calls[0]["scope"], "venue")
        self.assertEqual(srv.calls[0]["provenance"], {"corpus": "harness"})

    def test_the_source_is_stamped_on_every_write(self):
        srv = FakeServer()
        apply_operations([{"action": "add", "text": "a"}, {"action": "amend", "id": 5, "text": "b"}],
                         srv, source="clerk")
        self.assertEqual([c["source"] for c in srv.calls], ["clerk", "clerk"])

    def test_a_retire_op_is_not_double_undone(self):
        srv = FakeServer(fail_at=1)
        r = apply_operations([{"action": "retire", "id": 77}, {"action": "add", "text": "b"}], srv)
        self.assertEqual(r["ok"], False)
        self.assertEqual(srv.retired, [77], "one retire call, and it is the original op")

    def test_an_amend_rolls_back_to_the_text_it_replaced(self):
        srv = FakeServer(fail_at=1)
        r = apply_operations(
            [{"action": "amend", "id": 44, "text": "the new wording", "prev_text": "the old wording"},
             {"action": "add", "text": "boom"}],
            srv,
        )
        self.assertEqual(r["ok"], False)
        undo = srv.calls[-1]
        self.assertEqual(undo["op"], "correct")
        self.assertEqual(undo["id"], 901, "the undo supersedes the correction, not the original row")
        self.assertEqual(undo["text"], "the old wording", "the bytes that were replaced come back")
        self.assertEqual(undo["source"], "batch-rollback", "the undo is stamped as one")
        self.assertEqual(srv.supersede, [(901, 44), (902, 901)], "the chain grows by one honest link")

    def test_an_amend_without_prev_text_leaves_the_new_row_standing(self):
        srv = FakeServer(fail_at=1)
        r = apply_operations([{"action": "amend", "id": 44, "text": "new"}, {"action": "add", "text": "x"}], srv)
        self.assertEqual(r["ok"], False)
        self.assertEqual(r["retired"], [], "the honest limit: nothing to restore to")
        self.assertEqual(srv.supersede, [(901, 44)], "the correction stands on the chain")


class TestSabotage(unittest.TestCase):
    """Each sabotage must bite: a green suite that passes for the wrong reason
    is not evidence."""

    def test_the_plan_is_validated_whole_before_the_first_write(self):
        # a per-op validator that wrote as it went would issue one call before the
        # second op's ceiling error surfaced
        srv = FakeServer()
        with self.assertRaises(ValueError):
            apply_operations([{"action": "add", "text": "ok"},
                              {"action": "add", "text": "w" * (CEILING + 5)}], srv)
        self.assertEqual(len(srv.calls), 0)

    def test_rollback_order_is_newest_first(self):
        srv = FakeServer(fail_at=3)
        ops = [{"action": "add", "text": t} for t in ("a", "b", "c")]
        ops.append({"action": "add", "text": "d"})   # this one fails
        ops.append({"action": "add", "text": "e"})   # never reached
        r = apply_operations(ops, srv)
        self.assertEqual(r["failed_index"], 3)
        self.assertEqual(srv.retired, [903, 902, 901], "the last write is the first undone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
