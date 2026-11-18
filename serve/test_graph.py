"""Tests for the graph arm: `strata/graphify` and the third vote in `serve.memory.search`.

Three things these tests pin:

1. A store with no graph answers `op=graph` with zeros and a message, not an error
   (anti-vacuity: an absent thing is never silently "not enough").
2. `graph_weight=0.0` is byte-identical to the release before the arm: the same queries
   return the same ids in the same order.
3. With a graph on disk, a row LINKED to a hit rises, and the rise is attributed —
   `graph_rank` names the arm that moved it, the same convention as `lex_rank`/`cos_rank`.
"""

import json
import os
import shutil
import tempfile
import unittest

from serve.memory import MemoryService


class GraphArm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="grapharm-")
        cls.store = MemoryService(cls.dir)
        # A tiny ledger: one row about the browse lever, one about the shelf it lands on,
        # one about an unrelated card. The graph will link the first two.
        cls.a = cls.store.remember("Running graphify extract with default concurrency on one "
                                   "4090 caused timeouts, so calls were serialized.",
                                   klass="OPS", scope="default")["id"]
        cls.b = cls.store.remember("The serialized graphify calls land on the OPS shelf in the "
                                   "memory store ledger.",
                                   klass="OPS", scope="default")["id"]
        cls.c = cls.store.remember("The Radeon 780M plays Starfield at 1080p medium near 60 fps.",
                                   klass="HW", scope="default")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _write_graph(self, links, nodes=None):
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        nodes = nodes if nodes is not None else [
            {"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)]
        with open(os.path.join(self.dir, "strata-graphify", "graph.json"), "w") as f:
            json.dump({"nodes": nodes, "links": links, "hyperedges": []}, f)

    def test_no_graph_is_not_an_error(self):
        """A box with no graph answers with zeros and a message, not an exception."""
        from strata.graphify import StrataGraphify
        fresh = tempfile.mkdtemp(prefix="graphnone-")
        try:
            g = StrataGraphify(fresh)
            s = g.summary()
            self.assertEqual(s["status"], "empty")
            self.assertEqual(s["nodes"], 0)
            self.assertEqual(g.view()["nodes"], [])
            self.assertIn("No graph yet", s.get("message", ""))
        finally:
            shutil.rmtree(fresh, ignore_errors=True)

    def test_weight_zero_is_the_old_bytes(self):
        q = "graphify extract concurrency 4090 timeouts"
        self.store.graph_weight = 0.0
        base = [h["id"] for h in self.store.search(q, limit=8)]
        self._write_graph([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}",
                            "relation": "about"}])
        self.store._graph_cache = None
        same = [h["id"] for h in self.store.search(q, limit=8)]
        self.assertEqual(base, same)

    def test_a_linked_row_rises_and_says_why(self):
        self._write_graph([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}",
                            "relation": "about"}])
        self.store._graph_cache = None
        q = "graphify extract concurrency 4090 timeouts"
        self.store.graph_weight = 0.0
        off = {h["id"]: h for h in self.store.search(q, limit=12)}
        self.store.graph_weight = 0.6
        on = {h["id"]: h for h in self.store.search(q, limit=12)}
        self.assertIn(self.b, off, "the linked row is a candidate without the arm")
        # The arm spends RRF currency on the neighbour's behalf, so its score rises. Whether
        # that is enough to pass the seed above it is a question of the store's size; on a
        # three-row store the seed wins on rank 1 with or without the vote.
        self.assertGreater(on[self.b]["score"], off[self.b]["score"],
                           "the graph vote should raise the linked row")
        self.assertTrue(on[self.b].get("graph_rank"), "the arm signs its own moves")

    def test_the_op_answers(self):
        """The wire verb reads the graph file the same way the page does — no build needed."""
        from strata.graphify import StrataGraphify
        self._write_graph([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}",
                            "relation": "about"}])
        g = StrataGraphify(self.dir)
        v = g.view()
        self.assertEqual(len(v["nodes"]), 3)
        self.assertEqual(len(v["edges"]), 1)
        self.assertEqual(g.summary()["in_graph"], 3, "coverage counts the row ids the graph names")

    def test_neighbours_stay_in_scope(self):
        """A graph edge to a row in ANOTHER scope lifts shelves, not stores (audit 2026-11-16):
        the arm's IN-list read must honour the request's scopes, as the lexical SELECT does."""
        other = self.store.remember("Venue nights belong to the owner, scheduled by hand.",
                                    klass="OPS", scope="venue")["id"]
        self._write_graph([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{other}",
                            "relation": "about"}])
        self.store._graph_cache = None
        self.store.graph_weight = 0.6
        ids = [h["id"] for h in self.store.search("graphify extract concurrency 4090 timeouts",
                                                  limit=20)]
        self.assertNotIn(other, ids, "the graph arm crossed into the venue scope")
        self.store.graph_weight = 0.0

    def test_cover_drains_then_plateaus(self):
        """cover() loops over the uncovered queue and stops when a pass gains nothing — the
        plateau law, pinned with a stubbed extractor so the test costs no LLM call."""
        from strata.graphify import StrataGraphify
        g = StrataGraphify(self.dir)

        def stub(chunk):
            return {"nodes": [{"id": f"ops_fact_{self.a}", "label": "x"},
                              {"id": f"ops_fact_{self.b}", "label": "y"}],
                    "edges": [{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}"}],
                    "hyperedges": [], "input_tokens": 1, "output_tokens": 1}

        g._extract = stub
        # Fresh standing graph citing ONE row, so the queue is deterministic in any test order:
        # pass 1 must add the stub's second row, pass 2 must add nothing and stop on the plateau.
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        with open(os.path.join(self.dir, "strata-graphify", "graph.json"), "w") as f:
            json.dump({"nodes": [{"id": f"ops_fact_{self.a}"}], "links": [], "hyperedges": []}, f)
        s = g.cover(per_file=10, files_per_chunk=6, max_passes=5)
        self.assertEqual(s["in_graph"], 2, "the stub names two rows, and both land in the graph")
        self.assertEqual(s["cover_passes"], 2, "pass 2 gains nothing and stops on the plateau")


    def test_explain_path_query_walk_the_graph(self):
        """The read side: explain names a node and its scar, path reports the weakest hop,
        query returns a budgeted neighbourhood — all without a model call."""
        from strata.graphify import StrataGraphify
        self._write_graph([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}",
                            "relation": "about", "confidence": "EXTRACTED"},
                           {"source": f"ops_fact_{self.b}", "target": f"ops_fact_{self.c}",
                            "relation": "supports", "confidence": "INFERRED"}],
                          nodes=[{"id": f"ops_fact_{self.a}", "label": "graphify extract "
                                        "concurrency on a 4090 times out"},
                                 {"id": f"ops_fact_{self.b}", "label": "the OPS shelf keeps "
                                        "the serialized graphify calls"},
                                 {"id": f"hw_fact_9", "label": "the nvidia 4090 is the one card"}])
        g = StrataGraphify(self.dir)

        e = g.explain(str(self.a))                       # by fact id
        self.assertEqual(e["status"], "ok")
        self.assertEqual(e["degree"], 1)
        self.assertEqual(e["connections"][0]["relation"], "about")
        self.assertIn("concurrency", e["text"], "the explain carries the live ledger row")

        p = g.path(str(self.a), str(self.c))             # two hops, mixed tags
        self.assertEqual(p["status"], "ok")
        self.assertEqual(p["hops"], 2)
        self.assertEqual(p["confidence"], "INFERRED", "the route is as strong as its weakest hop")

        q = g.query("graphify concurrency 4090", budget=400)
        self.assertEqual(q["status"], "ok")
        self.assertLessEqual(len(q["text"]), 400, "the budget is the contract")
        self.assertIn(f"ops_fact_{self.a}", str(q.get("seeds")), "the seed is the row the words name")

    def test_explain_absent_node_says_so(self):
        """Anti-vacuity: not-found is a named answer, not an empty dict."""
        from strata.graphify import StrataGraphify
        g = StrataGraphify(self.dir)
        r = g.explain("nostradamus-9000")
        self.assertEqual(r["status"], "not-found")
        self.assertIn("message", r)


class SimLayer(unittest.TestCase):
    """The similarity layer (2026-11-17, the owner's embedding-pass ask): `graph_sim_k` > 0
    makes the store's OWN vectors a second edge source for the graph arm, so a neighbour the
    LLM pass never cited can still be pulled in on a vector vote.

    Four things pinned: the arm fires with NO graph file (the layer is a source of edges by
    itself); the vote is signed; concept links are priced ahead of vector links when a seed has
    both; and the identity-keyed cache follows a write, so a row committed after the first
    search is reachable without a restart.
    """

    @classmethod
    def setUpClass(cls):
        from serve.test_memory import StubEmbedder
        cls.dir = tempfile.mkdtemp(prefix="graph-sim-")
        cls.store = MemoryService(cls.dir, embedder=StubEmbedder({
            "the graph drain runs two chunks at a time on one 4090": [1.0, 0.0, 0.0, 0.0],
            # near-identical vector, disjoint words: the layer's whole point — a row no word
            # query reaches, sitting next door in embedding space
            "expert slots are evicted per layer so admitted experts get used":
                [0.97, 0.24, 0.0, 0.0],
            "the Radeon 780M plays Starfield at 1080p": [0.0, 0.0, 0.0, 1.0],
        }))
        cls.a = cls.store.remember("the graph drain runs two chunks at a time on one 4090",
                                   klass="OPS", scope="default")["id"]
        cls.b = cls.store.remember("expert slots are evicted per layer so admitted experts "
                                   "get used", klass="OPS", scope="default")["id"]
        cls.c = cls.store.remember("the Radeon 780M plays Starfield at 1080p",
                                   klass="OPS", scope="default")["id"]
        cls.q = "the graph drain runs two chunks at a time on one 4090"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        """The three rows and the stub embedder are built once per class, so each test starts
        from the same slate: no LLM graph file, no cached adjacency of either source."""
        p = os.path.join(self.dir, "strata-graphify", "graph.json")
        if os.path.exists(p):
            os.remove(p)
        self.store._graph_cache = None
        self.store._sim_cache = None
        self.store.graph_weight = 0.0
        self.store.graph_sim_k = 2       # the layer's own knob; _search() sets it per call

    def _search(self, weight: float, sim_k: int, q: str | None = None):
        self.store.graph_weight = weight
        self.store.graph_sim_k = sim_k
        return {h["id"]: h for h in self.store.search(q or self.q, limit=12)}

    def test_the_layer_fires_with_no_graph_file(self):
        """The layer is an EDGE SOURCE, not a modifier of the LLM arm: with no graph file on
        disk, `_graph_expand` used to return the candidates untouched. It must now cast votes
        off the store's own vectors, and the seed's neighbour must pay for them."""
        self.assertFalse(os.path.exists(os.path.join(self.dir, "strata-graphify", "graph.json")),
                         "the store has no LLM graph — every edge here is a vector")
        off = self._search(0.6, 0)
        on = self._search(0.6, 2)
        self.assertGreater(on[self.b]["score"], off[self.b]["score"],
                           "the vector neighbour cast no vote")
        self.assertTrue(on[self.b].get("graph_rank"), "the arm signs the vote it cast")
        self.assertNotIn("graph_rank", off[self.b], "k=0 must leave the arm's signature off")

    def test_sim_k_zero_is_the_shipped_two_arm(self):
        """The default path stays byte-identical: k=0 is the release before the layer."""
        base = [h["id"] for h in self._search(0.0, 0).values()]
        moved = [h["id"] for h in self._search(0.6, 0).values()]
        self.assertEqual(base, moved)

    def test_concept_links_are_priced_ahead_of_vector_links(self):
        """One seed, two edge sources. The seed is `a`; its LLM neighbour is `c`, its vector
        neighbour is `b`. `rank = si + len(nbrs) + ni` prices the concept link first, so `c`
        must carry the better graph rank — the owner's ruling, concept links first."""
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        with open(os.path.join(self.dir, "strata-graphify", "graph.json"), "w") as f:
            json.dump({"nodes": [{"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)],
                       "links": [{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.c}",
                                  "relation": "about"}],
                       "hyperedges": []}, f)
        self.store._graph_cache = None
        hits = self._search(0.6, 3)
        self.assertTrue(hits[self.c].get("graph_rank"), "the LLM neighbour got no vote")
        self.assertLess(hits[self.c]["graph_rank"], hits[self.b]["graph_rank"],
                        "a vector neighbour undercut the seed's own concept link")

    def test_a_write_after_the_first_search_is_reachable(self):
        """Seed-local (2026-11-18), so the layer reads the matrix on demand: the cached UNIT
        matrix is keyed on the vector matrix's IDENTITY, and a row committed after a search
        must be in the neighbourhood of everything asked for afterwards."""
        adj = self.store._sim_neighbours([self.a, self.b, self.c])
        self.assertEqual(set(adj), {self.a, self.b, self.c}, "the layer saw none of the rows")
        d = self.store.remember("the clerk drains sixty turns a tick behind 240 seconds of "
                                "silence", klass="OPS", scope="default")
        adj2 = self.store._sim_neighbours([self.a, d["id"]])
        self.assertIn(d["id"], adj2, "a row written after the cache filled is invisible to it")
        self.assertTrue(adj2[d["id"]], "the new row has no neighbourhood at k=2")
        self.assertIn(self.a, adj2, "a read after the write lost a row it had already seen")


if __name__ == "__main__":
    unittest.main()
