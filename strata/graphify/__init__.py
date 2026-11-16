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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_STORE = "/home/eugene/Strata-data/memory-eval"
DIR_NAME = "strata-graphify"

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
              files_per_chunk: int = FILES_PER_CHUNK, on_progress=None) -> dict:
        """Run a graph pass and persist it. `full` rebuilds every shelf; otherwise the
        existing graph is kept and the new rows are merged into it (build_merge), so a
        curated fact joins the graph it belongs to instead of replacing the file.
        """
        import networkx as nx
        from graphify import analyze, build as gbuild, cluster as gcluster, export as gexport

        self._ensure()
        rows = self.facts(ids)
        if not rows:
            return {"status": "empty", "message": "no facts to graph"}
        files = self.write_corpus(rows)
        chunks = self._chunks(files, files_per_chunk)
        total = len(chunks)
        parts, done, t0 = [], 0, time.time()
        for chunk in chunks:
            parts.append(self._extract(chunk))
            done += 1
            if on_progress:
                on_progress(done, total, len(files))
        extraction = self._merge_extractions(parts)

        if full or not self.graph_path.exists():
            G = gbuild.build_from_json(extraction, root=self.corpus)
        else:
            G = gbuild.build_merge([extraction], graph_path=self.graph_path, root=self.corpus)
        communities = gcluster.cluster(G)
        cohesion = gcluster.score_all(G, communities)
        gexport.to_json(G, communities, str(self.graph_path), force=True)

        self._write(self.analysis_path, {
            "communities": {str(k): v for k, v in communities.items()},
            "cohesion": {str(k): v for k, v in cohesion.items()},
            "gods": analyze.god_nodes(G, top_n=12),
        })
        state = {
            "built": _now(), "seconds": round(time.time() - t0, 1),
            "facts": len(rows), "files": len(files), "chunks": total,
            "nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
            "hyperedges": len(extraction.get("hyperedges") or []),
            "communities": len(communities),
            "tokens_in": extraction["input_tokens"], "tokens_out": extraction["output_tokens"],
            "model": served_model(), "watermark": max(r[0] for r in rows),
            "mode": "full" if (full or not self.graph_path.exists()) else "merge",
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
            "facts": state.get("facts", 0),
            "in_graph": cov.get("in_graph", 0),
            "built": state.get("built"), "seconds": state.get("seconds"),
            "model": state.get("model"), "mode": state.get("mode"),
            "pending": len(self._read(self.pending_path, {}).get("ids", [])),
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

    def coverage(self) -> dict:
        """Facts in the graph over facts in the store — the number the tile shows.

        A node is a concept the model lifted out of the fact text, so the node count is not
        the coverage: one node can cite a dozen rows, and a row can be cited by none. The
        honest read is the set of row ids the graph actually names. Node ids carry them
        (`<shelf>_fact_<id>`), so coverage is a suffix count over the ids on disk.
        """
        g = self._read(self.graph_path)
        ids = set()
        for n in g.get("nodes") or []:
            nid = str(n.get("id") or "")
            if "_fact_" in nid:
                tail = nid.rsplit("_fact_", 1)[1]
                if tail.isdigit():
                    ids.add(int(tail))
        for h in g.get("hyperedges") or []:
            for m in h.get("members") or h.get("nodes") or []:
                mid = str(m.get("id") if isinstance(m, dict) else m)
                if "_fact_" in mid:
                    tail = mid.rsplit("_fact_", 1)[1]
                    if tail.isdigit():
                        ids.add(int(tail))
        return {"in_graph": len(ids), "graph_ids": sorted(ids)[:20]}

    def stats_patch(self) -> dict:
        """The graph tile's numbers, folded into the store's own stats reply."""
        state = self._read(self.state_path)
        prog = self._read(self.progress_path)
        return {
            "nodes": state.get("nodes", 0),
            "communities": state.get("communities", 0),
            "facts": state.get("facts", 0),
            "built": state.get("built"),
            "pending": len(self._read(self.pending_path, {}).get("ids", [])),
            "running": bool(prog.get("running")),
        }

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
