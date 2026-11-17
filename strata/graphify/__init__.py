"""strata.graphify — the memory store's own knowledge graph, built inside Strata.

Why this is a package and not a shell-out: the graph is part of the memory system, so it
travels with the store. Everything it writes lives beside the data, in
`<store>/strata-graphify/`, and a box that clones the store gets the graph with it.

What it does. The store keeps facts as rows on shelves. A graph pass reads the fact text
and asks the served model what belongs with what: which facts are one case, which decision
a measurement supports, which two rows talk about the same subsystem. The result is nodes,
edges, hyperedges (a case with several facts in it) and communities (what the graph, not
the clerk, thinks the shelves are).

The measured shape of a pass, on this box (RTX 4090, Qwen3.8-Flash-Next IQ4_NL):

  prefill ~4,000-5,500 tok/s, decode ~90 tok/s — so a pass is bound by OUTPUT, not input.
  8 corpus files (25 facts each) is one chunk: 225,918 in / 70,741 out, ~10 min, and the
  answer came back whole. 25 files per chunk hit the 16,384-token output cap and truncated.
  Concurrency 1: four parallel chunks against one GPU timed out (the conversation cache
  thrashes when four 100K-token prompts land together).

Files, all under <store>/strata-graphify/:

  graph.json     the graph, networkx node-link format (nodes, links, hyperedges)
  analysis.json  communities + cohesion + god nodes
  view.json      the compact form the web page draws
  state.json     last successful build: counts, watermark, model
  pending.json   fact ids stored since the last pass, waiting for the next one
  state/lock     the build lock, so two passes cannot write graph.json together
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_STORE = "/home/eugene/Strata-data/memory-eval"
DIR_NAME = "strata-graphify"

WORDS = re.compile(r"[a-z0-9]+")           # the query verbs' tokenizer: one rule for all

# networkx view cache: (graph.json mtime, G). The page and the CLI ask between rebuilds;
# a rebuild costs one parse, not one per query call.
_NX_CACHE: dict = {}

# One chunk = 4 files. Measured on this box: 8 files per chunk costs 70,741 output tokens and
# lands whole, and yields ~7 concepts per chunk; 4 files costs about half as much per call and
# yields roughly the same per file, so it doubles the number of chunks — ~2.2 h for the whole
# store, about twice the rows the graph names. 25 files ran past the model's 16,384-token
# completion ceiling and re-extracted.
FILES_PER_CHUNK = int(os.environ.get("STRATA_GRAPHIFY_CHUNK", "4"))
FACTS_PER_FILE = 25
MAX_CONCURRENCY = 1

# The graph pass talks to the same server that serves the conversation, through the
# OpenAI-compatible API. This box serves with no key (`api_key: false` in /health), so
# the key is a placeholder for the openai client's non-empty requirement, not a secret.
# graphify reads these once, when it builds its backend table at import, so they are set
# HERE: a base URL set inside a call is too late and the pass goes to api.openai.com
# (measured: 401 "Incorrect API key provided: dummy").
API_URL = os.environ.get("STRATA_GRAPHIFY_URL", "http://127.0.0.1:8005/v1")
GRAPH_KEY = os.environ.get("STRATA_GRAPHIFY_KEY", "not-needed")
os.environ.setdefault("OPENAI_BASE_URL", API_URL)
os.environ.setdefault("OPENAI_API_KEY", GRAPH_KEY)
# Ask for the box's full output ceiling. graphify's own default is 8,192 tokens, which is
# HALF of what this boot samples (max_tokens 16,384 per /completion-sampler), so a chunk
# that needed 10,000 tokens came back cut in half and got re-extracted — a wasted pass.
# Above 16,384 the sampler caps it anyway, so the real anti-truncation lever stays chunk
# size: graphify bisects a cut chunk (measured: "chunk of 14 … splitting into halves of 7
# and 7"), and 8 files per chunk is the size that lands under the ceiling whole.
os.environ.setdefault("GRAPHIFY_MAX_OUTPUT_TOKENS", "16384")

# The model is not pinned. A pass asks the running server what it is serving, so a switch to
# Qwen 3.6-35B-A3B, to Qwen 4 when it lands, to a new quant or pack — needs no change here.
# The answer is cached per process; `STRATA_GRAPHIFY_MODEL` overrides it for a side-by-side.
_MODEL_CACHE: list = []

# graph.json coverage cache, keyed by path: (file mtime, frozenset of cited fact ids). The
# page polls summary/view every refresh and cover() asks uncovered() between passes; after a
# full drain graph.json is megabytes, so the parse is paid once per rebuild, not once per ask.
_COV_CACHE: dict = {}


def served_model(base_url: str | None = None) -> str:
    """The model id the server reports, from /health, then /models. Env wins if set."""
    if os.environ.get("STRATA_GRAPHIFY_MODEL"):
        return os.environ["STRATA_GRAPHIFY_MODEL"]
    if _MODEL_CACHE and base_url is None:
        return _MODEL_CACHE[0]
    import urllib.request

    root = (base_url or API_URL).rstrip("/")
    for path, key in ((root + "/health", "model"), (root + "/models", None)):
        try:
            with urllib.request.urlopen(path, timeout=10) as r:
                data = json.load(r)
        except Exception:                                       # noqa: BLE001 - try the next form
            continue
        found = data.get(key) if key else next(
            (m.get("id") for m in (data.get("data") or []) if m.get("id")), None)
        if found:
            if base_url is None:
                _MODEL_CACHE.clear()
                _MODEL_CACHE.append(found)
            return found
    return "strata"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StrataGraphify:
    """Builds and owns the graph that lives inside a memory store."""

    def __init__(self, store_dir: str = DEFAULT_STORE):
        self.store_dir = Path(store_dir)
        self.dir = self.store_dir / DIR_NAME
        self.corpus = self.dir / "corpus"
        self.graph_path = self.dir / "graph.json"
        self.analysis_path = self.dir / "analysis.json"
        self.view_path = self.dir / "view.json"
        self.state_path = self.dir / "state.json"
        self.pending_path = self.dir / "pending.json"
        self.progress_path = self.dir / "progress.json"
        self.lock_path = self.dir / "state"

    # ---------------------------------------------------------------- paths
    def _ensure(self) -> None:
        (self.dir / "state").mkdir(parents=True, exist_ok=True)
        self.corpus.mkdir(parents=True, exist_ok=True)

    def _read(self, path: Path, default=None):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {} if default is None else default

    def _write(self, path: Path, payload) -> None:
        self._ensure()
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, path)          # a reader never sees half a file

    # ---------------------------------------------------------------- facts
    def facts(self, ids: Optional[Iterable[int]] = None) -> list[tuple]:
        """Live facts from the store: (id, class, text, created_at, confidence).

        Facts are the rows whose source is not the doc index; the chunks are a routing
        map over files and would bury the 3k facts under 33k quotes.
        """
        from serve.memory import attach

        conn = attach(str(self.store_dir))
        try:
            where = "invalid_at IS NULL AND source NOT LIKE 'doc-index%%'"
            args: list = []
            if ids:
                where += " AND id = ANY(%s)"
                args.append(list(ids))
            rows = conn.execute(
                "SELECT id, class, text, created_at, confidence FROM memories "
                f"WHERE {where} ORDER BY class, created_at", args).fetchall()
        finally:
            conn.close()
        return rows

    def write_corpus(self, rows: list[tuple], per_file: int = FACTS_PER_FILE) -> list[Path]:
        """Fact rows → markdown files, one part per slice of a shelf.

        Returns the file paths written, sorted, so a pass is reproducible from the rows.
        """
        self._ensure()
        from collections import defaultdict

        import re
        slug = re.compile(r"[^a-z0-9]+")
        by_shelf: dict[str, list] = defaultdict(list)
        for row in rows:
            by_shelf[row[1] or "UNSHELVED"].append(row)

        out: list[Path] = []
        for cls, items in sorted(by_shelf.items()):
            name = slug.sub("-", cls.lower()).strip("-") or "unshelved"
            split = len(items) > per_file
            for part, start in enumerate(range(0, len(items), per_file), 1):
                slice_ = items[start:start + per_file]
                body = [f"# {cls}" + (f" — part {part}" if split else "") + "\n",
                        f"{len(slice_)} facts from the Strata memory store.\n"]
                for rid, _, text, created, conf in slice_:
                    body.append(f"## fact {rid}\nSaid {created} · confidence {conf}\n\n"
                                f"{(text or '').strip()}\n")
                suffix = f"-{part:02d}" if split else ""
                p = self.corpus / f"{name}{suffix}.md"
                p.write_text("\n".join(body), encoding="utf-8")
                out.append(p)
        return sorted(out)

    # ---------------------------------------------------------------- pass
    def _chunks(self, files: list[Path], size: int = FILES_PER_CHUNK) -> list[list[Path]]:
        size = max(1, int(size))
        return [files[i:i + size] for i in range(0, len(files), size)]

    def _extract(self, chunk: list[Path]) -> dict:
        """One LLM pass over one chunk, through the installed graphify library."""
        from graphify import llm

        os.environ.setdefault("OPENAI_API_KEY", GRAPH_KEY)
        os.environ["OPENAI_BASE_URL"] = API_URL
        os.environ["OPENAI_MODEL"] = served_model()
        return llm.extract_files_direct(
            list(chunk), backend="openai", api_key=GRAPH_KEY,
            model=served_model(), root=self.corpus)

    @staticmethod
    def _merge_extractions(parts: list[dict]) -> dict:
        nodes, edges, hyper = [], [], []
        tin = tout = 0
        for p in parts:
            nodes += p.get("nodes") or []
            edges += p.get("edges") or []
            hyper += p.get("hyperedges") or []
            tin += int(p.get("input_tokens") or 0)
            tout += int(p.get("output_tokens") or 0)
        return {"nodes": nodes, "edges": edges, "hyperedges": hyper,
                "input_tokens": tin, "output_tokens": tout}

    def build(self, ids: Optional[Iterable[int]] = None, full: bool = True,
              files_per_chunk: int = FILES_PER_CHUNK, per_file: int = FACTS_PER_FILE,
              corpus_files: Optional[list[Path]] = None, on_progress=None) -> dict:
        """Run a graph pass and persist it. `full` rebuilds every shelf; otherwise the
        existing graph is kept and the new rows are merged into it (build_merge), so a
        curated fact joins the graph it belongs to instead of replacing the file.

        `per_file` is the density knob: the model writes about one concept per 1.5 facts at
        10 facts a file, and one per 15 facts at 25 a file. Smaller files name more of the
        store per pass, which is what `cover` runs on.
        """
        import networkx as nx
        from graphify import analyze, build as gbuild, cluster as gcluster, export as gexport

        self._ensure()
        if corpus_files:
            # A bridge pass reads a file the graph wrote about itself, not the store.
            files, rows = list(corpus_files), self.facts(None)
        else:
            rows = self.facts(ids)
            if not rows:
                return {"status": "empty", "message": "no facts to graph"}
            files = self.write_corpus(rows, per_file=per_file)
        files_per_chunk = files_per_chunk or FILES_PER_CHUNK
        chunks = self._chunks(files, files_per_chunk)
        total = len(chunks)
        parts, done, t0 = [], 0, time.time()
        for chunk in chunks:
            parts.append(self._extract(chunk))
            done += 1
            if on_progress:
                on_progress(done, total, len(files))
        extraction = self._merge_extractions(parts)

        # The mode question is answered BEFORE the export: after gexport writes graph.json,
        # "does the file exist?" is always yes and a first merge pass would stamp itself
        # "merge" while it actually rebuilt the file (reporting bug found in the 2026-11-16 audit).
        # Full = read every shelf; merge = keep what the graph already learned. The two are
        # orthogonal (2026-11-17): a full pass over all shelves should ADD to the standing
        # graph, not replace it - the first full pass after a cover drain used to flatten
        # ~1,400 accumulated named rows back to one pass's ~130. Only the first build, with
        # no graph on disk, writes from nothing.
        if self.graph_path.exists():
            G = gbuild.build_merge([extraction], graph_path=self.graph_path, root=self.corpus)
        else:
            G = gbuild.build_from_json(extraction, root=self.corpus)
        communities = gcluster.cluster(G)
        cohesion = gcluster.score_all(G, communities)
        gexport.to_json(G, communities, str(self.graph_path), force=True)

        self._write(self.analysis_path, {
            "communities": {str(k): v for k, v in communities.items()},
            "cohesion": {str(k): v for k, v in cohesion.items()},
            "gods": analyze.god_nodes(G, top_n=12),
        })
        # hyperedges counts the WHOLE graph (the file just written carries the merged set), not
        # this pass's extraction: on a merge pass the extraction count is the delta, and the
        # tile read it as the total (2026-11-16 audit). watermark is the store's max id, not the
        # subset's: a cover pass reads a queue whose top id sits below the newest fact, and the
        # tile's "read through" stamp must name the newest row the store holds.
        whole = self._read(self.graph_path)
        state = {
            "built": _now(), "seconds": round(time.time() - t0, 1),
            "facts": len(rows), "files": len(files), "chunks": total,
            # in_graph is the coverage the tile shows, recorded at build time so a sweep can
            # read it out of state.json without re-parsing the graph.
            "in_graph": self.coverage().get("in_graph", 0),
            "nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
            "hyperedges": len(whole.get("hyperedges") or []),
            "communities": len(communities),
            "tokens_in": extraction["input_tokens"], "tokens_out": extraction["output_tokens"],
            "model": served_model(), "watermark": self._store_max_id(),
            "store_facts": self._n_facts(),
            "mode": "full" if full else "merge",       # read scope: all shelves, or the queue
        }
        self._write(self.state_path, state)
        self.write_view()
        return {"status": "ok", **state}

    def build_in_background(self, ids=None, full: bool = True) -> dict:
        """Start a pass on a worker thread and return at once.

        A pass is tens of minutes of decode, and the web page must stay readable through
        it, so the pass runs off the request thread and writes progress.json as it goes.
        One pass at a time: a second would double the pressure on the same GPU.
        """
        import threading

        prog = self._progress()
        if prog.get("running"):
            return {"status": "running", **prog}
        # Claim the pass BEFORE the thread starts: a caller that polls immediately would
        # otherwise read the previous run's file and report it as this pass's verdict.
        self._write(self.progress_path, {"running": True, "started": _now(), "pid": os.getpid(),
                                         "done": 0, "total": 0, "mode": "full" if full else "merge"})

        def run():
            try:
                res = self.build(
                    ids=ids, full=full,
                    on_progress=lambda d, t, n: self._write(self.progress_path, {
                        "running": True, "started": _now(), "pid": os.getpid(),
                        "done": d, "total": t, "files": n,
                        "mode": "full" if full else "merge"}))
                self._write(self.progress_path, {"running": False, "finished": _now(),
                                                 "pid": os.getpid(),
                                                 "done": res.get("chunks", 0),
                                                 "total": res.get("chunks", 0),
                                                 "mode": res.get("mode"), "result": res})
                self.clear_pending()
            except Exception as exc:                          # noqa: BLE001 - the page must see the reason
                self._write(self.progress_path, {"running": False, "finished": _now(),
                                                 "pid": os.getpid(),
                                                 "error": f"{type(exc).__name__}: {exc}"})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started", "mode": "full" if full else "merge"}

    # ---------------------------------------------------------------- views
    @staticmethod
    def _alive(prog: dict) -> bool:
        """Is a recorded pass really running? progress.json outlives its writer.

        A killed CLI leaves `running: true` on disk, and the page would then wait on a
        pass that stopped hours ago, so liveness is checked against the writing pid.
        """
        if not prog.get("running"):
            return False
        pid = prog.get("pid")
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
        except OSError:
            return False
        return True

    def _progress(self) -> dict:
        prog = self._read(self.progress_path)
        if prog.get("running") and not self._alive(prog):
            return {**prog, "running": False,
                    "error": f"pass died at pid {prog.get('pid')} - progress is stale, not live"}
        return prog

    def summary(self) -> dict:
        """What the page's tiles and the CLI print. Never raises on a missing graph."""
        state = self._read(self.state_path)
        prog = self._progress()
        has = self.graph_path.exists()          # a graph on disk is the truth; state.json is
        cov = self.coverage() if has else {"in_graph": 0}   # only the record of building it
        out = {
            "status": "ready" if (state or has) else "empty",
            "nodes": state.get("nodes", 0), "edges": state.get("edges", 0),
            "hyperedges": state.get("hyperedges", 0),
            "communities": state.get("communities", 0),
            # facts is the LIVE store count — the coverage denominator the page prints. A cover
            # pass reads a queue whose count is not the store's, and the tile was dividing by
            # it (2026-11-16 audit); facts_read keeps the old number visible.
            "facts": state.get("store_facts") or self._n_facts(),
            "facts_read": state.get("facts", 0),
            "in_graph": cov.get("in_graph", 0),
            "built": state.get("built"), "seconds": state.get("seconds"),
            "model": state.get("model"), "mode": state.get("mode"),
            "pending": len(self._read(self.pending_path, {}).get("ids", [])),
            # god nodes: what everything flows through — the graph's own top-of-mind, from
            # analysis.json written at build time (no LLM, no recompute).
            "gods": (self._read(self.analysis_path).get("gods") or [])[:12],
            "running": bool(prog.get("running")),
            "progress": {"done": prog.get("done"), "total": prog.get("total"),
                         "files": prog.get("files")} if prog.get("running") else None,
            "error": prog.get("error") if not prog.get("running") else None,
            "graph_path": str(self.graph_path),
        }
        if not (state or has):
            out["message"] = "No graph yet. Press Build, or run: python -m strata.graphify.cli build"
        return out

    def view(self, max_communities: int = 60) -> dict:
        """The compact form the page draws: every node, its community, and the edges between.

        Kept small on purpose — the page only needs id, label, community, degree. Edges ride
        as INDEX PAIRS into `nodes`, so the canvas draws the real graph and not a bubble per
        community; an endpoint outside the kept set drops that one edge.
        """
        g = self._read(self.graph_path)
        analysis = self._read(self.analysis_path)
        if not g:
            return {"nodes": [], "edges": [], "communities": []}
        member_of: dict[str, int] = {}
        for cid, members in (analysis.get("communities") or {}).items():
            for m in members:
                member_of[m] = int(cid)
        degree: dict[str, int] = {}
        for e in g.get("links") or []:
            degree[e.get("source")] = degree.get(e.get("source"), 0) + 1
            degree[e.get("target")] = degree.get(e.get("target"), 0) + 1

        def fact_of(nid) -> Optional[int]:
            # Node ids are `<shelf>_fact_<row id>` (the corpus writes one heading per fact), so
            # a node links straight back to its ledger row.
            parts = str(nid or "").rsplit("_fact_", 1)
            return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else None

        nodes = [{"id": n.get("id"), "label": (n.get("label") or "")[:220],
                  "community": member_of.get(n.get("id"), -1),
                  "degree": degree.get(n.get("id"), 0), "fact": fact_of(n.get("id"))}
                 for n in g.get("nodes") or []]
        sizes = {}
        for n in nodes:
            sizes[n["community"]] = sizes.get(n["community"], 0) + 1
        keep = {c for c, _ in sorted(sizes.items(), key=lambda kv: -kv[1])[:max_communities]}
        kept = [n for n in nodes if n["community"] in keep]
        at = {n["id"]: i for i, n in enumerate(kept)}
        edges = []
        for e in g.get("links") or []:
            s, t = at.get(e.get("source")), at.get(e.get("target"))
            if s is not None and t is not None:
                edges.append([s, t])
        # A community is NAMED for its best-connected member, the same convention graphify's
        # report uses: the hub is what the cluster is about. No LLM, no cloud — a max() over
        # degrees the graph already carries.
        stored = analysis.get("community_labels") or {}
        comms = []
        for c in sorted(keep):
            members = [n for n in kept if n["community"] == c]
            hub = max(members, key=lambda n: n["degree"]) if members else None
            comms.append({"id": c, "size": sizes[c],
                          "label": stored.get(str(c))
                                   or ((hub or {}).get("label") or f"community {c}")[:60]})
        return {"nodes": kept, "edges": edges, "communities": comms,
                "links_total": len(g.get("links") or []),
                "nodes_total": len(g.get("nodes") or [])}

    def write_view(self, max_communities: int = 40) -> dict:
        """Materialise view.json from the graph, so the page fetches a file, not a parse."""
        data = self.view(max_communities=max_communities)
        self._write(self.view_path, data)
        return data

    def read_view(self, max_communities: int = 40) -> dict:
        """view.json when it is as fresh as graph.json, a recomputed view otherwise.

        The page's Graph tab polls this every refresh; after a full drain graph.json is
        megabytes and the parse is the whole cost of a poll. The build stamps view.json
        last, so "view.json mtime >= graph.json mtime" means it describes the current
        graph. A caller asking for a non-default community count gets a fresh compute -
        the materialised file is cut for the page's 40.
        """
        if max_communities == 40 and self.view_path.exists() and self.graph_path.exists():
            try:
                if self.view_path.stat().st_mtime >= self.graph_path.stat().st_mtime:
                    data = self._read(self.view_path)
                    if data.get("nodes"):
                        return data
            except OSError:
                pass
        return self.view(max_communities=max_communities)

    def coverage(self) -> dict:
        """Facts in the graph over facts in the store — the number the tile shows.

        A node is a concept the model lifted out of the fact text, so the node count is not
        the coverage: one node can cite a dozen rows, and a row can be cited by none. The
        honest read is the set of row ids the graph actually names. Node ids carry them
        (`<shelf>_fact_<id>`), so coverage is a suffix count over the ids on disk —
        through `_named_ids`, which caches the parse by file mtime.
        """
        ids = self._named_ids()
        return {"in_graph": len(ids), "graph_ids": sorted(ids)[:20]}

    def _named_ids(self) -> set[int]:
        """The fact ids the graph's nodes and hyperedges cite, cached by graph.json mtime.

        summary(), coverage(), uncovered() and the cover loop all ask the same question of
        the same file within seconds of each other, and after a full drain graph.json is
        megabytes — one parse per rebuild, not one per poll (2026-11-16 optimization).
        """
        key = str(self.graph_path)
        try:
            stamp = os.path.getmtime(self.graph_path)
        except OSError:
            return set()                        # no graph file yet: nothing is named
        hit = _COV_CACHE.get(key)
        if hit and hit[0] == stamp:
            return set(hit[1])
        g = self._read(self.graph_path)
        ids: set[int] = set()
        pool = list(g.get("nodes") or [])
        for h in g.get("hyperedges") or []:
            pool += [{"id": m} for m in (h.get("members") or h.get("nodes") or [])]
        for n in pool:
            s = str(n.get("id") if isinstance(n, dict) else n)
            if "_fact_" in s:
                tail = s.rsplit("_fact_", 1)[1]
                if tail.isdigit():
                    ids.add(int(tail))
        _COV_CACHE[key] = (stamp, frozenset(ids))
        return ids

    def uncovered(self) -> list[int]:
        """Live fact ids that no node cites. This is the queue `cover` drains."""
        named = self._named_ids()
        return [r[0] for r in self._rows_meta() if r[0] not in named]

    def _rows_meta(self) -> list[tuple]:
        from serve.memory import attach
        try:
            conn = attach(str(self.store_dir))      # attach takes a path STRING
        except Exception:                            # a box with no cluster up yet: no queue
            return []
        try:
            return conn.execute(
                "SELECT id FROM memories WHERE invalid_at IS NULL AND source NOT LIKE 'doc-index%%' "
                "ORDER BY id").fetchall()
        finally:
            conn.close()

    def _store_max_id(self) -> int:
        """The newest live fact id in the store — the state's watermark, store-wide.
        Derived from _rows_meta (ids ASC), so one guarded attach serves all three readers."""
        rows = self._rows_meta()
        return rows[-1][0] if rows else 0

    def _n_facts(self) -> int:
        return len(self._rows_meta())

    def cover(self, per_file: int = 10, files_per_chunk: int = 6, max_passes: int = 12,
              on_progress=None) -> dict:
        """Drain the store into the graph: repeated merge passes over the rows no node names yet.

        Why passes and not one big pass: a pass reads everything and the model writes about one
        concept per 1.5-15 facts depending on file size, so a single pass names a slice of the
        store. The rows it skipped are still live, still searchable by word and cosine, and
        invisible to the graph arm. Each cover pass re-reads ONLY those rows, at 10 facts a
        file — the density that makes the model name a fact rather than summarise a shelf — and
        merges into the standing graph. The queue shrinks monotonically, so the run ends.
        """
        passes, started = 0, time.time()
        before = len(self.uncovered())
        while passes < max_passes:
            todo = self.uncovered()
            if not todo:
                break
            passes += 1
            self._write(self.progress_path, {"running": True, "started": _now(),
                                             "pid": os.getpid(), "mode": "cover",
                                             "pass": passes, "queued": len(todo),
                                             "done": 0, "total": 0})
            res = self.build(ids=todo, full=False, per_file=per_file,
                             files_per_chunk=files_per_chunk,
                             on_progress=lambda d, t, n: self._write(self.progress_path, {
                                 "running": True, "started": _now(), "pid": os.getpid(),
                                 "mode": "cover", "pass": passes, "queued": len(todo),
                                 "files": n, "done": d, "total": t}))
            if on_progress:
                on_progress(passes, res)
            if res.get("status") != "ok":
                break
            after = len(self.uncovered())
            if after >= before:               # the plateau law: a pass that names nothing new
                break                         # will not name anything new tomorrow
            before = after
        self._write(self.progress_path, {"running": False, "finished": _now(), "pid": os.getpid(),
                                         "mode": "cover", "pass": passes})
        s = self.summary()
        s["cover_passes"] = passes
        s["cover_seconds"] = round(time.time() - started, 1)
        s["uncovered"] = len(self.uncovered())
        return s

    def bridge(self, members_per_community: int = 12, max_communities: int = 90) -> dict:
        """One pass over the graph's OWN groups, to put edges between the communities.

        A cover drain makes the graph wide; the groups stay islands, and the recall arm spends
        its votes along edges. This writes a corpus file naming each community by its
        highest-degree members and asks the model what connects one group's case to another's.
        Cheap by construction: 90 groups × 12 members is a few chunks, not the store.
        """
        analysis = self._read(self.analysis_path)
        g = self._read(self.graph_path)
        if not g:
            return {"status": "empty", "message": "no graph to bridge"}
        labels = {n.get("id"): (n.get("label") or "") for n in (g.get("nodes") or [])}
        deg: dict[str, int] = {}
        for e in g.get("links") or []:
            deg[e.get("source")] = deg.get(e.get("source"), 0) + 1
            deg[e.get("target")] = deg.get(e.get("target"), 0) + 1
        blocks = []
        comms = sorted((analysis.get("communities") or {}).items(),
                       key=lambda kv: -len(kv[1]))[:max_communities]
        for cid, members in comms:
            top = sorted(members, key=lambda m: -deg.get(m, 0))[:members_per_community]
            text = "\n".join(f"- {labels.get(m, '')[:200]}" for m in top if labels.get(m))
            if text:
                blocks.append(f"## community {cid}\n{text}\n")
        self._write(self.progress_path, {"running": True, "started": _now(), "pid": os.getpid(),
                                         "mode": "bridge", "done": 0, "total": len(blocks)})
        path = self.corpus / "bridges.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# The graph's own groups\n\nEach section is one community, named by its "
                        "best-connected members. What connects these cases to each other?\n\n"
                        + "\n".join(blocks), encoding="utf-8")
        res = self.build(corpus_files=[path], full=False)
        self._write(self.progress_path, {"running": False, "finished": _now(), "pid": os.getpid(),
                                         "mode": "bridge", "result": res})
        return res

    # ---------------------------------------------------------------- queries
    # The read side of the graph (2026-11-16, the owner's "once the graph is built you QUERY
    # it"): explain one node, path between two, query in plain words. All three read
    # graph.json through one cached networkx view, and all three answer from the store's own
    # row when a node names one — the node is the map, the row is the territory.

    def _G(self):
        """The networkx graph, loaded once per rebuild (cache keyed by graph.json mtime)."""
        import networkx as nx

        key = str(self.graph_path)
        try:
            stamp = os.path.getmtime(self.graph_path)
        except OSError:
            return nx.Graph()
        hit = _NX_CACHE.get(key)
        if hit and hit[0] == stamp:
            return hit[1]
        g = self._read(self.graph_path)
        G = nx.node_link_graph(g, edges="links") if g else nx.Graph()
        _NX_CACHE[key] = (stamp, G)
        return G

    def _resolve(self, name: str) -> str | None:
        """A node id from a fact number ('1519', 'fact 1519'), an exact id, or a label
        substring — best match wins, ties by degree, so 'graphify' explains the hub."""
        G = self._G()
        if not G.number_of_nodes():
            return None
        s = str(name).strip()
        if not s:
            return None
        want = s.lower()
        digits = want.replace("fact", "").strip()
        if digits.isdigit():
            cands = [nid for nid in G.nodes if str(nid).endswith(f"_fact_{digits}")]
            if cands:
                return max(cands, key=lambda n: G.degree(n))
        if s in G.nodes:
            return s
        cands = [nid for nid, attrs in G.nodes(data=True)
                 if want == str(nid).lower() or want in (attrs.get("label") or "").lower()]
        if not cands:                                    # any word of the name in a label
        #  rare words carry the match: 'graphify concurrency' should find the concurrency hub
            toks = [t for t in WORDS.findall(want) if len(t) > 3]
            for nid, attrs in G.nodes(data=True):
                if any(t in (attrs.get("label") or "").lower() for t in toks):
                    cands.append(nid)
        if not cands:
            return None
        return max(cands, key=lambda n: G.degree(n))

    @staticmethod
    def _edge_attrs(G, u: str, v: str) -> dict:
        """One edge's attributes, MultiGraph-safe: graphify folds parallel edges as keys
        (the `also_seen` list), so G.edges[u, v] is a KEY-dict on a multigraph, and
        G.edges[u, v] on a plain graph is the attrs dict. Both mean the same to us."""
        d = G.get_edge_data(u, v)
        if not d:
            return {}
        if G.is_multigraph():
            # the strongest edge speaks: keys are insertion order, first is the kept one
            return next(iter(d.values()))
        return d

    def _edge_line(self, G, u: str, v: str) -> dict:
        e = self._edge_attrs(G, u, v)
        return {"to": v, "label": (G.nodes[v].get("label") or "")[:120],
                "relation": e.get("relation") or "linked",
                "confidence": e.get("confidence") or "",
                "degree": G.degree(v)}

    def explain(self, name: str) -> dict:
        """One node, whole: what it is, where it came from, its community, its connections.
        When the node names a store row, the row's live text rides along — the scar, current."""
        G = self._G()
        nid = self._resolve(name)
        if nid is None:
            return {"status": "not-found", "query": str(name)[:120],
                    "message": "no node matches; try a fact id, a label word, or `query`"}
        attrs = G.nodes[nid]
        out = {"status": "ok", "id": nid, "label": attrs.get("label") or "",
               "community": attrs.get("community"), "degree": G.degree(nid),
               "file": attrs.get("source_file"), "type": attrs.get("file_type")}
        s = str(nid)
        if "_fact_" in s and s.rsplit("_fact_", 1)[1].isdigit():
            out["fact"] = int(s.rsplit("_fact_", 1)[1])
            text = self._row_text(out["fact"])
            if text:
                out["text"] = text[:1200]        # the live ledger row behind the node
        outs = [self._edge_line(G, nid, nb) for nb in G.neighbors(nid)] if G.is_directed() \
            else self._undirected_edges(G, nid)
        out["connections"] = sorted(outs, key=lambda e: (-e["degree"], e["label"]))[:40]
        return out

    def _undirected_edges(self, G, nid: str) -> list[dict]:
        return [{"to": nb, "label": (G.nodes[nb].get("label") or "")[:120],
                 "relation": self._edge_attrs(G, nid, nb).get("relation") or "linked",
                 "confidence": self._edge_attrs(G, nid, nb).get("confidence") or "",
                 "degree": G.degree(nb)} for nb in G.neighbors(nid)]

    def path(self, a: str, b: str) -> dict:
        """The shortest walk between two nodes, every hop tagged with its relation and
        confidence. The path's confidence is its WEAKEST hop — a route through an INFERRED
        edge is an inferred route. This is the verb that shows the bridge earning its keep."""
        import networkx as nx

        G = self._G()
        na, nb = self._resolve(a), self._resolve(b)
        if na is None or nb is None:
            return {"status": "not-found", "missing": str(a if na is None else b)[:120]}
        U = G.to_undirected() if G.is_directed() else G
        try:
            nodes = nx.shortest_path(U, na, nb)
        except nx.NetworkXNoPath:
            return {"status": "no-path", "from": na, "to": nb}
        hops, weakest = [], "EXTRACTED"
        for u, v in zip(nodes, nodes[1:]):
            e = self._edge_attrs(U, u, v)
            conf = e.get("confidence") or ""
            if conf == "INFERRED":
                weakest = "INFERRED"
            hops.append({"from": u, "to": v, "label": (G.nodes[v].get("label") or "")[:120],
                         "relation": e.get("relation") or "linked", "confidence": conf})
        return {"status": "ok", "from": na, "to": nb, "hops": len(hops),
                "confidence": weakest if hops else "", "path": hops}

    def query(self, q: str, budget: int = 1200, depth: int = 2, seeds: int = 5) -> dict:
        """Plain words in, a scoped neighbourhood out: score nodes by label overlap, walk
        `depth` hops from the best, print it inside `budget` characters. The graph arm votes
        on the neighbours of top hits; this is the same walk with a human asking — and the
        graph-first answer to 'what connects X to Y', where graphify's whole pitch lives."""
        G = self._G()
        toks = set(WORDS.findall(str(q).lower()))
        if not toks or not G.number_of_nodes():
            return {"status": "empty", "text": ""}
        scored = []
        for nid, attrs in G.nodes(data=True):
            overlap = len(toks & set(WORDS.findall((attrs.get("label") or "").lower())))
            if overlap:
                scored.append((overlap, G.degree(nid), nid))
        if not scored:
            return {"status": "no-match", "text": ""}
        scored.sort(reverse=True)
        front = [nid for _, _, nid in scored[:max(1, seeds)]]
        seen, frontier = set(front), set(front)
        for _ in range(max(1, depth)):
            nxt = {nb for n in frontier for nb in G.neighbors(n)} - seen
            seen |= nxt
            frontier = nxt
            if not nxt:
                break
        lines, used = [], 0
        try:
            # graphify's own walk when the library is importable: IDF-weighted scoring,
            # hub-penalised paths, its budgeted renderer. The seeds above are ours (label-word
            # overlap), so the payload names the rows the question chose either way.
            from graphify import serve as gs
            text = gs._query_graph_text(G, str(q), mode="bfs", depth=max(1, int(depth)),
                                        token_budget=max(100, int(budget) // 3),
                                        graph_path=str(self.graph_path), seeds=front)
            if str(text).strip():
                return {"status": "ok", "engine": "graphify", "seeds": front,
                        "nodes": len(seen), "text": str(text)[:budget]}
        except Exception:                                    # noqa: BLE001 - the lean walk answers
            pass
        for nid in front:
            lines.append(f"* {G.nodes[nid].get('label') or nid}"[:200])
            used += len(lines[-1])
            for e in sorted(self._undirected_edges(G, nid), key=lambda x: x["label"]):
                line = f"    --{e['relation']}--> {e['label']}" \
                     + (f" [{e['confidence']}]" if e["confidence"] else "")
                if used + len(line) > budget:
                    return {"status": "ok", "seeds": front, "nodes": len(seen),
                            "text": "\n".join(lines), "truncated": True}
                lines.append(line)
                used += len(line)
        return {"status": "ok", "seeds": front, "nodes": len(seen),
                "text": "\n".join(lines)[:budget]}

    def _row_text(self, fact_id: int) -> str:
        from serve.memory import attach
        try:
            conn = attach(str(self.store_dir))
        except Exception:
            return ""
        try:
            r = conn.execute("SELECT text FROM memories WHERE id = %s AND invalid_at IS NULL",
                             (int(fact_id),)).fetchone()
            return (r[0] or "") if r else ""
        finally:
            conn.close()

    # ---------------------------------------------------------------- live mirror
    # graph.json stays canonical - the arm, the page, and explain/path/query all read it.
    # The Neo4j side is a MIRROR: push again after any rebuild and MERGE keeps it idempotent.
    # At 3k rows the file walk is sub-millisecond; the mirror earns its keep when the doc
    # graph lands (33k nodes) and multi-hop Cypher wants indexes (2026-11-16, the owner's
    # "build it before we need it").

    def push(self, uri: str = "bolt://127.0.0.1:7687", user: str = "neo4j",
             password: str = "") -> dict:
        """Mirror the standing graph into a live Neo4j (FalkorDB speaks the same driver
        family via its Bolt endpoint). Credentials come from the arguments or
        STRATA_NEO4J_PASSWORD - a store never bakes a secret into its code.
        An unreachable server is a named answer, not a stack trace."""
        G = self._G()
        if not G.number_of_nodes():
            return {"status": "empty", "message": "no graph to push - run a pass first"}
        from graphify.export import push_to_neo4j
        comms: dict[int, list] = {}
        for cid, members in (self._read(self.analysis_path).get("communities") or {}).items():
            try:
                comms[int(cid)] = members
            except (TypeError, ValueError):
                continue
        pw = password or os.environ.get("STRATA_NEO4J_PASSWORD", "")
        try:
            counts = push_to_neo4j(G, uri, user, pw, communities=comms or None)
        except Exception as exc:                             # noqa: BLE001 - the caller sees the reason
            return {"status": "unreachable", "uri": uri,
                    "message": f"{type(exc).__name__}: {str(exc)[:180]}"}
        self._write(self.dir / "mirror.json",
                    {"pushed": _now(), "uri": uri, "nodes": G.number_of_nodes(),
                     "edges": G.number_of_edges(), **{k: v for k, v in (counts or {}).items()}})
        return {"status": "ok", "uri": uri, **(counts or {})}

    def export_cypher(self, path: str | None = None) -> dict:
        """The serverless mirror: one .cypher file any Neo4j can load, rewritten by the
        next pass. No DB process, no RAM - the graph as a portable statement script."""
        G = self._G()
        if not G.number_of_nodes():
            return {"status": "empty", "message": "no graph to export - run a pass first"}
        from graphify.export import to_cypher
        out = path or str(self.dir / "graph.cypher")
        to_cypher(G, out)
        return {"status": "ok", "file": out, "bytes": os.path.getsize(out),
                "nodes": G.number_of_nodes(), "edges": G.number_of_edges()}

    # ---------------------------------------------------------------- curation hook
    def note(self, ids: Iterable[int]) -> int:
        """Record facts that the harvest just stored, to be graphed by the next pass.

        The curation loop calls this after a window is marked. It is cheap and offline —
        a JSON list, no LLM — so it cannot slow a drain; the LLM pass is the sweep's job.
        """
        pend = self._read(self.pending_path, {"ids": []})
        known = set(pend.get("ids") or [])
        known.update(int(i) for i in ids)
        self._write(self.pending_path, {"ids": sorted(known), "updated": _now()})
        return len(known)

    def clear_pending(self) -> None:
        self._write(self.pending_path, {"ids": [], "updated": _now()})

    def pending_ids(self) -> list[int]:
        return list(self._read(self.pending_path, {}).get("ids") or [])

    def due(self, threshold: int = 24) -> bool:
        """Is it worth a pass? One pass per `threshold` new facts, so a 60-fact drain
        costs ~3 graph passes, not 60."""
        return len(self.pending_ids()) >= threshold


__all__ = ["StrataGraphify", "DEFAULT_STORE", "DIR_NAME"]
