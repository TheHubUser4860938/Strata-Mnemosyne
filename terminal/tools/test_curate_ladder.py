#!/usr/bin/env python3
"""The resolution ladder (item 16, 2026-11-24) — bands, the name gate, and the bound it reports.

Pure over rows = (id, text, vec, class), so this runs with no server and no model. Vectors are
built from an explicit cosine by construction: two unit vectors at angle θ have cos θ, so the test
names the SIMILARITY it wants and the ladder has to place it in the right band.
"""
import math
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np                                        # noqa: E402
from m7_consolidate import ladder                         # noqa: E402


def vec(c: float) -> bytes:
    """A 4-d unit vector at cosine `c` with [1,0,0,0]."""
    v = np.array([c, math.sqrt(max(0.0, 1 - c * c)), 0.0, 0.0], dtype=np.float32)
    return v.astype(np.float32).tobytes()


BASE = vec(1.0)


def row(i, text, cos=1.0, klass=""):
    return (i, text, vec(cos), klass)


class TheLadder(unittest.TestCase):
    def test_two_rows_at_the_same_words_are_certain_without_a_model(self):
        rows = [row(1, "the 4090 has 24 GB of VRAM"), row(2, "the 4090 has 24 GB of VRAM")]
        certain, ask, st = ladder(rows)
        self.assertEqual([c[0] for c in certain], [1], "one pair, folded by the EXACT rung")
        self.assertEqual(ask, [], "the cheap rung spent nothing")
        self.assertEqual(st["exact"], 1)
        self.assertEqual(st["llm_requests"], 0)
        # Punctuation is not a different claim: the SAME words with a full stop is the fuzzy rung's
        # work, and it is still certain — no model asked.
        rows2 = [row(1, "the 4090 has 24 GB of VRAM"), row(2, "The 4090 has 24 GB of VRAM.")]
        c2, a2, st2 = ladder(rows2)
        self.assertEqual((len(c2), len(a2)), (1, 0))
        self.assertEqual(st2["fuzzy"], 1, "casefold and a stop: the token sets agree")

    def test_the_name_gate_sends_a_digit_mismatch_to_not_a_pair(self):
        # "48 layers" and "12 layers" are 0.999 cosine apart in a vector space that reads the
        # sentence, and they are not the same claim. The digit set is the cheapest ruler that knows.
        rows = [row(1, "the model runs at 48 layers deep", 0.999),
                row(2, "the model runs at 12 layers deep", 0.999)]
        certain, ask, st = ladder(rows)
        self.assertEqual(certain, [])
        self.assertEqual(ask, [])
        self.assertEqual(st["name_gate"], 1, "certain NOT, and no model asked")

    def test_the_middle_band_is_ambiguous_and_counts_a_request_bound(self):
        # One shared digit set (the gate stays out of the way) and LETTERED variants, so the only
        # thing varying is the cosine: 12 paraphrases at 0.86 against the seed.
        letters = "abcdefghijkl"
        rows = [row(0, "the graft lever was fixed at 12 cells", 1.0)]
        rows += [row(i, f"the graft lever got repaired at 12 cells, variant {letters[i - 1]}", 0.86)
                 for i in range(1, 13)]
        certain, ask, st = ladder(rows, cap_per_request=10)
        # The band is the 12 pairs against the seed (cos 0.86); the 66 pairs AMONG the variants are
        # ~0.999 apart, so the embedding rung folds them with no model. One fixture, both bands.
        self.assertEqual(len(ask), 12, "the seed's 12 pairs are the model's to judge")
        self.assertEqual(len(certain), 66, "the variants are near-identical to EACH OTHER")
        self.assertEqual(st["ambiguous_count"], 12)
        self.assertEqual(st["embedding"], 66, "the 0.95 line, not the model, settled those")
        self.assertEqual(st["llm_requests"], 2, "ceil(12/10) asks — the bound is reportable")
        self.assertEqual(st["undecided"], 12, "not reached is not rejected")

    def test_a_pair_below_the_floor_is_not_a_pair_at_all(self):
        rows = [row(1, "the cow purchase came before the fence repair", 1.0),
                row(2, "micca rb42 speakers put out surprising bass", 0.40)]
        certain, ask, st = ladder(rows)
        self.assertEqual((certain, ask), ([], []))
        self.assertEqual(st["not_a_pair"], 1)

    def test_the_label_rung_keeps_two_shelves_from_comparing(self):
        # Rung 1 is the label: two drawers are two subjects, and the ladder does not ask which
        # words agree. The same words on ONE shelf is a pair the EXACT rung folds.
        rows = [row(1, "the card is an RTX 4090", 1.0, "HW/GPU"),
                row(2, "the card is an RTX 4090", 1.0, "HW/GPU")]
        certain, ask, st = ladder(rows)
        self.assertEqual(st["pairs"], 1, "one shelf, so it is a pair")
        self.assertEqual(len(certain), 1, "and the EXACT rung folds it with no model")
        rows2 = [row(1, "the card runs cool under load", 0.99, "HW/GPU"),
                 row(2, "the bill passed the senate floor", 0.99, "POL/ARSA")]
        c2, a2, st2 = ladder(rows2)
        self.assertEqual((c2, a2), ([], []), "two drawers, two subjects: not a pair")
        self.assertEqual(st2["pairs"], 0, "the label gate fired before the cosine was read")

    def test_the_cap_drops_the_weakest_candidates_and_says_so(self):
        # Lettered variants (the name gate stays out), one digit set, and a cosine ladder from
        # 0.81 to 0.87 against the seed: the cap must keep the TIGHTEST and count what it cut.
        letters = "abcdefgh"
        rows = [row(0, "the standing cart is 262 MB on disk", 1.0)]
        rows += [row(i, f"the standing cart is 262 MB on disk, note {letters[i - 1]}", 0.80 + i * 0.01)
                 for i in range(1, 9)]                        # 8 in the band, tightest last
        certain, ask, st = ladder(rows, cap_per_label=3)
        self.assertEqual(len(ask), 3, "the three TIGHTEST survive the label cap")
        self.assertEqual(st["cap_truncated_pairs"], 5, "and the run says how many it dropped")
        self.assertGreater(ask[0][2], ask[-1][2], "sorted tightest-first")
        self.assertLessEqual(st["llm_requests"], 1, "three pairs, one request")

    def test_the_vectors_agree_with_the_numbers_the_bands_use(self):
        self.assertAlmostEqual(float(np.dot(np.frombuffer(BASE, np.float32),
                                           np.frombuffer(vec(0.9), np.float32))), 0.9, places=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
