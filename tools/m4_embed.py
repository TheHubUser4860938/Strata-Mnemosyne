#!/usr/bin/env python3
"""m4_embed - backfill semantic vectors for rows written before the embedder (PHASE 4).

remember() embeds at write time, but a store that turns the embedder on mid-life has rows
without vectors: they stay recallable by bm25 (the hybrid is a UNION, cosine adds what
lexicon misses, never the reverse), and this tool closes the gap. Safe against a RUNNING
server: writes go to the same WAL the server reads, and MemoryService._vec_matrix notices
by embedded-count on the next search - no restart needed.

  python3 tools/m4_embed.py [--dir Strata-data/memory-eval]
      [--model Strata-data/embeddings/embeddinggemma-2] [--threads 8] [--limit N]
With no --model the store's own meta.embedder_model stamp chooses the dir and the class.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from psycopg import OperationalError                                       # noqa: E402
from serve.embedder import create                                          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from strata_control.datafolder import data_dir                    # noqa: E402  the one data folder (2026-10-23)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(data_dir(ROOT) / "memory-eval"))
    ap.add_argument("--model", default=None,
                    help="embedder dir; the default is the dir named by the store's own "
                         "meta.embedder_model stamp, so the backfill matches the arm that "
                         "ranks (2026-11-01: bge vectors under a gemma arm are comparable "
                         "only by luck)")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="cap rows this pass (0 = all)")
    ap.add_argument("--batch", type=int, default=64,
                    help="rows per embed call. 64 long chunks costs ~26 GB of RSS on "
                         "the 768-d embedder (2026-11-02, measured beside a serving "
                         "engine); 16 costs a few GB and the rate barely moves")
    a = ap.parse_args()

    src = Path(a.dir)
    # ADR-002: the store is a Postgres cluster inside the dir - attach() is the one-liner twin of
    # the old sqlite3.connect, and the sealed-.enc reveal branch retired with the seal law (the
    # store is never ciphertext-at-rest while a dir holds a cluster; backups are the ciphertext).
    from serve.memory import attach
    try:
        conn = attach(str(src))
    except Exception as exc:                       # noqa: BLE001 - a clear no beats a traceback
        print(f"cannot attach {src}: {type(exc).__name__}: {str(exc)[:140]} - is this a Postgres "
              f"store? import it once: python3 tools/m5_import.py --dir {src}")
        return 2

    def done_close():
        conn.close()

    q = ("select id, text from memories where invalid_at is null and id not in"
         " (select id from embeddings) order by id")
    rows = conn.execute(q + (" limit %s" if a.limit else ""),
                        [a.limit] if a.limit else ()).fetchall()
    print(f"unembedded active rows: {len(rows)}")
    if not rows:
        done_close()
        return 0
    stamp = conn.execute("select value from meta where key='embedder_model'").fetchone()
    model = a.model or str(data_dir(ROOT) / "embeddings" / (stamp[0] if stamp else "bge-small-en-v1.5"))
    print(f"embedder: {Path(model).name} (store stamp: {stamp[0] if stamp else 'none'})")
    emb = create(model, threads=a.threads)     # create(), not Embedder(): the model's
    # recipe is a class law (serve/embedder.py OUT) - the bge class against the gemma
    # files embeds with the wrong prefix and the wrong pooling, silently.
    name = getattr(emb, "model_name", Path(model).name)
    t0, done = time.time(), 0
    for i in range(0, len(rows), a.batch):
        chunk = rows[i:i + a.batch]
        vecs = emb.embed_docs([r[1] for r in chunk])
        pairs = [(r[0], v.tobytes(), name) for r, v in zip(chunk, vecs)]
        for attempt in (1, 2):
            try:
                with conn.cursor() as cur:
                    cur.executemany("insert into embeddings(id, vec, model)"
                                    " values(%s,%s,%s)"
                                    " on conflict (id) do update"
                                    " set vec = excluded.vec, model = excluded.model",
                                    pairs)
                conn.commit()
                break
            except OperationalError as exc:      # 2026-11-01: a long pass outlives its
                # socket - the store is the durable thing, the connection is not. The row
                # query selects only unembedded ids, so a dropped batch costs a re-embed.
                print(f"  reconnect after {type(exc).__name__} (attempt {attempt})")
                conn = attach(str(src))
        done += len(chunk)
        rate = done / max(time.time() - t0, 1e-6)
        eta = (len(rows) - done) / rate if rate else 0
        print(f"  {done}/{len(rows)} ({rate:.1f} rows/s, eta {eta / 3600:.1f} h)",
              flush=True)
    done_close()
    print(f"backfilled {done} rows in {time.time() - t0:.1f} s - a live server picks them up"
          " by embedded-count on its next search")
    return 0


if __name__ == "__main__":
    sys.exit(main())
