#!/usr/bin/env python3
"""One atomic batch of memory operations against a running Strata.

Why: the shelf's row ceiling is 4,000 characters (serve/memory.py:1471), and an
over-budget write today costs two calls - shorten, then add - with a crash
window between them. Hermes solves the same shape in its memory tool
(tools/memory_tool.py:373): "make ALL your changes to one target in ONE call via
an 'operations' array... the char limit is checked only on the FINAL result - so
a single call can remove/patch stale entries to free room AND add new ones,
even when an add alone would overflow."

Client-side on purpose: no server change, no reboot, and the sweep is the only
caller that needs it today.

Rollback is the house way: an applied add is INVALIDATED (out of recall, kept in
the history) and an applied correction is superseded, so the scar stays visible
(motive six). The verbs are the server's own: remember, correct, invalidate -
op:"retire" is the cart verb.
"""
from __future__ import annotations

import urllib.error

CEILING = 4000
ACTIONS = ("add", "amend", "retire")


def _normalize(text: str) -> str:
    return " ".join(str(text or "").split())


def plan(operations) -> list[dict]:
    """Validate every op's shape and its FINAL length before anything is written.

    A batch that would overflow is refused whole - the caller fixes it as one
    batch, which is the point of the endpoint.
    """
    ops = list(operations or [])
    if not ops:
        raise ValueError("an operations batch needs at least one op")
    out = []
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError(f"op {i} is not an object")
        action = op.get("action")
        if action not in ACTIONS:
            raise ValueError(f"op {i}: action must be one of {ACTIONS}, got {action!r}")
        if action in ("add", "amend"):
            text = _normalize(op.get("text"))
            if not text:
                raise ValueError(f"op {i} ({action}) needs text")
            if len(text) > CEILING:
                raise ValueError(
                    f"op {i} ({action}) is {len(text)} characters, over the {CEILING}-char row "
                    f"ceiling; shorten it and re-issue the whole batch in one call")
            if action == "amend" and op.get("id") is None:
                raise ValueError(f"op {i} (amend) needs an id")
            out.append({"action": action, "text": text, "id": op.get("id"),
                        "klass": op.get("klass"), "scope": op.get("scope"),
                        # an amend's undo needs the bytes it replaced: the store
                        # overwrites text, so the caller hands the old text in
                        "prev_text": _normalize(op.get("prev_text")) if action == "amend" else None,
                        "provenance": op.get("provenance")})
        else:
            if op.get("id") is None:
                raise ValueError(f"op {i} (retire) needs an id")
            out.append({"action": "retire", "id": op.get("id"), "scope": op.get("scope"),
                        "text": op.get("text")})
    return out


def _body(op: dict, source: str) -> dict:
    """The wire shape of one fact verb, read from serve/server.py:10241-10252.

    add -> remember, amend -> correct (lands a NEW row and supersedes the old:
    that is the house supersession chain, motive six), retire -> invalidate
    (out of recall, kept in the history). op:"retire" is the CART verb, not this.
    """
    if op["action"] == "add":
        b = {"op": "remember", "text": op["text"], "source": source}
        if op.get("klass"):
            b["class"] = op["klass"]
        if op.get("scope"):
            b["scope"] = op["scope"]
        if op.get("provenance"):
            b["provenance"] = op["provenance"]
        return b
    if op["action"] == "amend":
        b = {"op": "correct", "id": op["id"], "text": op["text"], "source": source}
        if op.get("klass"):
            b["class"] = op["klass"]        # absent -> the new row inherits the old shelf
        if op.get("scope"):
            b["scope"] = op["scope"]
        if op.get("provenance"):
            b["provenance"] = op["provenance"]
        return b
    return {"op": "invalidate", "id": op["id"], **({"scope": op["scope"]} if op.get("scope") else {})}


def apply_operations(operations, post, source: str = "curate") -> dict:
    """Apply a batch in order. The first failure retires what landed, and the
    result names the op that failed.

    `post(body) -> (status, response)` is injected so the contract is testable
    without an engine.
    """
    ops = plan(operations)
    done: list[dict] = []
    for i, op in enumerate(ops):
        try:
            status, resp = post(_body(op, source))
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            return _fail(post, done, i, f"transport: {type(e).__name__}: {e}")
        if status is None or status >= 400:
            detail = (resp or {}).get("error") if isinstance(resp, dict) else resp
            return _fail(post, done, i, f"op {i} {op['action']} -> {status}: {str(detail)[:160]}")
        done.append({**op, "receipt": resp})
    return {"ok": True, "applied": len(done), "failed_index": None, "rolled_back": False,
            # the ids of the rows this batch wrote; a retire names a row it freed,
            # not a row it created, so it is not a write receipt
            "ids": [d["receipt"]["id"] for d in done
                    if d["action"] in ("add", "amend") and isinstance(d.get("receipt"), dict)
                    and d["receipt"].get("id")],
            # the server's own answer per op: `deduped` and `invalidated` are the two
            # fields a clerk needs to know what the shelf did with a correction
            "receipts": [d["receipt"] for d in done]}


def _fail(post, done: list[dict], index: int, error: str) -> dict:
    """Undo what landed, newest first, so a half-applied batch is one visible state.
    Retire, not delete - the scar stays visible (motive six)."""
    retired = []
    for d in reversed(done):
        rid = d.get("receipt", {}).get("id") if isinstance(d.get("receipt"), dict) else None
        if d["action"] == "amend":
            # supersede the correction with the wording it replaced: the chain grows
            # by one honest link, which is the house undo
            target = rid or d.get("id")
            if not target or not d.get("prev_text"):
                continue      # nothing to restore to; the corrected row stands
            body = {"op": "correct", "id": target, "text": d["prev_text"], "source": "batch-rollback"}
            if d.get("scope"):
                body["scope"] = d["scope"]
        elif d["action"] == "add":
            if not rid:
                continue
            body = {"op": "invalidate", "id": rid}
            if d.get("scope"):
                body["scope"] = d["scope"]
        else:
            continue        # a retire is undone by un-retiring, which one call does not do
        try:
            post(body)
            retired.append(rid if rid else d.get("id"))
        except Exception:                                        # noqa: BLE001 - best-effort
            pass
    return {"ok": False, "applied": 0, "failed_index": index, "rolled_back": True,
            "retired": retired, "error": error}
