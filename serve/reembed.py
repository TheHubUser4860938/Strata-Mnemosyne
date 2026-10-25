"""serve/reembed.py - rewrite every vector in a store with the configured embedder.

The store's invariant is vectors == live rows, and vectors are comparable only WITHIN one
model (the 2026-10-24 swap law: bge's 384-d bytes are meaningless against a 768-d query).
So a model change means re-embedding everything before the semantic arm can be trusted -
and this tool does it in ONE transaction: the live server sees all-old or all-new bytes,
never a mixed store (a mixed-width np.stack is the crash the matrix filter exists to
avoid), and every rewritten row leaves stamped with the model that made it. Whatever the
old-code server manages to write inside the run's window stays NULL-stamped, is excluded
by width, and the boot banner counts what is left out loud.

Attach semantics (ADR-002 R0b): running against a LIVE store is the normal case - the
curation loop does the same every window - and this process does not stop the cluster on
the way out.

    python -m serve.reembed --store /path/to/store --dir /path/to/embeddinggemma-2 \
        [--name embeddinggemma-2] [--threads 8] [--fill] [--dry]
"""
from __future__ import annotations

import argparse
import time

from . import memory as memory_api
from .embedder import create


def migrate(svc, emb, fill: bool = False, log=print) -> dict:
    """Re-embed every row that carries a vector whose stamp is not the live model's
    (with --fill, also live rows that carry none). Returns the report; raises on SQL
    trouble - a half-written migration rolls back whole, it does not warn."""
    name = getattr(emb, "model_name", "unknown")
    conn = svc.conn
    rows = conn.execute(
        "select e.id, m.text from embeddings e join memories m on m.id = e.id"
        " where e.model is distinct from %s", (name,)).fetchall()
    if fill:
        rows += conn.execute(
            "select m.id, m.text from memories m left join embeddings e on e.id = m.id"
            " where e.id is null and m.invalid_at is null").fetchall()
    conn.commit()
    log(f"store: {len(rows)} rows to rewrite for model {name!r}")
    t0 = time.perf_counter()
    n = 0
    for i in range(0, len(rows), 64):
        batch = rows[i:i + 64]
        vecs = emb.embed_docs([r[1] for r in batch])
        with conn.cursor() as cur:                    # the venue tools' own pattern
            cur.executemany(
                "insert into embeddings(id, vec, model) values(%s,%s,%s)"
                " on conflict (id) do update set vec = excluded.vec, model = excluded.model",
                [(r[0], v.tobytes(), name) for r, v in zip(batch, vecs)])
        n += len(batch)
        if n % 512 < 64:
            log(f"  {n}/{len(rows)} rows, {time.perf_counter() - t0:.0f} s")
    conn.execute("insert into meta(key, value) values('embedder_model', %s)"
                 " on conflict (key) do update set value = excluded.value", (name,))
    conn.commit()                                     # the whole rewrite lands at once
    dt = time.perf_counter() - t0
    return {"rows": n, "seconds": round(dt, 1), "model": name,
            "per_row_ms": round(dt * 1000 / max(1, n), 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m serve.reembed")
    ap.add_argument("--store", required=True, help="the store directory the server uses")
    ap.add_argument("--dir", required=True, help="embedder model directory")
    ap.add_argument("--name", default=None, help="which embedder class (default: the dir name)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--max-seq", type=int, default=None)
    ap.add_argument("--fill", action="store_true",
                    help="also embed live rows that carry no vector at all")
    ap.add_argument("--dry", action="store_true", help="count and say, write nothing")
    a = ap.parse_args(argv)
    emb = create(a.dir, threads=a.threads, name=a.name, max_seq=a.max_seq)
    svc = memory_api.MemoryService(a.store, embedder=emb)     # attaches; keeps the cluster up
    foreign = svc.foreign_vectors()
    print(f"embedder {getattr(emb, 'model_name', '?')}, {getattr(emb, 'dims', '?')}-d; "
          f"store has {foreign} foreign-sized or foreign-stamped vectors")
    if a.dry:
        print("--dry: nothing written")
        return 0
    rep = migrate(svc, emb, fill=a.fill)
    print(f"re-embedded {rep['rows']} rows in {rep['seconds']} s "
          f"({rep['per_row_ms']} ms/row); foreign vectors now {svc.foreign_vectors()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
