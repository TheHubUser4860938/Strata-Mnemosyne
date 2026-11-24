#!/usr/bin/env python3
"""The vault projection (item 13, 2026-11-24): shelf→folder, row→note, link→wikilink, and the
three semantics that make it safe to run twice — the manifest, the human note, the prune.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from m10_vault import HOME, lint, note_name, project, slug     # noqa: E402


def fact(i, text, klass="OPS", when="2026-11-24 10:00", **kw):
    r = {"id": i, "text": text, "class": klass, "scope": "default", "confidence": 0.8,
         "when": when, "proof": 0, "stale": False, "why": "", "scar": [],
         "supersedes": "", "superseded_by": "", "filed": ""}
    r.update(kw)
    return r


class TheVault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.out = Path(self.tmp) / "vault"
        self.rows = [fact(11, "the sweep drains the queue", "OPS/SWEEP", proof=3),
                     fact(12, "the clerk files at temp 0.2", "MEM/HARVEST"),
                     fact(13, "the card is a 4090", "HW")]
        self.links = {11: [{"kind": "supports", "target": "[[12 the clerk files at temp 0.2]]"}]}

    def test_a_shelf_is_a_folder_and_a_row_is_a_note_named_by_its_id(self):
        t = project(self.out, self.rows, self.links)
        self.assertEqual(t["rows"], 3)
        self.assertTrue((self.out / "OPS" / note_name(11, "the sweep drains the queue")).exists(),
                        "the shelf's first segment is the folder, so OPS/SWEEP joins OPS")
        self.assertTrue((self.out / "HW" / note_name(13, "the card is a 4090")).exists())
        body = (self.out / "OPS" / note_name(11, "the sweep drains the queue")).read_text()
        self.assertIn("id: 11", body)
        self.assertIn("proof: 3", body, "the observation rung rides into the vault")
        self.assertIn("## Connections", body, "the graph pane draws bullets, not properties")
        self.assertIn("supports → [[12", body)

    def test_a_second_run_writes_nothing_and_a_retired_rows_note_is_pruned(self):
        project(self.out, self.rows, self.links)
        again = project(self.out, self.rows, self.links)
        self.assertEqual((again["written"], again["unchanged"]), (0, 3),
                         "byte-stable: the vault's modified-sort stays meaningful")
        gone = project(self.out, self.rows[:2], {})
        self.assertEqual(gone["pruned"], 1, "the retired row's note goes with it")
        self.assertFalse((self.out / "HW" / note_name(13, "the card is a 4090")).exists())

    def test_a_human_note_wearing_the_name_is_left_alone(self):
        (self.out / "OPS").mkdir(parents=True)
        mine = self.out / "OPS" / note_name(11, "the sweep drains the queue")
        mine.write_text("the owner's own note\n", encoding="utf-8")
        project(self.out, self.rows, self.links)
        self.assertEqual(mine.read_text(encoding="utf-8"), "the owner's own note\n",
                         "the manifest owns files, not the vault")
        self.assertTrue((self.out / "OPS" / (note_name(11, "the sweep drains the queue")
                                             + ".strata.md")).exists(),
                        "and the row is still in here, beside it")

    def test_the_ledger_the_chain_and_home_land_beside_the_notes(self):
        project(self.out, self.rows, self.links)
        for name in ("facts.base", "chain.base", "Home.md"):
            self.assertTrue((self.out / name).exists(), name)
        self.assertIn("views", (self.out / "facts.base").read_text(encoding="utf-8"))
        self.assertEqual((self.out / "Home.md").read_text(encoding="utf-8"), HOME)

    def test_the_lint_names_the_three_mechanical_failures(self):
        rows = [fact(21, "a note with no date", "OPS", when=""),
                fact(22, "a note with no shelf", ""),
                fact(23, "a note citing a missing belief", "OPS",
                     supersedes="[[11 gone]]")]
        project(self.out, rows, {})
        bad = lint(self.out)
        self.assertEqual(len(bad), 3, bad)
        self.assertTrue(any("no `when`" in b for b in bad))
        self.assertTrue(any("no `shelf`" in b for b in bad))
        self.assertTrue(any("not in the vault" in b for b in bad))
        self.assertEqual(lint(self.out / "nothing"), ["no manifest at "
                                                      + str(self.out / "nothing" / ".strata-vault.json")
                                                      + " — run the projection first"])

    def test_the_slug_is_a_filename_not_a_paragraph(self):
        self.assertEqual(slug("The 4090 has 24 GB of VRAM!"), "the 4090 has 24 gb of vram")
        self.assertLessEqual(len(slug("word " * 40)), 44)
        self.assertTrue(note_name(9, "!!!").startswith("9 "))
        for ch in '/:*?"<>|':
            self.assertNotIn(ch, slug('a/b:c*d?e"f<g>h|i'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
