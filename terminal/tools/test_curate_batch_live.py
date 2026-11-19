#!/usr/bin/env python3
"""C4's wire contract, against a RUNNING Strata.

The unit tests prove the batch logic with a fake. This proves the fake is shaped
like the server: one batch of add + correct + invalidate, posted to /memory, with
the receipts read back. Skips cleanly when nothing is listening, so it can ride
the suite on a box with no engine.

What the live run taught the fake (2026-11-05):
  * op:"retire" is the CART verb; a fact is retired with op:"invalidate";
  * op:"correct" lands a NEW row that supersedes the old one - UNLESS the new
    wording overlaps the carrier by >=75%, in which case it dedupes INTO the
    carrier and answers {"id": <same row>, "invalidated": null};
  * the route answers BARE: {"ok": true, "id": ...}, no result wrapper.

Run: .venv/bin/python -m unittest tools.test_curate_batch_live
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_batch import apply_operations  # noqa: E402

URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8005")
STAMP = "harness C5 smoke"


def post(body: dict, timeout: int = 60):
    req = urllib.request.Request(
        URL + "/memory", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() or "{}"
        e.close()                      # 3.14 warns about an unclosed error body
        return e.code, json.loads(body_text)


def server_up() -> bool:
    try:
        status, resp = post({"op": "turns", "limit": 1}, timeout=30)
        return status == 200 and "turns" in resp
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def search(q: str, limit: int = 8):
    status, resp = post({"op": "search", "q": q, "limit": limit}, timeout=60)
    assert status == 200, f"search {q!r} -> {status}: {resp}"
    return resp.get("hits") or []


@unittest.skipUnless(server_up(), f"no Strata on {URL}")
class TestLiveBatch(unittest.TestCase):
    """The three fact verbs, in one batch, against the real shelf."""

    def test_one_batch_adds_then_the_amend_supersedes_or_dedupes(self):
        r = apply_operations(
            [
                {"action": "add", "text": f"{STAMP}: the sweep gate waits four minutes",
                 "klass": "OPS/HARNESS"},
                {"action": "add", "text": f"{STAMP}: quaternion normalisation is checked per layer"},
            ],
            post, source="harness-c5",
        )
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["applied"], 2)
        self.assertEqual(len(r["ids"]), 2, "the server handed back row ids")
        self.assertTrue(all(isinstance(i, int) for i in r["ids"]))
        self.assertEqual(r["receipts"][0].get("ok"), True, "the receipt rides the result")

        target = r["ids"][1]
        prev = f"{STAMP}: quaternion normalisation is checked per layer"
        new = f"{STAMP}: the embedder normalises quaternions at ingest"
        r2 = apply_operations([{"action": "amend", "id": target, "text": new, "prev_text": prev}],
                              post, source="harness-c5")
        self.assertTrue(r2["ok"], r2.get("error"))
        rec = r2["receipts"][0]
        # both outcomes are legal; the receipt must say which one happened
        self.assertIn("id", rec, "an amend that names no row is a blind write")
        self.assertIn("invalidated", rec, "the receipt must name what it superseded")
        if rec["invalidated"] is None:
            self.assertTrue(rec.get("deduped") or rec.get("pin_held"),
                            f"invalidated:null with no reason: {rec}")
        else:
            self.assertEqual(int(rec["invalidated"]), target, "the old row is the one it replaced")

        # the wording the batch wrote is retrievable from the shelf
        hits = search(new.replace(STAMP + ": ", ""), limit=6)
        texts = " ".join(h.get("text") or "" for h in hits)
        self.assertTrue("quaternion" in texts or "normalis" in texts,
                        f"the shelf does not show the batch's wording: {texts[:200]}")

        # cleanup: invalidate every row this test wrote, so the shelf is as found
        to_retire = [i for i in r["ids"] if isinstance(i, int)]
        if isinstance(rec.get("id"), int):
            to_retire.append(rec["id"])
        r3 = apply_operations([{"action": "retire", "id": i} for i in to_retire], post, source="harness-c5")
        self.assertTrue(r3["ok"], r3.get("error"))
        self.assertEqual(r3["applied"], len(to_retire))

    def test_the_ceiling_the_unit_fake_believes_in_is_the_servers(self):
        status, resp = post({"op": "remember", "text": "q" * 4001, "source": "harness-c5"})
        self.assertGreaterEqual(status, 400, "the server accepted a 4001-char row")
        with self.assertRaises(ValueError) as cm:
            apply_operations([{"action": "add", "text": "q" * 4001}], post, source="harness-c5")
        self.assertIn("4000-char row ceiling", str(cm.exception))
        # the refused op left the port answering, i.e. no half-written state to trip on
        status, resp = post({"op": "turns", "limit": 1})
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
