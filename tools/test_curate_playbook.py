#!/usr/bin/env python3
"""The playbook shelf arm: one settled task, one row, on OPS/PLAYBOOK.

The plugin (Clio plugins/clio-playbooks.ts) posts this shape; this proves the
shelf answers it the way the plugin believes. Skips cleanly when the port is dark.

Run: .venv/bin/python -m unittest tools.test_curate_playbook
"""
from __future__ import annotations

import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("STRATA_URL", "http://127.0.0.1:8005")
CLASS = "OPS/PLAYBOOK"
MARK = "harness E4 smoke: a settled task filed as one playbook row"


def post(body: dict, timeout: int = 60):
    req = urllib.request.Request(URL + "/memory", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode() or "{}"
        e.close()
        return e.code, json.loads(text)


def server_up() -> bool:
    try:
        status, resp = post({"op": "turns", "limit": 1}, timeout=30)
        return status == 200 and "turns" in resp
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def shelf_text(row: dict) -> str:
    """The plugin's rendering, reimplemented here so the test names the format."""
    bits = [f"Task: {row['title']}"]
    if row.get("traits"):
        bits.append("kind: " + ",".join(row["traits"]))
    if row.get("skills"):
        bits.append("skills: " + ",".join(row["skills"]))
    if row.get("tools"):
        bits.append("tools: " + ",".join(row["tools"]))
    if row.get("verify"):
        bits.append("verification that passed: " + row["verify"])
    bits.append("outcome: " + row.get("outcome", "unverified"))
    return " | ".join(bits)[:1200]


@unittest.skipUnless(server_up(), f"no Strata on {URL}")
class TestPlaybookShelf(unittest.TestCase):
    ROW = {
        "title": MARK,
        "traits": ["bugfix", "memory-shelf"],
        "skills": ["diagnosing-bugs"],
        "tools": ["edit", "shell"],
        "verify": "python3 -m unittest tools.test_curate_clerk",
        "outcome": "verified",
    }

    def test_one_row_lands_with_the_class_the_plugin_names(self):
        text = shelf_text(self.ROW)
        self.assertIn("kind: bugfix,memory-shelf", text)
        self.assertIn("verification that passed:", text)

        status, resp = post({"op": "remember", "text": text, "source": "clio-playbooks",
                             "class": CLASS,
                             "provenance": {"lane": "playbook", "traits": self.ROW["traits"],
                                            "outcome": "verified", "verify": self.ROW["verify"]}})
        self.assertEqual(status, 200, resp)
        rid = resp.get("id")
        self.assertIsInstance(rid, int, "the shelf handed back a row id")

        # read it back: the class is the call number, and it must survive
        status, found = post({"op": "search", "q": "settled task filed playbook row", "limit": 20,
                              "class": "OPS"})
        self.assertEqual(status, 200, found)
        hit = next((h for h in (found.get("hits") or []) if h.get("id") == rid), None)
        self.assertIsNotNone(hit, "the row is retrievable on the OPS family")
        self.assertEqual(hit.get("class"), CLASS, f"the drawer is {hit.get('class')}")

        # the provenance lane rides, so a reader can see where the row came from
        prov = hit.get("provenance") or {}
        self.assertEqual(prov.get("lane"), "playbook")
        self.assertEqual(prov.get("outcome"), "verified")

        status, gone = post({"op": "invalidate", "id": rid})
        self.assertEqual(status, 200, gone)

    def test_a_replay_of_the_same_task_dedupes_instead_of_piling_up(self):
        text = shelf_text(self.ROW)
        s1, r1 = post({"op": "remember", "text": text, "source": "clio-playbooks", "class": CLASS})
        s2, r2 = post({"op": "remember", "text": text, "source": "clio-playbooks", "class": CLASS})
        self.assertEqual(s1, 200)
        self.assertEqual(s2, 200)
        self.assertEqual(r1.get("id"), r2.get("id"), "the same bytes land on one row")
        self.assertTrue(r2.get("deduped"), f"the shelf said {r2.get('deduped')}")
        post({"op": "invalidate", "id": r1.get("id")})

    def test_the_row_fits_the_ceiling(self):
        row = dict(self.ROW, title="t" * 1500, verify="v" * 400)
        text = shelf_text(row)
        self.assertLessEqual(len(text), 1200)
        status, resp = post({"op": "remember", "text": text, "source": "clio-playbooks", "class": CLASS})
        self.assertEqual(status, 200, resp)
        post({"op": "invalidate", "id": resp.get("id")})


if __name__ == "__main__":
    unittest.main(verbosity=2)
