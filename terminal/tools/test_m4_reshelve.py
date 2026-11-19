#!/usr/bin/env python3
"""tools/test_m4_reshelve.py - the clerk's naming law, standalone.

The 2026-11-06 census: the store grew drawers that were one shelf wearing two names -
TECH/TECH (self-nested), USR/PREFE beside USR/PREF and MEM/QWEN beside MEM/QWEN3
(truncation collisions). The batch clerk files by `_one(code, known)`; these are the
three naming rules it owes, each with the shelf list the census produced.

    .venv/bin/python tools/test_m4_reshelve.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m4_reshelve import _one

MENU = {"TECH", "TECH/PYTHO", "USR/PREF", "MEM/QWEN3", "OPS", "OPS/STATE"}


class SelfNested(unittest.TestCase):
    def test_a_cutter_repeating_its_top_collapses(self):
        self.assertEqual(_one("TECH/TECH", MENU), ("TECH", "existing"))

    def test_a_self_nested_top_that_is_not_on_the_menu_is_the_reviewer_call(self):
        self.assertEqual(_one("FILL/FILL", MENU), ("FILL", "unknown"))


class TruncationCollisions(unittest.TestCase):
    def test_a_longer_truncation_of_a_known_drawer_prefixes_onto_it(self):
        self.assertEqual(_one("NEW/USR/PREFE", MENU), ("USR/PREF", "existing"))

    def test_a_shorter_truncation_of_a_known_drawer_prefixes_onto_it(self):
        self.assertEqual(_one("NEW/MEM/QWEN", MENU), ("MEM/QWEN3", "existing"))

    def test_a_genuine_new_cutter_still_opens(self):
        self.assertEqual(_one("NEW/HW/PANEL", MENU), ("NEW/HW/PANEL", "new"))

    def test_a_bare_invention_that_prefixes_one_top_folds_onto_it(self):
        # "OP" arriving where the menu carries OPS is one drawer, not two
        self.assertEqual(_one("NEW/OP", MENU), ("OPS", "existing"))


class PlainAnswers(unittest.TestCase):
    def test_menu_shelf_wins_as_is(self):
        self.assertEqual(_one("OPS/STATE", MENU), ("OPS/STATE", "existing"))

    def test_wild_stays_wild(self):
        self.assertEqual(_one("WILD", MENU), ("", "wild"))

    def test_unknown_code_is_the_reviewers(self):
        self.assertEqual(_one("COOKING", MENU), ("COOKING", "unknown"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
