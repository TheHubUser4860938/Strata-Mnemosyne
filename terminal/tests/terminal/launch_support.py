"""Shared fixtures for the `strata launch` tests: an isolated home, a fake computer, and a text dump of a Textual screen."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
from pathlib import Path
from unittest import mock

HW_12 = {"ram_gb": 64.0, "os": "Test OS", "disk_free_gb": 5000.0, "cpu": {"avx2": True, "name": "test cpu"},
         "gpus": [{"index": 0, "name": "NVIDIA GeForce RTX 5070", "vram_gb": 12.0, "usable": True, "vendor": "nvidia"}]}
HW_24 = {**HW_12, "gpus": [{"index": 0, "name": "NVIDIA GeForce RTX 4090", "vram_gb": 24.0, "usable": True, "vendor": "nvidia"}]}
HW_2X16 = {**HW_12, "gpus": [{"index": 0, "name": "NVIDIA RTX A4000", "vram_gb": 16.0, "usable": True, "vendor": "nvidia"},
                             {"index": 1, "name": "NVIDIA RTX A4000", "vram_gb": 16.0, "usable": True, "vendor": "nvidia"}]}
HW_32GB_RAM = {**HW_12, "ram_gb": 32.0}


class Home:
    """A throw-away per-user home: profiles, presets, launch presets, state, components and install folder."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="strata-launch-test-")
        base = Path(self.tmp.name)
        self.base = base
        self.env = {
            "STRATA_PROFILE_DIR": str(base / "config" / "profiles"),
            "STRATA_PRESET_DIR": str(base / "config" / "presets"),
            "STRATA_LAUNCH_PRESET_DIR": str(base / "config" / "launch-presets"),
            "STRATA_COMPONENTS_DIR": str(base / "components"),
            "STRATA_INSTALL_DIR": str(base / "install"),
            "STRATA_RUNTIME_DIR": str(base / "runtime"),
            "XDG_STATE_HOME": str(base / "state"),
            "LOCALAPPDATA": str(base / "local"),
            "APPDATA": str(base / "roaming"),            # Windows: %APPDATA%\Strata\settings.json (remembered Strata folders), profiles, connections
            "XDG_CONFIG_HOME": str(base / "xdg-config"),  # Linux/macOS: ~/.config/strata/settings.json
            "HOME": str(base / "home"),
            "USERPROFILE": str(base / "home"),
        }
        self.env_clear = ("STRATA_SETTINGS_FILE", "STRATA_CONNECTION_DIR", "CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES")   # a developer's own variables must not leak into a test either
        (base / "home").mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch.dict(os.environ, self.env)

    def __enter__(self) -> "Home":
        self.patch.start()
        for k in self.env_clear:                       # (patch.dict puts the original environment back on exit)
            os.environ.pop(k, None)
        return self

    def __exit__(self, *exc) -> None:
        self.patch.stop()
        self.tmp.cleanup()


def catalog(hw: dict | None = None, root: Path | None = None):
    from strata_cli.launch.catalog import Catalog
    return Catalog(root=root or Path(os.environ["STRATA_INSTALL_DIR"]), hardware=hw or HW_12)


def text_of(app) -> str:
    """What the current screen shows, one line per terminal row (for assertions and the text previews)."""
    strips = app.screen._compositor.render_strips()
    return "\n".join(s.text.rstrip() for s in strips)


def wizard_flow(app) -> list[str]:
    """The step list the wizard on screen is counting.  It grows as you walk it: on the Start screen
    the family is not chosen yet, so the Drafting step is not in the count, and the first Enter
    commits the recommended row and inserts it.  A walk from the Start screen therefore has to be
    counted with that family, which is what the Model screen will commit — the row the catalog
    recommends, not a guess."""
    screen = getattr(app, "screen", None)
    live = getattr(screen, "flow", None)
    ctx = getattr(app, "ctx", None)
    if callable(live) and ctx is not None:
        fam = getattr(getattr(ctx, "settings", None), "family", None)
        if not fam:
            rows = getattr(ctx, "rows", None) or []
            fam = rows[0].get("family") if rows and isinstance(rows[0], dict) else None
        if fam:
            from strata_cli.launch.screens import flow_for
            return flow_for(ctx, family=fam)
    for owner in (screen, app):
        f = getattr(owner, "flow", None)
        if callable(f):
            flow = f()
            if flow:
                return flow
    raise AssertionError("no wizard flow on this app")


def reach(app, step_id: str) -> tuple:
    """The "enter" presses that walk the launch wizard to `step_id`, counted from the flow the
    running wizard is using.  The wizard's length is data, not a constant: the Cards step exists
    only on multi-GPU boxes and the Drafting step only on machines whose engine runs DFlash2
    (v0.2.23 made that true for the CUDA fixtures these tests drive, so the flow grew from nine
    steps to ten and every test downstream of Pictures landed one step early).  Count it from
    `app.flow()`, the list the app itself prints its "Step N of M" counter from — a ctx built in
    the test can disagree with the app about the hardware, and the counter is the truth on screen."""
    flow = wizard_flow(app)
    if step_id not in flow:
        raise AssertionError(f"no {step_id!r} step in this wizard's flow: {flow}")
    return ("enter",) * (flow.index(step_id) + 1)     # the first Enter leaves the Start screen onto step 1


def walk(app, from_step: str, to_step: str) -> tuple:
    """The "enter" presses that go from one wizard screen to a later one, counted from the flow the
    running wizard is using.  A test that is already standing on Pictures and wants Parallel presses
    the distance between them, not a number: the Drafting step sits in that gap on a DFlash2 machine
    and the Cards step sits in the early ones on a multi-GPU machine."""
    flow = wizard_flow(app)
    for sid in (from_step, to_step):
        if sid not in flow:
            raise AssertionError(f"no {sid!r} step in this wizard's flow: {flow}")
    d = flow.index(to_step) - flow.index(from_step)
    if d <= 0:
        raise AssertionError(f"{to_step!r} is not after {from_step!r} in {flow}")
    return ("enter",) * d


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    from strata_cli.cli import main
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as e:
            code = int(e.code or 0)
    return code, out.getvalue(), err.getvalue()


def not_intel(testcase) -> None:
    """These fixtures describe an NVIDIA PC (catalog(HW_12)). Runner.intel_chosen asks the machine that runs the test, so on a box with an
    Intel Arc (p1006) the launch became an Intel one and the plan words changed. Patched for the length of the test."""
    from strata_cli.launch.runner import Runner
    p = mock.patch.object(Runner, "intel_chosen", lambda self: False)
    p.start()
    testcase.addCleanup(p.stop)
