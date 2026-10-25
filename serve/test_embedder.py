"""serve/test_embedder.py - the bge-small pins and a semantic smoke, offline-capable.

The pin test needs no model (a fake dir with wrong SHA256SUMS must raise before anything
loads - a silently swapped embedder silently changes every ranking in the store). The real-
model smoke SKIPS cleanly when the files are absent, so CI without the 133 MB download still
passes; on the dev box (downloaded 2026-10-14, pinned in SHA256SUMS) it asserts the exact
behavior the temporal diagnostic demanded: a paraphrased query ranks its decision note over
unrelated facts with ZERO lexical overlap.
"""
import tempfile
import unittest
from pathlib import Path

from serve.embedder import Embedder, EmbeddingGemma2, _verify_pinned
from serve.memory import MemoryService
from strata_control.datafolder import data_dir      # the one data folder (2026-10-23): the embedder is not inside the install

MODEL_DIR = data_dir(Path(__file__).resolve().parent.parent) / "embeddings/bge-small-en-v1.5"
EG2_DIR = data_dir(Path(__file__).resolve().parent.parent) / "embeddings/embeddinggemma-2"


class Pins(unittest.TestCase):
    def test_wrong_sha256_raises_before_any_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "model.onnx").write_bytes(b"not really a model")
            (p / "tokenizer.json").write_text("{}")
            (p / "SHA256SUMS").write_text("0" * 64 + "  model.onnx\n" + "1" * 64 + "  tokenizer.json\n")
            with self.assertRaises(ValueError) as cm:
                Embedder(p)
            self.assertIn("pin mismatch", str(cm.exception))

    def test_no_pin_file_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:      # verify passes; the ONNX load is what fails next
            _verify_pinned(Path(d))                   # (no exception about pins from a pinless dir)


@unittest.skipUnless((MODEL_DIR / "model.onnx").exists() and (MODEL_DIR / "SHA256SUMS").exists(),
                     "bge-small files not downloaded on this box")
class RealModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.emb = Embedder(MODEL_DIR)

    def test_semantic_ranking_and_norms(self):
        docs = self.emb.embed_docs([
            "The user decided to batch the date-filter parameter implementation into Ladder A",
            "The township of Darnen is located in Stevens County, Minnesota",
            "NVIDIA GeForce RTX 4090 with 24 GB VRAM drives this machine"])
        # the query shares NO rare word with the decision note - pure semantic reach
        q = self.emb.embed_query("which plan was chosen for folding in the hygiene fix?")
        cos = docs @ q
        self.assertGreater(cos[0], cos[1])
        self.assertGreater(cos[0], cos[2])
        self.assertGreater(cos[0], 0.3)
        import numpy as np
        self.assertTrue(np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-4))
        self.assertEqual(docs.shape, (3, 384))

    def test_query_prefix_changes_the_vector(self):
        import numpy as np
        a = self.emb.embed_query("cascade fix")
        b = self.emb._encode(["cascade fix"])[0]       # unprefixed
        self.assertGreater(float(np.linalg.norm(a - b)), 0.05,
                           "bge asymmetry (query prefix) must be live or ranking degrades quietly")


@unittest.skipUnless((EG2_DIR / "onnx/model_quantized.onnx").exists()
                     and (EG2_DIR / "SHA256SUMS").exists(),
                     "embeddinggemma-2 files not downloaded on this box")
class RealModelGemma(unittest.TestCase):
    """EmbeddingGemma-2 q8 CPU smoke (downloaded 2026-10-24, SHA256SUMS written against the
    repo's own LFS oids). The card's example is the standard: the published scores
    (0.684/0.854/0.752/0.783 for Venus/Mars/Jupiter/Saturn at q4/WebGPU) must be met within
    q8 tolerance with the identical ranking - end-to-end proof that this ORT feed (empty
    media-feature tensors, the graph's masked-mean sentence_embedding, L2 after) reproduces
    the vendor recipe, prefixes included."""

    @classmethod
    def setUpClass(cls):
        cls.emb = EmbeddingGemma2(EG2_DIR, threads=4)

    def test_card_example_ranking_and_scores(self):
        import numpy as np
        q = self.emb.embed_query("Which planet is known as the Red Planet?")
        docs = self.emb.embed_docs([
            "Venus is often called Earth's twin because of its similar size and proximity.",
            "Mars, known for its reddish appearance, is often referred to as the Red Planet.",
            "Jupiter, the largest planet in our solar system, has a prominent red spot.",
            "Saturn, famous for its rings, is sometimes mistaken for the Red Planet."])
        self.assertEqual(q.shape, (768,))
        self.assertEqual(docs.shape, (4, 768))
        self.assertTrue(np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-4))
        cos = docs @ q
        self.assertEqual(int(np.argmax(cos)), 1)                      # Mars, as the card has it
        order = sorted(range(4), key=lambda i: -cos[i])
        self.assertEqual(order, [1, 3, 2, 0])                         # Mars Saturn Jupiter Venus
        for got, card in zip(cos, (0.684, 0.854, 0.752, 0.783)):      # the card's q4 scores
            self.assertLess(abs(float(got) - card), 0.05,
                            f"q8 CPU drifted >0.05 from the card's q4 reference {card}: "
                            f"{float(got):.3f}")

    def test_recipes_are_live(self):
        import numpy as np
        a = self.emb.embed_query("cascade fix")
        b = self.emb._encode([EmbeddingGemma2.QUERY_PREFIX + "cascade fix"])[0]
        self.assertTrue(np.allclose(a, b, atol=1e-6),
                        "embed_query must BE the recipe string, not a paraphrase of it")
        c = self.emb._encode(["cascade fix"])[0]                      # bare, no prefix
        self.assertGreater(float(np.linalg.norm(a - c)), 0.05,
                           "the query asymmetry must be live or search quality degrades quietly")


@unittest.skipUnless((MODEL_DIR / "model.onnx").exists() and (MODEL_DIR / "SHA256SUMS").exists(),
                     "bge-small files not downloaded on this box")
class HitProvenance(unittest.TestCase):
    """Which arm put a hit where. Every hybrid hit now carries `lex_rank` (position in the bm25 list,
    before the blend re-sorts it) and `cos_rank` (position in the cosine scan) - both values already
    existed inside the fusion and were thrown away. The knowledge-update -0.139 (the reranker losing
    rank-1 slots on the venue) cost a day to diagnose because the answer was not in the record; this is
    the field that makes that question a query. Bytes discipline: the block renders scope+text only, the
    MCP tool whitelists its fields (serve/memory.py:198), so nothing the MODEL reads changed - this is
    for the API, the UI and the probes."""

    @classmethod
    def setUpClass(cls):
        cls.emb = Embedder(MODEL_DIR)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mem = MemoryService(self.tmp.name, recall_limit=10, embedder=self.emb)
        # the three shapes the fusion can produce, in one store
        self.mem.remember("The user's GPU is an NVIDIA GeForce RTX 4090 with 24 GB VRAM",
                          scope="default", guard=False)          # both arms: shares the rare words
        self.mem.remember("The user decided to batch the date-filter parameter implementation into "
                          "Ladder A alongside the cascade fix", scope="default", guard=False)
        self.mem.remember("The township of Darnen is located in Stevens County, Minnesota",
                          scope="default", guard=False)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def test_ranks_agree_with_what_each_arm_actually_returned(self):
        # the invariant, not a model-dependent ranking: a hit the lexical arm proposed carries its bm25
        # position, and one it never proposed carries None. Queries here match at most one bm25 row, so
        # the blend cannot reorder and the position is checkable against the embedder-off arm directly.
        for q in ("RTX 4090 VRAM", "Stevens County Minnesota township", "which plan was chosen"):
            lex = [h["id"] for h in self.mem.search(q, scope="default", limit=10, semantic=False)]
            for h in self.mem.search(q, scope="default", limit=10):
                if h["id"] in lex:
                    self.assertEqual(h["lex_rank"], lex.index(h["id"]) + 1, f"{q}: lex position moved")
                else:
                    self.assertIsNone(h.get("lex_rank"), f"{q}: a cosine-only hit claims a lexical rank")

    def test_lexical_hit_keeps_its_bm25_position(self):
        hits = self.mem.search("RTX 4090 VRAM", scope="default", limit=10)
        got = [h for h in hits if "RTX 4090" in h["text"]]
        self.assertTrue(got)
        self.assertEqual(got[0]["lex_rank"], 1)                   # bm25's first place, recorded as such
        self.assertIsInstance(got[0]["cos_rank"], int)            # and cosine ranked it too

    def test_the_lexical_arm_records_no_cosine_rank(self):
        # embedder OFF path: no fusion happened, so no cosine provenance may leak into the record
        hits = self.mem.search("RTX 4090 VRAM", scope="default", limit=10, semantic=False)
        self.assertTrue(hits)
        for h in hits:
            self.assertIn("lex_rank", h)
            self.assertNotIn("cos_rank", h)

    def test_provenance_survives_read_path_dedupe(self):
        # the near-dupe suppression pass must pass the dicts through, not rebuild them, or the fields
        # vanish exactly when a duplicate family is involved - the case that needs them most
        self.mem.remember("The user's machine has an NVIDIA GeForce RTX 4090 with 24 GB VRAM",
                          scope="default", guard=False)
        for h in self.mem.search("RTX 4090 VRAM", scope="default", limit=10):
            self.assertIn("lex_rank", h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
