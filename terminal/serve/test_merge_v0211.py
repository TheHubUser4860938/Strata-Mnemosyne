"""The v0.2.11 merge audit's fixes, pinned (2026-11-06).

    python -m unittest serve.test_merge_v0211

Six findings from the audit of the merge (the serve suite was green through all of them -
these are the bugs the tests did not reach):

F1  a prefill-only image request lost the flag on the embedding branch;
F2  the prefill head dropped the sampling keys, so a graft staged for it was never consulted;
F4  the batched path sent BGEN with graft=1 and staged nothing: the admission read the
    file the PREVIOUS graft had staged (the engine stages one file for the next request);
F5  stage_graft wrote the pipe around the write lock - on a --parallel engine a GRAFT
    line could splice into the middle of another request's GEN line;
F12 a solo-phase quarantine (DONE) handed off the control lines but left the slot's own
    record standing: the Monitor showed a phantom, the LRU saw a stale timestamp;
F13 the #3961 end-event guard lived only on the OpenAI route - the Anthropic and
    Responses routes kept the silent-200-with-no-finish-reason;
F14 one unparseable STRATA_STREAM_WRITE_TIMEOUT_S made every route unimportable.
"""
import os
import queue
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import serve.server as server  # noqa: E402
from serve.server import StrataEngine, anthropic_events  # noqa: E402


class Pipe:
    def __init__(self, echo_lines=False):
        self.written, self.flushes = [], 0
        self.echo = echo_lines

    def write(self, s):
        self.written.append(s)

    def flush(self):
        self.flushes += 1


class Proc:
    def __init__(self, echo_lines=False):
        self.stdin, self.returncode = Pipe(echo_lines), None

    def poll(self):
        return None


def harness(**over):
    """A StrataEngine built by hand: the attributes the solo path touches, nothing more."""
    e = StrataEngine.__new__(StrataEngine)
    e.proc, e.silence_s, e.lines, e.ended = Proc(), 0.0, queue.Queue(), False
    e.silent_note, e.gen, e.wlock = None, 1, threading.Lock()
    e.progress, e.progress_ms, e.reused, e.last = None, 0, 0, None
    e.lp_lines, e.batch, e.multi = [], 0, False
    e.split, e.split_prefill, e.parallel = None, 0, 0
    e.__dict__.update(over)
    return e


class PrefillWire(unittest.TestCase):
    """F1, F2, F5: the solo wire - what a prefill-only request sends, keys and all."""

    def drive(self, sampling, **kw):
        e = harness()
        e.lines.put("GRAFTED 41061 780000000 91.4")            # stage_graft's answer, consumed before GEN
        e.lines.put("DONE 0 3 1.0 1.0 stop")
        list(e.generate([1, 2, 3], 0, sampling, threading.Event(), **kw))
        return [w.strip() for w in e.proc.stdin.written]

    def test_the_prefill_head_keeps_the_sampling_keys(self):
        # F2: graft=1 (and every other key) must ride the prefill head - the engine consults
        # the staged file only when the GEN line says to
        lines = self.drive({"strata_graft": "/vault/parent.bin", "temperature": 0.7}, prefill_only=True)
        self.assertEqual(lines[0], "GRAFT /vault/parent.bin", "F5: the graft goes first, through the lock")
        self.assertTrue(lines[1].startswith("GEN 0 prefill=1"), lines[1])
        self.assertIn("graft=1", lines[1], "F2: a prefill-only request that staged a graft says so on the wire")
        self.assertIn("temperature=0.7", lines[1], "the keys are the request's own, not a fixed set")

    def test_the_image_branch_keeps_prefill_only(self):
        # F1: embeddings used to be the branch that forgot the flag
        e = harness()
        e.lines.put("DONE 0 3 1.0 1.0 stop")
        list(e.generate([1, 2, 3], 0, {}, threading.Event(), embeddings="1,2,3", prefill_only=True))
        sent = [w.strip() for w in e.proc.stdin.written]
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("GENI 0"), sent[0])
        self.assertIn("prefill=1", sent[0], "F1: an embedding pass is still a prefill-only pass")

    def test_a_plain_gen_line_is_unchanged(self):
        # the byte-identical law: no graft, no prefill - the wire says what it always said
        lines = self.drive({"temperature": 0.5})
        self.assertEqual(lines, ["GEN 0 temperature=0.5 1,2,3"])


class SendLines(unittest.TestCase):
    """F4's mechanism: GRAFT and BGEN as one lock acquisition, one flush."""

    def test_the_pair_writes_two_lines_under_one_lock(self):
        e = harness()
        e._send_lines("GRAFT /vault/parent.bin", "BGEN 0 8 graft=1 1,2,3")
        self.assertEqual(e.proc.stdin.written, ["GRAFT /vault/parent.bin\n", "BGEN 0 8 graft=1 1,2,3\n"])
        self.assertEqual(e.proc.stdin.flushes, 1, "one flush: no other writer can land between the lines")

    def test_the_batched_admission_sends_the_pair_when_grafted(self):
        # the contract, pinned where it is written: a grafted admission stages its OWN file
        src = Path(__file__).with_name("server.py").read_text(encoding="utf-8")
        start = src.index("def generate_batched")
        body = src[start:src.index("\n    def ", start + 10)]
        self.assertIn('strata_graft', body, "the batched path must know the graft key")
        self.assertIn('_send_lines(f"GRAFT', body, "and stage it atomically with the BGEN that consumes it")

    def test_the_solo_graft_write_takes_the_lock(self):
        # F5: the solo path keeps its FIFO turn, and now the write lock too
        e = harness()
        e.lines.put("GRAFTED 5 100 1.0")
        got = e.stage_graft("/vault/parent.bin")
        self.assertEqual(e.proc.stdin.written, ["GRAFT /vault/parent.bin\n"])
        self.assertEqual(got["tokens"], 5, "the answer is still the engine's own numbers")


class EndEventGuard(unittest.TestCase):
    """F13: the #3961 guard on the Anthropic and Responses routes."""

    class StubEngine:
        gen, alive = 1, True

    class StubSvc:
        def __init__(self):
            self.engine, self.ended_with = EndEventGuard.StubEngine(), None

        def model_for(self, req):
            return "stub-model"

        def end_engine_if_unchanged(self, born):
            self.ended_with = born
            return True

    def test_the_anthropic_stream_that_never_ended_is_an_error(self):
        svc = self.StubSvc()
        run = iter([("event", server.Event("content", "hi"))])        # tokens, then the loop ends: no "done"
        g = anthropic_events(svc, {}, [1], None, None, 8, threading.Event(), run=run)
        self.assertEqual(next(g)[0], "message_start")                  # the stream opens as always...
        with self.assertRaises(server.EngineDied):
            list(g)                                                    # ...and ends as an error

    def test_the_guard_ends_the_engine_that_ran_it(self):
        svc = self.StubSvc()
        g = anthropic_events(svc, {}, [1], None, None, 8, threading.Event(),
                             run=iter([("event", server.Event("content", "hi"))]))
        with self.assertRaises(server.EngineDied) as cm:
            list(g)
        self.assertTrue(cm.exception.restarts, "the note says the next request restarts it, so it must")
        self.assertEqual(svc.ended_with, 1, "and it ends THAT process, not whatever answers now")

    def test_the_responses_route_got_the_same_guard(self):
        src = Path(__file__).with_name("server.py").read_text(encoding="utf-8")
        start = src.index("def events():")
        end = src.index("items = self._capture(events()", start)
        body = src[start:end]
        self.assertIn("if done is None and not cancel.is_set()", body,
                      "F13: a responses stream that stopped without its done event is an error too")
        self.assertIn("end_engine_if_unchanged(born)", body, "and it ends the process that ran it")


class ImportRobustness(unittest.TestCase):
    """F14: one unparseable env value is a streaming timeout, not a dead server."""

    def test_a_stray_unit_still_leaves_a_timeout(self):
        # read through the function, not a module reload: the suite shares this module's classes
        import unittest.mock as mock
        with mock.patch.dict(os.environ, {"STRATA_STREAM_WRITE_TIMEOUT_S": "60s"}):
            self.assertEqual(server._stream_write_timeout(), 60.0)
        with mock.patch.dict(os.environ, {"STRATA_STREAM_WRITE_TIMEOUT_S": "30"}):
            self.assertEqual(server._stream_write_timeout(), 30.0)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server._stream_write_timeout(), 60.0)


class QuarantineBookkeeping(unittest.TestCase):
    """F12: the DONE quarantine frees the slot's RECORD (busy is BDONE's job)."""

    def test_the_done_quarantine_clears_the_slot_record(self):
        src = Path(__file__).with_name("server.py").read_text(encoding="utf-8")
        start = src.index("def generate_batched")
        body = src[start:src.index("\n    def ", start + 10)]
        i = body.index('self._quarantine_control(undrained, born, lines_q, slot if undrained == "BADM" else None, holding)')
        tail = body[i:i + 900]
        self.assertIn('if slot is not None and undrained == "DONE" and same:', tail,
                      "F12: the DONE branch of the quarantine refreshes the slot's own record")
        self.assertIn("self.slot_live[slot] = None", tail)
        self.assertIn("self.slot_used[slot] = time.time()", tail)


if __name__ == "__main__":
    unittest.main()
