#!/usr/bin/env python3
"""tools/test_curate_clerk.py - the shelf clerk's contract with `ask`, standalone.

The clerk shipped 2026-11-02 13:12 (698ba298) wired into the store path as
`fact_class(...) or clerk_class(...)`, and it read `ask(...)` as a string. The `ask` in
curate_loop returns the 3-tuple `(answer, ptok, geom_ok)` (curate_loop.py:749), so the FIRST
fact the keywords left WILD and the clerk named raised:

    TypeError: expected string or bytes-like object, got 'tuple'

Because marks land per window AFTER scoring (the window law, 2026-10-24), an unmarked window
is re-drained next tick and dies on the same fact: 13 consecutive ticks re-extracted turns
8654..8713 with zero marks, and the queue grew 505 -> 1,303. The clerk only runs on the `or`
branch, which is why the ticks between 13:12 and 18:05 that day looked healthy.

Every case below is the shape the real `ask` answers with, not a shape invented for the test.

    .venv/bin/python tools/test_curate_clerk.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curate_loop import clerk_class


def fake_ask(answer, ptok=1234):
    """A muted generation that succeeds: the real return shape is (answer, ptok, geom_ok)."""
    def ask(text, maxtok, want_geom=None, kind=""):
        assert kind == "shelf", f"the clerk must ask on its own kind, got {kind!r}"
        return answer, ptok, want_geom is None
    return ask


class ClerkFilesTheFact(unittest.TestCase):
    def test_a_named_shelf_comes_back_from_the_tuple(self):
        self.assertEqual(clerk_class("The sweep drains 60 turns a window.", fake_ask("MEM")), "MEM")

    def test_a_cutter_code_comes_back_whole(self):
        self.assertEqual(clerk_class("Row 4227 lives on the founding shelf.",
                                     fake_ask("DOC/FOUNDING")), "DOC/FOUNDING")

    def test_the_last_code_wins_when_the_model_rambles(self):
        # the clerk answers "ONE line and nothing else"; a small model that adds a sentence
        # still gets its shelf, and the trailing code is the one it settled on
        self.assertEqual(clerk_class("Some fact.", fake_ask("It is MEM/CRG, so: MEM/CRG")), "MEM/CRG")


class ClerkLeavesItWild(unittest.TestCase):
    def test_transport_failure_leaves_it_wild(self):
        # the real failure shape: (None, None, False)
        self.assertEqual(clerk_class("Some fact.", fake_ask(None, ptok=None)), "")

    def test_an_unknown_top_leaves_it_wild(self):
        # a wrong shelf HIDES a fact from every filtered request; a wild shelf only waits
        self.assertEqual(clerk_class("Some fact.", fake_ask("COOKING")), "")

    def test_an_empty_answer_leaves_it_wild(self):
        self.assertEqual(clerk_class("Some fact.", fake_ask("")), "")

    def test_a_raising_ask_never_stalls_the_sweep(self):
        def boom(text, maxtok, want_geom=None, kind=""):
            raise RuntimeError("engine away")
        self.assertEqual(clerk_class("Some fact.", boom), "")

    def test_no_ask_at_all_leaves_it_wild(self):
        self.assertEqual(clerk_class("Some fact.", None), "")




class ClerkCollapsesSelfNested(unittest.TestCase):
    """The 2026-11-06 census found drawers that repeated their family: TECH/TECH, BIO/BIO.
    One drawer does not need two name tags - the cutter collapses to the family."""

    def test_a_cutter_that_repeats_its_top_collapses(self):
        self.assertEqual(clerk_class("Some fact.", fake_ask("TECH/TECH")), "TECH")

    def test_a_real_cutter_still_rides(self):
        self.assertEqual(clerk_class("Some fact.", fake_ask("TECH/PYTHO")), "TECH/PYTHO")
if __name__ == "__main__":
    unittest.main(verbosity=2)
