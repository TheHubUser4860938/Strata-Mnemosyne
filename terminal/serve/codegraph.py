"""codegraph.py — the seam between the store's rows and the repo's code graph (2026-11-24, the merge).

Three surfaces, three address spaces, no join. A `DEC` row says "the seam lives in
`strata_control/setup_config.py`"; the memory graph calls that row `dec_seam_lives_fact_234183`;
the repo graph has 184,727 nodes keyed by a slugged path plus a symbol label, and 454,530
structural edges over them. Nothing connects the row to the symbol, so "what did we decide about
this function?" and "what memory is about this file?" both had to be answered by grep.

This module is that join, and it is deliberately small: it READS graphify's output (it owns its
file and rewrites it nightly at 04:40), indexes it by path, and answers two questions.

  resolve("serve/memory.py")     → exists on disk under one of the roots? which code nodes?
  nodes_for(path)                → the node ids whose source_file is that path

The suffix index is what makes it work in practice: the store's rows name paths in the shape the
speaker used — `serve/memory.py`, `terminal/serve/memory.py`, `m7_consolidate.py`, `AGENTS.md` —
while the graph stores repo-relative paths. Matching on the last two segments resolves every shape
a person actually types, and a two-segment match is specific enough that `docs/README.md` and
`app/README.md` stay distinct.

The cache follows the store's own stamp law (see `MemoryService._graph`): keyed by the file's
mtime, so a nightly AST refresh is picked up and a cold read is one JSON parse.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

__all__ = ["CodeGraph", "default_graph"]

DEFAULT = Path(__file__).resolve().parents[2] / "graphify-out" / "graph.json"
SIDECAR = DEFAULT.parent / "semantic.json"      # tools/m11_semantic.py's embedding edges (2026-11-24)


class CodeGraph:
    """A read-only index over graphify-out/graph.json: path → nodes, and the reverse."""

    def __init__(self, path: str | Path = DEFAULT, roots: list[str | Path] | None = None,
                 sidecar: str | Path | None = None):
        self.path = Path(path)
        self.sidecar = Path(sidecar) if sidecar else SIDECAR
        # The roots a row's path is resolved against. The repo root and its `terminal/` half are
        # the two the store's own rows use, measured 2026-11-24: 21 DEC rows name a file, and the
        # same row shape appears as `serve/memory.py` (terminal-relative) and `docs/MEMORY_CORE.md`
        # (repo-relative).
        self.roots = [Path(str(r)).expanduser() for r in (roots or self._default_roots())]
        self._lock = threading.Lock()
        self._stamp: float | None = None
        self._sem_stamp: float | None = None
        self._sem: dict[str, list[tuple[str, float]]] = {}
        self._by_file: dict[str, list[str]] = {}
        self._by_suffix: dict[str, list[str]] = {}
        self._label: dict[str, str] = {}
        self._file_of: dict[str, str] = {}
        self._n = 0

    @staticmethod
    def _default_roots() -> list[Path]:
        here = Path(__file__).resolve().parents[2]                 # …/Strata-Mnemosyne
        return [here, here / "terminal"]

    def _load(self) -> None:
        try:
            stamp = os.path.getmtime(self.path)
        except OSError:
            return
        if self._stamp == stamp:
            return
        with self._lock:
            if self._stamp == stamp:
                return
            try:
                g = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            by_file: dict[str, list[str]] = {}
            by_suffix: dict[str, list[str]] = {}
            label: dict[str, str] = {}
            file_of: dict[str, str] = {}
            for n in g.get("nodes") or []:
                nid = str(n.get("id") or "")
                src = str(n.get("source_file") or "")
                if not nid:
                    continue
                label[nid] = str(n.get("label") or nid)
                if not src:
                    continue
                file_of[nid] = src
                by_file.setdefault(src, []).append(nid)
                seg = "/".join(src.split("/")[-2:]) if "/" in src else src
                by_suffix.setdefault(seg, []).append(nid)
                by_suffix.setdefault(Path(src).name, []).append(nid)
            self._by_file, self._by_suffix = by_file, by_suffix
            self._label, self._file_of = label, file_of
            self._n = len(g.get("nodes") or [])
            self._stamp = stamp

    def _load_sem(self) -> None:
        """The embedding sidecar, mtime-stamped like the graph (tools/m11_semantic.py).

        graphify rewrites graph.json nightly and knows nothing of this file, so the join lives
        here: `pairs` are node-id → node-id with a cosine, produced on the STORE's ruler
        (embeddinggemma-2), which is what makes a "similar" here mean the same thing as a
        "similar" in the recall block. Absent sidecar = empty map, never an error.
        """
        try:
            stamp = os.path.getmtime(self.sidecar)
        except OSError:
            self._sem, self._sem_stamp = {}, None
            return
        if self._sem_stamp == stamp:
            return
        with self._lock:
            if self._sem_stamp == stamp:
                return
            try:
                doc = json.loads(self.sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            sem: dict[str, list[tuple[str, float]]] = {}
            for p in doc.get("pairs") or []:
                a, b, c = str(p.get("source") or ""), str(p.get("target") or ""), float(p.get("cos") or 0)
                if a and b:
                    sem.setdefault(a, []).append((b, c))
                    sem.setdefault(b, []).append((a, c))
            for v in sem.values():
                v.sort(key=lambda x: -x[1])
            self._sem, self._sem_stamp = sem, stamp

    def related(self, nid: str, limit: int = 4) -> list[dict]:
        """What the RULER thinks this node is near — embedding edges, not AST edges.

        AST says `search()` calls `_semantic()`; the cosine says a function in `serve/docs.py`
        implements the idea a note in `MEMORY_CORE.md` describes. That is the edge class the
        structural graph cannot see, and the reason the 25-minute embed pass exists.
        """
        self._load_sem()
        out = []
        for x, cos in self._sem.get(str(nid), [])[:limit]:
            out.append({"node": x, "label": self._label.get(x, x),
                        "file": self._file_of.get(x, ""), "cos": round(cos, 3)})
        return out

    def exists(self, name: str) -> bool:
        """Does the cited path resolve to a real file under any root? (The stale pass asks this
        first; the graph is the fallback, because a node proves the file is in the tree.)"""
        p = Path(str(name))
        if p.is_absolute():
            return p.exists()
        return any((r / p).exists() for r in self.roots)

    def nodes_for(self, name: str, limit: int = 12) -> list[dict]:
        """The code nodes whose file the row names, by exact path then by suffix."""
        self._load()
        s = str(name).strip().lstrip("./")
        ids = list(self._by_file.get(s, []))
        if not ids:
            seg = "/".join(s.split("/")[-2:]) if "/" in s else Path(s).name
            ids = list(self._by_suffix.get(seg, []))
        seen, out = set(), []
        for nid in ids:
            if nid in seen:
                continue
            seen.add(nid)
            node = {"node": nid, "label": self._label.get(nid, nid),
                    "file": self._file_of.get(nid, s)}
            rel = self.related(nid, limit=3)
            if rel:
                node["related"] = rel
            out.append(node)
            if len(out) >= limit:
                break
        return out

    def resolve(self, name: str) -> dict:
        """One answer to the question a citation asks: is the address live, and what is there?

        `on_disk` is the filesystem's answer; `nodes` is the graph's. A row whose path is gone from
        disk but present in the graph is not stale in the sense that matters — the file is in the
        tree, the row just named it from a different root. Measured 2026-11-24: 12 of 21 DEC rows
        that name a file failed a single-root check; the multi-root check is what makes that number
        mean "the file moved", not "the path is spelled from over there".
        """
        self._load()
        on_disk = self.exists(name)
        nodes = self.nodes_for(name)
        return {"path": str(name), "on_disk": on_disk, "live": on_disk or bool(nodes),
                "nodes": nodes, "roots": [str(r) for r in self.roots]}

    def stats(self) -> dict:
        self._load()
        return {"graph": str(self.path), "nodes": self._n, "files": len(self._by_file),
                "roots": [str(r) for r in self.roots],
                "graph_mtime": self._stamp and int(self._stamp)}


_singleton: CodeGraph | None = None
_singleton_lock = threading.Lock()


def default_graph(path: str | Path | None = None) -> CodeGraph:
    """The process's one CodeGraph, mtime-stamped, so every caller shares the parse."""
    global _singleton
    with _singleton_lock:
        if _singleton is None or (path is not None and Path(path) != _singleton.path):
            _singleton = CodeGraph(path or DEFAULT)
    return _singleton
