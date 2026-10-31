"""The fork's update path: a released engine older than this checkout is rebuilt from the checkout.

The fork's engine carries work upstream's releases do not (`--conversation-cache-cart-slots`,
the BF16 projection form).  `update_installed_engine` used to treat every ready-made engine at
or above MIN_ENGINE as current, so `./update.sh` left 0.1.54 in place beside a 0.1.55 source and
the next start died on the fork-only flag.  A ready-made engine older than CMakeLists.txt's
version now takes the local-build branch; the release package is not fetched over it.

    python -m unittest tools.test_setup_engine_update
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup  # noqa: E402

GPU = {"arch": 89, "count": 1}
PREBUILT = {"version": "0.1.54", "source": "prebuilt", "archs": [89],
            "vision": "cuda13.0", "vision_archs": "89"}


class UpdateInstalledEngine(unittest.TestCase):
    def run_update(self, meta: dict, source: str = "0.1.55"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        eng = Path(tmp.name)
        (eng / setup.EXE).write_bytes(b"fake engine")
        (eng / setup.VEXE).write_bytes(b"fake vision")
        (eng / "BUILD.json").write_text(json.dumps(meta), encoding="utf-8")
        built, fetched = [], []
        with mock.patch.object(setup, "engine_dir", lambda toolkit=13: eng), \
                mock.patch.object(setup, "source_version", lambda: source), \
                mock.patch.object(setup, "update_engine_gpu", lambda toolkit=13: dict(GPU)), \
                mock.patch.object(setup, "build_engine",
                                  lambda gpu, vision, yes, llama, toolkit=None: built.append((gpu, vision, toolkit))), \
                mock.patch.object(setup, "get_prebuilt", lambda *a, **k: fetched.append(a)), \
                mock.patch.object(setup, "get_llama_cpp", lambda: "llama"):
            setup.update_installed_engine("http://invalid/", toolkit=13)
        return built, fetched

    def test_a_released_engine_older_than_the_source_is_built_here(self):
        built, fetched = self.run_update(PREBUILT)
        self.assertEqual(fetched, [], "the upstream package must not replace the checkout's engine")
        self.assertEqual(len(built), 1)
        gpu, vision, toolkit = built[0]
        self.assertEqual(int(gpu["arch"]), 89)
        self.assertEqual(vision, "gpu", "a prebuilt 'cuda13.0' encoder maps to build_engine's 'gpu'")
        self.assertEqual(toolkit, 13)

    def test_a_released_engine_at_the_source_version_is_left_alone(self):
        built, fetched = self.run_update({**PREBUILT, "version": "0.1.55"})
        self.assertEqual((built, fetched), ([], []))


if __name__ == "__main__":
    unittest.main()
