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

    def _write_graph(self, links):
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        nodes = [{"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)]
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


if __name__ == "__main__":
    unittest.main()
