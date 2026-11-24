#!/usr/bin/env python3
"""The row↔code seam (2026-11-24, the merge): one path, three spellings, one answer.

The store's DEC rows name files the way the speaker said them — `serve/memory.py` from inside
terminal/, `docs/MEMORY_CORE.md` from the repo root, `m7_consolidate.py` with no directory at all.
graphify's graph keys nodes on the repo-relative path. The seam is the only thing between "this
decision is stale" and "this decision lives at terminal/serve/memory.py", so the tests are the
spellings.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from serve.codegraph import CodeGraph        # noqa: E402

GRAPH = {
    "nodes": [
        {"id": "terminal_serve_memory_memoryservice", "label": "MemoryService",
         "source_file": "terminal/serve/memory.py", "source_location": "L1183", "type": "class"},
        {"id": "terminal_serve_memory_search", "label": "search",
         "source_file": "terminal/serve/memory.py", "source_location": "L2923", "type": "function"},
        {"id": "terminal_tools_m7_consolidate_ladder", "label": "ladder",
         "source_file": "terminal/tools/m7_consolidate.py", "type": "function"},
        {"id": "docs_memory_core", "label": "MEMORY_CORE.md",
         "source_file": "docs/MEMORY_CORE.md", "type": "file"},
        {"id": "app_host_server_index", "label": "index",
         "source_file": "app/host/server/index.mjs", "type": "function"},
    ],
    "edges": [{"source": "terminal_serve_memory_memoryservice",
               "target": "terminal_serve_memory_search", "relation": "contains"}],
}


class TheSeam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "repo").mkdir()
        (self.tmp / "repo" / "terminal").mkdir()
        (self.tmp / "repo" / "terminal" / "serve").mkdir()
        (self.tmp / "repo" / "terminal" / "serve" / "memory.py").write_text("x = 1\n")
        (self.tmp / "repo" / "docs").mkdir()
        (self.tmp / "repo" / "docs" / "MEMORY_CORE.md").write_text("# hi\n")
        g = self.tmp / "repo" / "graphify-out"
        g.mkdir()
        (g / "graph.json").write_text(json.dumps(GRAPH), encoding="utf-8")
        self.cg = CodeGraph(g / "graph.json",
                            roots=[self.tmp / "repo", self.tmp / "repo" / "terminal"])

    def test_the_three_spellings_of_one_file_all_resolve(self):
        for name in ("serve/memory.py", "terminal/serve/memory.py", "memory.py"):
            r = self.cg.resolve(name)
            self.assertTrue(r["live"], f"{name} resolved to nothing")
            self.assertEqual(r["nodes"][0]["node"], "terminal_serve_memory_memoryservice",
                             f"{name} found the wrong nodes")
        # Only the two directory-qualified spellings are on disk from these roots: a bare
        # `memory.py` is a real file at terminal/serve/, and the graph is what says so.
        self.assertTrue(self.cg.resolve("serve/memory.py")["on_disk"])
        self.assertFalse(self.cg.resolve("memory.py")["on_disk"],
                         "the disk answer is the disk answer; the graph supplies the rest")

    def test_a_path_that_only_the_graph_knows_is_still_live(self):
        # app/host/server/index.mjs is not in this fixture's roots, but the graph has its nodes:
        # a citation to it is a live claim about the repo, not a stale one.
        r = self.cg.resolve("app/host/server/index.mjs")
        self.assertFalse(r["on_disk"])
        self.assertTrue(r["live"], "the graph is the second witness")
        self.assertEqual(r["nodes"][0]["label"], "index")

    def test_a_gone_path_is_not_live_and_says_which_roots_it_tried(self):
        r = self.cg.resolve("terminal/serve/gone.py")
        self.assertFalse(r["live"])
        self.assertEqual(r["nodes"], [])
        self.assertEqual(len(r["roots"]), 2, "the answer names where it looked")

    def test_two_files_sharing_a_leaf_name_stay_distinct(self):
        # The suffix index is the last two segments, so `docs/README.md` and `app/README.md` are
        # two answers, not one bucket.
        (self.tmp / "repo" / "terminal" / "tools").mkdir()
        r = self.cg.resolve("tools/m7_consolidate.py")
        self.assertEqual(r["nodes"][0]["label"], "ladder")

    def test_the_cache_follows_the_graphs_mtime(self):
        first = self.cg.stats()["nodes"]
        g = self.tmp / "repo" / "graphify-out" / "graph.json"
        data = json.loads(g.read_text(encoding="utf-8"))
        data["nodes"].append({"id": "new_node", "label": "new", "source_file": "docs/NEW.md"})
        g.write_text(json.dumps(data), encoding="utf-8")
        import os
        os.utime(g, (g.stat().st_atime + 5, g.stat().st_mtime + 5))
        self.assertEqual(self.cg.stats()["nodes"], first + 1,
                         "the nightly AST refresh is picked up without a restart")

    def test_the_seam_costs_one_parse_for_every_caller(self):
        from serve.codegraph import default_graph
        a = default_graph(self.tmp / "repo" / "graphify-out" / "graph.json")
        b = default_graph()
        self.assertIs(a, b, "the process shares one index")

    def test_the_embedding_sidecar_adds_the_meaning_hop(self):
        # The sidecar is m11's output format: node-id pairs with a cosine, stamped with the
        # store's embedder. Absent = no section; present = `related` rides the node.
        side = self.tmp / "repo" / "graphify-out" / "semantic.json"
        side.write_text(json.dumps({"pairs": [
            {"source": "terminal_serve_memory_search", "target": "docs_memory_core",
             "cos": 0.87, "relation": "semantically_similar_to"}]}), encoding="utf-8")
        cg = CodeGraph(self.tmp / "repo" / "graphify-out" / "graph.json",
                       roots=[self.tmp / "repo"], sidecar=side)
        r = cg.related("terminal_serve_memory_search")
        self.assertEqual(r[0]["node"], "docs_memory_core")
        self.assertEqual(r[0]["cos"], 0.87)
        node = cg.nodes_for("serve/memory.py")[1]
        self.assertEqual(node["node"], "terminal_serve_memory_search")
        self.assertEqual(node["related"][0]["label"], "MEMORY_CORE.md")
        # a graph with no sidecar written yet is a normal day, not an error
        side.unlink()
        self.assertEqual(cg.related("terminal_serve_memory_search"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
