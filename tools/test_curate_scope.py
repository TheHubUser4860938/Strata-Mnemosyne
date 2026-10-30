"""The scope guard: inside a nested function, `name += 1` on a name the ENCLOSING function binds
is a trap.  Python makes that name local to the inner function, so the augmented read happens
before anything has assigned it - UnboundLocalError, every time that branch runs.

Receipt, dated: `unscored += 1` in curate_loop.score_batch (added 2026-10-24 by 82f3ac01) sat
latent six days because its branch only fires when a candidate comes back short of alive cold
passes.  The first geometry-blind boot found it; every tick from 2026-10-30 00:33 died there,
before the store and before the per-window mark, and 298 turns stayed uncurated overnight while
the sweep still reported itself healthy.  The tally it tried to bump is kept by `unscored_here`
and returned to the caller, which owns the run total.

The rule is deliberately narrow: an AugAssign whose name an enclosing scope also binds, where the
inner scope never ASSIGNS that name plainly and never declares it nonlocal/global.  A function
that initializes `total = 0` before touching `total += x` is a legal shadow and stays unflagged,
so the check costs nothing to run repo-wide.
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKGS = ("tools", "serve")


def _is_scope(node) -> bool:
    """A nested function, lambda or class is its own scope: its names are its own business."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef))


def _own_names(fn) -> tuple:
    """This scope's (plain-bound names, augmented-bound names, nonlocal/global declarations)."""
    plain: set[str] = set()
    aug: set[str] = set()
    declared: set[str] = set()

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if _is_scope(child):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    plain.add(child.name)          # a def binds its name in THIS scope
                continue
            if isinstance(child, (ast.Nonlocal, ast.Global)):
                declared.update(child.names)      # no children worth walking (bare identifiers)
            elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name):
                aug.add(child.target.id)
                walk(child.value)              # NOT walk(child): the += target is a Store-Name,
                continue                       # and counting it as plain-bound would hide the bug
            elif isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
                plain.add(child.id)
            elif isinstance(child, (ast.Import, ast.ImportFrom)):
                plain.update(a.asname or a.name.split(".")[0] for a in child.names)
            walk(child)

    if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = fn.args
        plain.update(x.arg for x in [*a.posonlyargs, *a.args, *a.kwonlyargs])
        for x in (a.vararg, a.kwarg):
            if x is not None:
                plain.add(x.arg)
    walk(fn)
    return plain, aug, declared


def _check(path: pathlib.Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    hits: list[str] = []
    mod = _own_names(tree)

    def visit(fn, enclosing):
        plain, aug, declared = _own_names(fn)
        for name in sorted(aug - declared - plain):
            if any(name in p for p in enclosing):
                hits.append(f"{path.name}:{fn.lineno}: `{name} +=` reads the enclosing scope's "
                            f"name, which Python made local to this function")
        for child in ast.iter_child_nodes(fn):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, enclosing + [plain])

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(node, [mod[0]])
    return hits


def test_no_enclosing_name_augmented_without_nonlocal():
    """The exact shape that cost last night's drain must not come back."""
    hits: list[str] = []
    for pkg in PKGS:
        for f in sorted((ROOT / pkg).glob("*.py")):
            hits += _check(f)
    assert not hits, "augment-assignment scope traps:\n  " + "\n  ".join(hits)


def test_the_guard_fires_on_the_shape_that_broke_the_sweep():
    """A test that cannot fail is not a guard: feed it the bug it was written for."""
    src = ("def outer():\n"
           "    unscored = 0\n"
           "    def inner(xs):\n"
           "        for x in xs:\n"
           "            unscored += x\n"
           "        return unscored\n"
           "    return inner([1])\n")
    tmp = pathlib.Path(__file__).with_name("_scope_guard_selftest__.py")
    tmp.write_text(src, encoding="utf8")
    try:
        assert _check(tmp), "the guard stopped catching its own bug"
    finally:
        tmp.unlink()


def test_a_legal_local_shadow_stays_quiet():
    """`t = 0` then `t += x` inside the inner function is a shadow, not a trap."""
    src = ("def outer():\n"
           "    t = 0\n"
           "    def inner(xs):\n"
           "        t = 0\n"
           "        for x in xs:\n"
           "            t += x\n"
           "        return t\n"
           "    return inner([1])\n")
    tmp = pathlib.Path(__file__).with_name("_scope_guard_selftest2__.py")
    tmp.write_text(src, encoding="utf8")
    try:
        assert not _check(tmp), "the guard cried on a legal shadow"
    finally:
        tmp.unlink()
