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
import curate_loop as C          # the law prompt and its verdict parser (2026-11-24)
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
class LawPromptCarriesTheDates(unittest.TestCase):
    """The supersession law's judge was shown two facts and no dates (2026-11-24).

    Every row carries `when` to the minute, the harvest writes a median of 6.92 h after the
    saying, and a backfill can store an old turn after a new one — so the order the model sees is
    not the order things were said. Hindsight's consolidation prompt settled the same problem by
    computing the comparison in code and handing the model a mark (29/40 to 36-38/40, no extra
    call). These tests pin the mark: both sides dated, the law sentence naming the tie-break, and
    an unknown date rendered as unknown rather than invented.
    """

    def test_both_sides_are_dated(self):
        p = C.law_prompt("The box serves 0.1.67.", 1795550000.0,
                         "The box serves 0.1.66.", 1795000000.0)
        self.assertIn("NEW (said 2026-", p)
        self.assertIn("OLD (said 2026-", p)
        self.assertLess(p.index("OLD (said"), p.index("NEW (said"),
                        "the prompt reads the other way round: NEW must be the side being stored")

    def test_the_law_sentence_uses_the_order(self):
        p = C.law_prompt("new", 1795550000.0, "old", 1795000000.0)
        self.assertIn("said LATER is the current value", p)

    def test_an_unknown_date_says_so_instead_of_inventing_one(self):
        p = C.law_prompt("new", None, "old", "")
        self.assertIn("OLD (said date unknown)", p)
        self.assertIn("NEW (said date unknown)", p)

    def test_the_verdict_vocabulary_is_the_one_the_parser_reads(self):
        """`law_verdict` scans for RESTATED / CORRECTS / DIFFERENT; a prompt that renames them
        silently sends every judgment to the DIFFERENT default."""
        p = C.law_prompt("new", 1795550000.0, "old", 1795000000.0)
        for w in ("RESTATED", "CORRECTS", "DIFFERENT"):
            self.assertIn(w, p)
            self.assertEqual(C.law_verdict(w), w)


class TheShelfVerbIsCold(unittest.TestCase):
    """The clerk's stability, measured 2026-11-24 on the label panel (`tools/m4_labelpanel.py`):
    two identical asks on the same fact and the same menu agreed 0.42-0.60 of the time at temp 0.8,
    0.88 at 0.2, 0.96 at temp 0. The blank rate moved with it (0.67 answered at 0.8, 0.92 at 0),
    which is why the blanks were never the token budget. Two contracts keep that in place: the
    clerk ASKS FOR the shelf kind, and the shelf kind is the cold one."""

    def test_the_clerk_asks_for_the_shelf_kind_so_the_verb_temp_reaches_it(self):
        seen = {}

        def ask(text, maxtok, want_geom=None, kind=""):
            seen["kind"] = kind
            seen["maxtok"] = maxtok
            return "OPS", 10, True

        self.assertEqual(clerk_class("the box runs a 4090 and 125 GB of RAM", ask), "OPS")
        self.assertEqual(seen.get("kind"), "shelf",
                         "the clerk's call is how the shelf verb gets its temperature")
        self.assertEqual(seen.get("maxtok"), 64, "the shipped decode cap")

    def test_the_shelf_verb_is_the_cold_one(self):
        self.assertIn("shelf", C.VERB_TEMP, "the verb has no temperature of its own: it is at 0.8")
        self.assertLessEqual(C.VERB_TEMP["shelf"], 0.4,
                             "measured band: agreement 0.88 at 0.2, 0.62 at 0.4, 0.42 at 0.8")
        for other in ("extract", "law", ""):
            self.assertEqual(C.VERB_TEMP.get(other, 0.8), 0.8,
                             f"{other} keeps the harvest's own temperature")


class TheBatchedClerk(unittest.TestCase):
    """Phase 4's queue (2026-11-24): N facts, ONE call. The parse is the risk, so the tests are
    the parse — a fake `ask` hands back scripted replies and the arm is judged on what it files."""

    def test_a_numbered_batch_files_every_fact_it_can_read(self):
        seen = {}

        def ask(text, maxtok, want_geom=None, kind=""):
            seen["kind"] = kind
            seen["maxtok"] = maxtok
            seen["text"] = text
            return "1: OPS\n2: USR/PREF\n3: WILD\n4: DOC/FOUNDING", 900, True

        out = C.clerk_class_batch(["the box runs a 4090", "the owner prefers short sentences",
                                   "a banana is a fruit", "madison writes federalist 10"], ask)
        self.assertEqual(out, ["OPS", "USR/PREF", "", "DOC/FOUNDING"],
                         "WILD is the shrug and it parses to the empty string")
        self.assertEqual(seen["kind"], "shelf", "the batch runs at the shelf verb's temperature")
        self.assertIn("4. madison", seen["text"], "the facts ride numbered, in order")
        self.assertGreaterEqual(seen["maxtok"], 16 * 4, "the budget scales with the batch")

    def test_a_missing_line_leaves_that_fact_wild_and_the_others_filed(self):
        def ask(text, maxtok, want_geom=None, kind=""):
            return "1: TECH\n3: MEM", 200, True

        self.assertEqual(C.clerk_class_batch(["a", "b", "c", "d"], ask), ["TECH", "", "MEM", ""],
                         "a half-parsed batch is legal: wild rides every ask, a wrong shelf hides")

    def test_prose_and_a_second_answer_for_one_row_do_not_move_it(self):
        def ask(text, maxtok, want_geom=None, kind=""):
            return "1: OPS\n  (the machine, not the number)\n1: TECH", 200, True

        self.assertEqual(C.clerk_class_batch(["the 4090 has 24 GB"], ask), ["OPS"],
                         "the first line for a row wins; a bare sentence is not an answer")

    def test_a_code_whose_top_is_not_on_the_menu_is_ignored(self):
        def ask(text, maxtok, want_geom=None, kind=""):
            return "1: ZZZ/QUUX\n2: HW", 200, True

        self.assertEqual(C.clerk_class_batch(["x", "y"], ask), ["", "HW"])

    def test_a_transport_failure_is_a_shrug_not_a_crash(self):
        def ask(text, maxtok, want_geom=None, kind=""):
            raise RuntimeError("the engine is busy")

        self.assertEqual(C.clerk_class_batch(["x", "y"], ask), ["", ""])


if __name__ == "__main__":
    unittest.main(verbosity=2)
