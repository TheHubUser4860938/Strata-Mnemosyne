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
        plateau law, pinned with a stubbed extractor so the test costs no LLM call.

        The queue drains in ONE pass since 2026-11-26: a build ends with `ensure_fact_nodes`,
        the coverage floor, which names every live row the extractor skipped (a node keyed
        `<shelf>_fact_<id>` plus one edge to the shelf hub). Before the floor this asserted
        in_graph 2 after pass 1 and a second pass to earn row c; the floor is why the tile can
        read 100% while the concept layer keeps growing pass over pass.
        """
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
        self.assertEqual(s["in_graph"], 3, "the stub names two rows, the floor names the third")
        self.assertEqual(s["uncovered"], 0, "the drain's definition of done: no row left unnamed")
        self.assertEqual(s["cover_passes"], 1, "the queue is empty, so a second pass never runs")


    def test_a_part_file_keeps_its_name_when_its_rows_do(self):
        """Corpus parts are named by their row-id RANGE, not a part index (2026-11-26). A cover
        pass reads only the rows no node names, so as the queue shrinks an index name renumbers
        the shelf's files, and graphify keys node ids by the file stem — a re-extraction then
        re-rolls names an earlier pass had already earned. Measured on the live drain: 516 rows
        named per pass against 368 lost, a plateau near 58% coverage."""
        from strata.graphify import StrataGraphify
        g = StrataGraphify(self.dir)
        rows = [(10 + i, "OPS", f"fact {i}", "2026-11-26", 0.9) for i in range(6)]
        self.assertEqual({p.name for p in g.write_corpus(rows, per_file=2)},
                         {"ops-000010-000011.md", "ops-000012-000013.md", "ops-000014-000015.md"})
        # The head slice gets named and drops out of the next queue; the parts that keep their
        # rows keep their names, so their nodes are re-extracted against the same facts.
        self.assertEqual({p.name for p in g.write_corpus(rows[2:], per_file=2)},
                         {"ops-000012-000013.md", "ops-000014-000015.md"})

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
        from the same slate: no LLM graph file, no cached adjacency of either source.

        The slate now has a third source to clear: `remember()` links semantic near-dupes with an
        `about` edge, and since 2026-11-24 the typed table is an edge SOURCE for this arm, so the
        stub rows are linked to each other (cosine 0.97) and would vote in the k=0 arm. This class
        measures the VECTORS; `LinkVote` measures the links.
        """
        p = os.path.join(self.dir, "strata-graphify", "graph.json")
        if os.path.exists(p):
            os.remove(p)
        self.store.conn.execute("delete from links")
        self.store.conn.commit()
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


class ConceptWalk(unittest.TestCase):
    """The graph's concept nodes are bridges, not dead ends (2026-11-24).

    The built graph carries two kinds of node: a row (id `<shelf>_fact_<n>`) and a concept the
    extraction pass lifted out of the fact text. `fid()` parses a row id and returns None for a
    concept, so the shipped adjacency kept only fact-to-fact edges — 1,020 of the store graph's
    3,133 edges (measured 2026-11-23). A fact that reaches another fact THROUGH a concept — the
    classic multi-hop case, two rows that name the same subject — was invisible to the arm.

    These tests pin the fix: a shared concept is an edge, a direct edge is priced ahead of a
    mediated one, a tight concept is priced ahead of a hub, and a hub cannot flood the block.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="concepts-")
        cls.store = MemoryService(cls.dir)
        ids = {}
        for name, text in (
                ("a", "The dflash2 drafter accepts six proposals per step on the heretic pack."),
                ("b", "DFlash2 acceptance on the tuned pack reads 0.803 at confidence 0.7."),
                ("c", "The Radeon 780M plays Starfield at 1080p medium near 60 fps."),
                ("d", "Spec 8 costs no VRAM because the eight-token window is already captured.")):
            ids[name] = cls.store.remember(text, klass="OPS", scope="default")["id"]
        cls.a, cls.b, cls.c, cls.d = (ids["a"], ids["b"], ids["c"], ids["d"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _graph_file(self, nodes, links):
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        with open(os.path.join(self.dir, "strata-graphify", "graph.json"), "w") as f:
            json.dump({"nodes": nodes, "links": links, "hyperedges": []}, f)
        self.store._graph_cache = None

    def test_a_shared_concept_reaches_the_sibling_row(self):
        """a — concept — b, no direct edge: the arm must see b as a neighbour of a."""
        self._graph_file(
            [{"id": f"ops_fact_{i}"} for i in (self.a, self.b)]
            + [{"id": "ops_concept_drafter", "label": "DFlash2 drafter"}],
            [{"source": f"ops_fact_{self.a}", "target": "ops_concept_drafter"},
             {"source": "ops_concept_drafter", "target": f"ops_fact_{self.b}"}])
        adj = self.store._graph()
        self.assertIn(self.b, list(adj.get(self.a, ())),
                      "a fact linked through a concept is not a neighbour")
        self.assertIn(self.a, list(adj.get(self.b, ())), "the bridge is not symmetric")

    def test_a_direct_edge_is_priced_ahead_of_a_mediated_one(self):
        """A row the extraction pass joined directly is better evidence than a row that merely
        shares a concept, so it must come first in the neighbourhood's order — the vote prices
        position, so order IS the price."""
        self._graph_file(
            [{"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)]
            + [{"id": "ops_concept_x", "label": "a shared subject"}],
            [{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.b}"},
             {"source": f"ops_fact_{self.a}", "target": "ops_concept_x"},
             {"source": "ops_concept_x", "target": f"ops_fact_{self.c}"}])
        nbrs = list(self.store._graph().get(self.a, ()))
        self.assertLess(nbrs.index(self.b), nbrs.index(self.c),
                        "a mediated neighbour undercut a direct one")

    def test_a_tight_concept_outranks_a_wide_one(self):
        """Two bridges from a: one concept shared with ONE row, one shared with many. The tight
        concept is the better claim that the rows are one case, so it votes first."""
        wide = [{"id": f"ops_fact_{self.a}"}, {"id": "ops_concept_wide"}]
        links = [{"source": f"ops_fact_{self.a}", "target": "ops_concept_wide"},
                 {"source": "ops_concept_wide", "target": f"ops_fact_{self.c}"}]
        for i in range(8):                       # the wide concept's other members
            hub = self.store.remember(f"Hub member {i}: an unrelated fact about frame pacing.",
                                      klass="OPS", scope="default")["id"]
            wide.append({"id": f"ops_fact_{hub}"})
            links.append({"source": "ops_concept_wide", "target": f"ops_fact_{hub}"})
        wide += [{"id": "ops_concept_tight"}, {"id": f"ops_fact_{self.b}"}]
        links += [{"source": f"ops_fact_{self.a}", "target": "ops_concept_tight"},
                  {"source": "ops_concept_tight", "target": f"ops_fact_{self.b}"}]
        self._graph_file(wide, links)
        nbrs = list(self.store._graph().get(self.a, ()))
        self.assertLess(nbrs.index(self.b), nbrs.index(self.c),
                        "a hub concept outvoted a tight one")

    def test_a_hub_concept_does_not_flood_the_neighbourhood(self):
        """A concept touching the whole store is a table of contents, not a bridge: the arm has
        eight seeds and a block of 96 notes, so a hub must be capped."""
        from serve.memory import CONCEPT_FAN
        n = CONCEPT_FAN + 25
        nodes = [{"id": "ops_concept_hub"}, {"id": f"ops_fact_{self.a}"}]
        links = []
        for i in range(n):
            rid = self.store.remember(f"Filler fact {i} about expert cache slots.",
                                      klass="OPS", scope="default")["id"]
            nodes.append({"id": f"ops_fact_{rid}"})
            links.append({"source": "ops_concept_hub", "target": f"ops_fact_{rid}"})
        links.append({"source": "ops_fact_{self.a}", "target": "ops_concept_hub"})
        self._graph_file(nodes, links)
        got = list(self.store._graph().get(self.a, ()))
        self.assertLessEqual(len(got), CONCEPT_FAN,
                             f"a hub concept contributed {len(got)} neighbours")

    def test_the_bridge_moves_a_probe_the_direct_edge_cannot(self):
        """The product claim, end to end: a query phrased on row b's words must pull row a up
        when the only link between them is a concept, and not when the arm is off."""
        self._graph_file(
            [{"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)]
            + [{"id": "ops_concept_drafter", "label": "DFlash2 drafter"}],
            [{"source": f"ops_fact_{self.a}", "target": "ops_concept_drafter"},
             {"source": "ops_concept_drafter", "target": f"ops_fact_{self.b}"}])
        q = "accepts six proposals per step on the heretic pack"
        self.store.graph_weight = 0.0
        off = {h["id"]: h for h in self.store.search(q, limit=8)}
        self.store.graph_weight = 0.6
        on = {h["id"]: h for h in self.store.search(q, limit=8)}
        self.assertNotIn("graph_rank", off.get(self.a, {}),
                         "the arm signed a row with the weight off")
        self.assertTrue(on.get(self.a, {}).get("graph_rank"),
                        "the concept bridge cast no vote")


class LinkVote(unittest.TestCase):
    """The typed edge is an edge source too (2026-11-24).

    The store has carried three kinds of connection: the built graph's edges, the vectors' nearest
    neighbours, and the `links` table — a typed, human- and clerk-authored relation between two
    rows (`about` / `contradicts` / `supports`), 858 rows on this box, free to read and already in
    Postgres. Only the first two voted. These tests pin the third: a link the owner wrote is the
    best evidence in the building that two rows belong to one question, so it votes, and it is
    priced ahead of a link the model inferred.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="linkvote-")
        cls.store = MemoryService(cls.dir)
        cls.a = cls.store.remember("The clerk drains two batches of sixty turns per tick behind "
                                   "240 seconds of engine silence.", klass="OPS", scope="default")["id"]
        cls.b = cls.store.remember("Curation runs on a systemd timer, not a crontab, on this box.",
                                   klass="OPS", scope="default")["id"]
        cls.c = cls.store.remember("The Radeon 780M plays Starfield at 1080p medium near 60 fps.",
                                   klass="HW", scope="default")["id"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _graph_file(self, links):
        os.makedirs(os.path.join(self.dir, "strata-graphify"), exist_ok=True)
        with open(os.path.join(self.dir, "strata-graphify", "graph.json"), "w") as f:
            json.dump({"nodes": [{"id": f"ops_fact_{i}"} for i in (self.a, self.b, self.c)],
                       "links": links, "hyperedges": []}, f)
        self.store._graph_cache = None

    def _search(self, w: float, query: str = "clerk drains batches turns tick", limit: int = 8):
        """The arm's one switch, set the way the shipped tests set it — an attribute, not a kwarg:
        `search()` reads `self.graph_weight`. The store has no embedder, so the lexical arm is the
        whole of the other two, and the query shares words with `a` (the seed) and not with `b`."""
        self.store.graph_weight = w
        return {h["id"]: h for h in self.store.search(query, limit=limit)}

    def test_a_typed_link_votes_with_no_graph_file(self):
        """The layer is an edge SOURCE: with no graph on disk, a row the owner linked to a seed
        still rises, because the link is in the store and the graph is a file."""
        if os.path.isdir(os.path.join(self.dir, "strata-graphify")):
            shutil.rmtree(os.path.join(self.dir, "strata-graphify"))
        self.store._graph_cache = None
        self.store.link(self.a, self.b, kind="about")
        hits = self._search(0.6)
        self.assertIn(self.a, hits, "the seed is not in the list, so no vote can be attributed")
        self.assertTrue(hits.get(self.b, {}).get("graph_rank"),
                        "a typed link cast no vote")

    def test_a_typed_link_is_priced_ahead_of_an_inferred_one(self):
        """One seed, two sources: `c` is the graph's neighbour, `b` is the owner's. The typed
        edge is the better claim, so it must carry the better rank."""
        self._graph_file([{"source": f"ops_fact_{self.a}", "target": f"ops_fact_{self.c}",
                           "relation": "about"}])
        self.store.link(self.a, self.b, kind="supports")
        hits = self._search(0.6)
        self.assertTrue(hits.get(self.b, {}).get("graph_rank"), "the link voted nothing")
        self.assertTrue(hits.get(self.c, {}).get("graph_rank"), "the graph voted nothing")
        self.assertLess(hits[self.b]["graph_rank"], hits[self.c]["graph_rank"],
                        "an inferred edge undercut the one a hand wrote")

    def test_links_vote_only_inside_the_scopes_the_ask_can_see(self):
        """A shelf is a filing drawer and a link crossing drawers is the point of the arm, but a
        tenant's neighbours stay inside its scopes — the law `_graph_expand` already applies to
        the graph, now applied to the link read, so a `user` fact cannot reach a project ask
        through a link (14 active links crossed scopes on this store, measured 2026-11-24)."""
        p = self.store.remember("The venue box keeps its own store and its own numbers.",
                                klass="OPS", scope="project")["id"]
        self.store.link(self.a, p, kind="about")
        nbrs = self.store._link_neighbours([self.a], scopes=["default", "user"]).get(self.a, [])
        self.assertNotIn(p, nbrs, "a link pulled a row in from outside the ask's scopes")
        both = self.store._link_neighbours([self.a]).get(self.a, [])
        self.assertIn(p, both, "the unscoped read lost the cross-scope neighbour it should see")

    def test_weight_zero_leaves_the_link_signature_off(self):
        """The default path stays byte-identical: with the arm off, a link is text on the hit
        line, not a vote."""
        hits = self._search(0.0)
        self.assertNotIn("graph_rank", hits.get(self.b, {}),
                         "the arm signed a row with the weight off")


class TheVaultVerbs(unittest.TestCase):
    """The Obsidian reading of the graph (2026-11-24, the owner's ask on the Graph tab).

    The nx view is UNDIRECTED, so a relation's subject and object survive only in the raw link
    list. These three verbs are what the page's walk runs on — a note's links out vs its
    backlinks, one node's neighbourhood, and a jump by a few letters — and each test is the
    direction surviving the round trip, which is the part a graph library does not give you.
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="vault-")
        cls.store = MemoryService(cls.dir)
        cls.a = cls.store.remember("The cart rotates when a persona file moves.",
                                   klass="MEM", scope="default")["id"]
        cls.b = cls.store.remember("A rotated cart re-seeds the standing prefix.",
                                   klass="MEM", scope="default")["id"]
        cls.c = cls.store.remember("The 4090 keeps a fifth of its expert cache hot.",
                                   klass="HW", scope="default")["id"]
        cls.na, cls.nb, cls.nc = f"mem_fact_{cls.a}", f"mem_fact_{cls.b}", f"hw_fact_{cls.c}"
        cls.graph = os.path.join(cls.dir, "strata-graphify", "graph.json")
        cls._write([{"source": cls.na, "target": cls.nb, "relation": "references",
                     "confidence": "EXTRACTED"},
                    {"source": cls.nc, "target": cls.na, "relation": "conceptually_related_to",
                     "confidence": "INFERRED"}])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _write(cls, links, nodes=None):
        os.makedirs(os.path.dirname(cls.graph), exist_ok=True)
        nodes = nodes if nodes is not None else [
            {"id": cls.na, "label": "cart rotation", "community": 3},
            {"id": cls.nb, "label": "cart re-seed", "community": 3},
            {"id": cls.nc, "label": "expert cache", "community": 9}]
        with open(cls.graph, "w", encoding="utf-8") as f:
            json.dump({"directed": False, "multigraph": False, "nodes": nodes,
                       "links": links, "hyperedges": []}, f)
        # A monotone mtime: the caches key on it, and two writes in the same second would
        # otherwise look like the same graph.
        cls._seq = getattr(cls, "_seq", 0) + 1
        t = os.path.getmtime(cls.graph)
        os.utime(cls.graph, (t + cls._seq, t + cls._seq))

    def setUp(self):
        # The base graph, per test. The verbs read graph.json through a cache keyed by mtime,
        # so a test that rewrites the file (the rebuild test) would otherwise leak into every
        # test unittest runs after it — the suite's order became part of the fixture.
        self._write([{"source": self.na, "target": self.nb, "relation": "references",
                      "confidence": "EXTRACTED"},
                     {"source": self.nc, "target": self.na, "relation": "conceptually_related_to",
                      "confidence": "INFERRED"}])

    def _g(self):
        from strata.graphify import StrataGraphify
        return StrataGraphify(self.dir)

    def test_a_note_has_links_out_and_backlinks_and_they_are_not_the_same_list(self):
        d = self._g().explain(self.na)
        self.assertEqual(d["status"], "ok")
        self.assertEqual([x["to"] for x in d["links"]], [self.nb], "a references b: that is a link out")
        self.assertEqual([x["to"] for x in d["backlinks"]], [self.nc], "c references a: that is a backlink")
        self.assertEqual(d["backlinks"][0]["relation"], "conceptually_related_to")
        self.assertEqual(d["backlinks"][0]["confidence"], "INFERRED",
                         "the folded edge's confidence rides the line, not the nx view")
        self.assertEqual(len(d["connections"]), 2, "the undirected list stays for the older caller")

    def test_a_concept_note_names_the_shelf_it_was_read_from(self):
        # The note's chips: a fact node names its row, so "open in the ledger" has an address.
        d = self._g().explain(self.na)
        self.assertEqual(d["fact"], self.a)
        self.assertEqual(d["shelf"], "mem")

    def test_the_local_graph_is_one_node_centred_with_the_edges_among_its_neighbours(self):
        d = self._g().neighbourhood(self.na, depth=1)
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["id"], self.na)
        self.assertEqual({n["id"] for n in d["nodes"]}, {self.na, self.nb, self.nc})
        self.assertEqual([n["id"] for n in d["nodes"] if n["hub"]], [self.na],
                         "the note you opened is the centre of its own graph")
        self.assertEqual(len(d["edges"]), 2)
        self.assertEqual(d["edges"][0][2], "references",
                         "an edge carries the relation, so the page can NAME the line")

    def test_depth_two_walks_through_the_hub_a_one_hop_walk_cannot_see(self):
        # b is linked only to a; at depth 2 it reaches c, which touches a and nothing else.
        one = self._g().neighbourhood(self.nb, depth=1)
        two = self._g().neighbourhood(self.nb, depth=2)
        self.assertNotIn(self.nc, {n["id"] for n in one["nodes"]})
        self.assertIn(self.nc, {n["id"] for n in two["nodes"]})

    def test_an_unknown_node_says_so_rather_than_drawing_nothing(self):
        self.assertEqual(self._g().neighbourhood("no_such_node")["status"], "not-found")
        self.assertEqual(self._g().explain("no_such_node")["status"], "not-found")

    def test_the_switcher_finds_a_note_by_a_few_letters_and_ranks_a_prefix_first(self):
        g = self._g()
        hits = g.switcher("cart")["hits"]
        self.assertEqual({h["id"] for h in hits}, {self.na, self.nb})
        self.assertEqual(hits[0]["fact"], self.a, "the label starts with the typed word")
        self.assertEqual(g.switcher("zzzq")["hits"], [], "no match is an honest empty list")
        hubs = g.switcher("")["hits"]                     # empty query: the graph's hubs
        self.assertEqual(hubs[0]["id"], self.na, "a is the only degree-2 node")
        self.assertEqual(hubs[0]["degree"], 2)

    def test_a_rebuilt_graph_is_the_graph_the_page_draws(self):
        # The raw-link cache is stamped by mtime, like the nx view: a rebuild must be seen,
        # because the nightly pass rewrites graph.json under the running server.
        self._write([{"source": self.nb, "target": self.nc, "relation": "supports",
                      "confidence": "EXTRACTED"}])
        d = self._g().explain(self.nb)
        self.assertEqual([x["to"] for x in d["links"]], [self.nc])
        self.assertEqual(d["backlinks"], [])


if __name__ == "__main__":
    unittest.main()
