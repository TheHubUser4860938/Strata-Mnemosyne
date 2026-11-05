"""B4 — the cache-parity fork: a saved conversation grafts by vault name (2026-11-05).

    python -m unittest serve.test_cart_parity

A maintenance turn (a sweep, a curation ask, a digest) that re-renders the standing
texts pays full prefill. Hermes measured ~26% end-to-end by forking with a
byte-identical prefix (agent/background_review.py:979, issue #25322 / PR #17276).
This box already owns the primitive: `X-Strata-Carts-Graft` stages a vault file as
the NEXT request's start, host-side, and the engine writes no device byte — the
parent's conversation is untouched (stage_graft, server.py:3470).

Until now the header resolved only MINTED CARTS, through the ledger. The fork needs
the wider door: any conversation saved with POST /slots/0?action=save is graftable
by its vault file name. The cart law carries over one floor wider: an unknown name
marks NOTHING — additive, never a silent substitution.
"""
import os
import sys
import queue
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.server import graft_mark, StrataEngine, slot_filename_problem  # noqa: E402


class StubMemory:
    """The ledger as the seam sees it: a name answers with a row, or the ledger throws."""

    def __init__(self, rows=None, broken=False):
        self.rows, self.broken = rows or {}, broken

    def carts_get(self, name):
        if self.broken:
            raise RuntimeError("postgres is on the other boot")
        return self.rows.get(name, [])


class StubSvc:
    def __init__(self, vault, memory):
        self.slot_save_path, self.memory = vault, memory


class GraftForkTests(unittest.TestCase):
    def setUp(self):
        self.vault = tempfile.TemporaryDirectory()
        self.addCleanup(self.vault.cleanup)
        self.v = Path(self.vault.name); self.vdir = str(self.v)

    def mark(self, name, memory):
        req = {}
        graft_mark(StubSvc(self.vdir, memory), {"X-Strata-Carts-Graft": name}, req)
        return req.get("strata_graft")

    def test_a_minted_cart_still_grafts_first(self):
        (self.v / "MEM-CART-ABCDEF12.bin").write_bytes(b"state")
        mem = StubMemory({"graft": [{"file": "MEM-CART-ABCDEF12.bin", "state": "seeded"}]})
        self.assertEqual(self.mark("graft", mem), str(self.v / "MEM-CART-ABCDEF12.bin"),
                         "the ledger's cart keeps its precedence")

    def test_a_saved_conversation_grafts_by_vault_name(self):
        # THE FORK: slot 0 was saved once as parent.bin; the background ask names it.
        (self.v / "parent.bin").write_bytes(b"conversation")
        got = self.mark("parent.bin", StubMemory({}))
        self.assertEqual(got, str(self.v / "parent.bin"))
        self.assertTrue(os.path.isabs(got), "the engine is given a PATH, never a bare name (the 2026-10-29 scar)")
        self.assertEqual(os.path.dirname(got), self.vdir, "inside the slot vault, where the engine reads")

    def test_the_cart_wins_when_both_answer_the_name(self):
        (self.v / "shared.bin").write_bytes(b"conversation")
        mem = StubMemory({"shared.bin": [{"file": "MEM-CRG-99999999.bin"}]})
        (self.v / "MEM-CRG-99999999.bin").write_bytes(b"cart")
        self.assertEqual(self.mark("shared.bin", mem), str(self.v / "MEM-CRG-99999999.bin"),
                         "a cart named X grafts the cart, byte-identical to yesterday's behaviour")

    def test_unknown_names_mark_nothing(self):
        self.assertIsNone(self.mark("nope.bin", StubMemory({})), "additive, never a silent substitution")

    def test_a_broken_ledger_falls_to_the_vault(self):
        (self.v / "parent.bin").write_bytes(b"conversation")
        self.assertEqual(self.mark("parent.bin", StubMemory(broken=True)), str(self.v / "parent.bin"),
                         "the ledger is a pointer: it never kills a graft the vault can serve")

    def test_a_cart_row_naming_no_file_falls_to_the_vault(self):
        (self.v / "retired").write_bytes(b"conversation")
        mem = StubMemory({"retired": [{"file": ""}]})          # retired cart: the row lives, the file does not
        self.assertEqual(self.mark("retired", mem), str(self.v / "retired"))

    def test_a_name_with_separators_marks_nothing(self):
        (self.v / "in.bin").write_bytes(b"x")
        os.makedirs(self.v / "sub", exist_ok=True)
        (self.v / "sub" / "deep.bin").write_bytes(b"x")
        self.assertIsNone(self.mark("sub/deep.bin", StubMemory({})), "one plain file name, the slot law")
        self.assertIsNone(self.mark("", StubMemory({})), "an empty header marks nothing")
        self.assertIsNone(slot_filename_problem("parent.bin"), "and the validator agrees the fork's name is plain")

    def test_no_vault_no_graft(self):
        req = {}
        graft_mark(StubSvc(None, StubMemory({})), {"X-Strata-Carts-Graft": "parent.bin"}, req)
        self.assertNotIn("strata_graft", req)

    def test_the_fork_path_rides_the_wire_verbatim(self):
        # The engine's half, one line deep: the file the fork marked is the file GRAFTed.
        path = str(self.v / "parent.bin")
        (self.v / "parent.bin").write_bytes(b"conversation")

        class Pipe:
            def __init__(self):
                self.written = []

            def write(self, s):
                self.written.append(s)

            def flush(self):
                pass

        class Proc:
            def __init__(self):
                self.stdin = Pipe()

        e = StrataEngine.__new__(StrataEngine)
        e.proc, e.silence_s, e.lines, e.ended = Proc(), 0.0, queue.Queue(), False
        e.silent_note = None
        e.lines.put("GRAFTED 41061 780000000 91.4")            # a parent's real shape: ~41k tokens of standing prefix
        got = e.stage_graft(path)
        self.assertEqual(e.proc.stdin.written, [f"GRAFT {path}\n"], "the fork's path rides the wire verbatim")
        self.assertEqual(got["tokens"], 41061, "and the staged token count is what the engine says, not what we guess")


if __name__ == "__main__":
    unittest.main()
