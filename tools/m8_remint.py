#!/usr/bin/env python3
"""m8_remint - the S3 background re-mint window (2026-10-25, the staleness law).

sweep_cron.sh runs this every tick, beside m4_catalog. A cartridge's promise is that its text
matches the rows it was minted from; the live server marks staleness INLINE (a write that moves
a source row marks the cart stale in the same request - memory._touched), but writers outside
the server process - importers' raw SQL, tomorrow's tool - can only be caught by LOOKING.
This is the looking.

THE LAW, three sentences. Staleness is annotated, never deleted: a stale cart keeps its ledger
row, its scar and its .bin, and only loses its index line (the attach law goes quiet). Re-mints
run in the background window, never on the request path: no user's turn pays to seed somebody
else's old cart. The engine is touched ONLY when something is actually stale - an idle ledger
costs one SELECT and nothing else.

The remint itself rides the API (op=remint, the m2 pattern: the live server seeds, saves and
replaces the file with its scar), because the engine is the server's. A cart whose sources are
ALL gone is reported and left stale: a cart with nothing left to say is a retirement DECISION,
and retirement is a human verb (op=retire) - the sweep does not shelve knowledge by itself.

Run: python3 tools/m8_remint.py [--db DIR] [--url URL] [--apply] [--quiet]
(--quiet prints only when a cart moved, which is what the sweep tick wants to hear; dry by
default: the scan and the remints both wait for --apply.)
"""
import argparse, json, sys, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

from serve.memory import CART_SCAN_SQL, attach                # the store's own scan law + the m2 twin
from strata_control.datafolder import data_dir                # same home m4_catalog reads


def post(url: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url + "/memory", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:      # a seed turn is seconds, not minutes
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except ValueError:
            return e.code, {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(data_dir(ROOT) / "memory-eval"),
                    help="store directory (the scan attaches; the remint rides the API - m2 law)")
    ap.add_argument("--url", default="http://127.0.0.1:8005")
    ap.add_argument("--apply", action="store_true", help="scan and remint (default: report only)")
    ap.add_argument("--quiet", action="store_true", help="print only when a cart moved")
    a = ap.parse_args(argv)

    con = attach(a.db, autocommit=True)
    try:
        newly = []
        if a.apply:
            newly = sorted(r[0] for r in con.execute(CART_SCAN_SQL).fetchall())
        stale = [r[0] for r in con.execute(
            "select name from carts where state = 'stale' order by name").fetchall()]
    except Exception as e:                       # noqa: BLE001 - the migration window: a store
        print(f"[remint] no ledger to mind yet ({str(e).splitlines()[0][:80]})")   # predating the
        return 0                                 # carts table reports, does not crash
    finally:                                     # (finally still closes the connection)
        con.close()

    if not stale:
        if not a.quiet:
            print("[remint] ledger clean: no stale carts")
        return 0

    moved, quiet_notes = [], []
    for name in stale:
        if not a.apply:
            moved.append(f"{name} (dry)")
            continue
        code, body = post(a.url, {"op": "remint", "name": name})
        if code == 200:
            cart = body.get("cart") or {}
            moved.append(f"{name} -> {cart.get('file', '?')} "
                         f"({cart.get('tokens', 0):,} tok"
                         + (f", dropped {len(cart['dropped_rows'])} gone rows"
                            if cart.get("dropped_rows") else "") + ")")
        elif code == 400:      # sources all gone: left stale on purpose, a retirement decision
            moved.append(f"{name}: nothing left to mint - "
                         f"{(body.get('error') or {}).get('message', '')[:80]}")
        else:                  # 503 or worse: the box moved; the next tick tries again
            moved.append(f"{name}: remint refused {code} - "
                         f"{((body.get('error') or {}).get('message', ''))[:80]}")
    if newly and not a.quiet:
        print(f"[remint] scan marked stale: {', '.join(newly)}")
    if not a.quiet or moved:
        print(f"[remint] {len(moved)} stale cart(s)"
              f"{'' if a.apply else ' (dry run - pass --apply to re-mint)'}:")
        for line in moved:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
