#!/usr/bin/env python3
"""tools/test_curate_geom.py - the geometry probe's bank, standalone.

The cold scorer asks the engine with `want = local render + ddelta` and VOIDs any ask whose
prompt_tokens is not exactly that (the V3 channel discipline). `ddelta` is what THIS boot
charges on top of a local render - measured, not remembered, because it moves between boots:
+7 for the reason-modes directive (2026-10-17), +42 for the boot's own head (the 2026-10-30
scar), +49 on the heretic boot of 2026-11-01.

The probe is one 1-token completion with a 30 s timeout, and it ran ONCE per tick. When it
timed out, boot_delta() returned 0 - the comment said "want stays banked" and there was no
bank. Measured in tools/state/cron.log: every void in the 2026-11-03 18:46 tick was
`ptok - expect == 49` (234 of 234), so all 78 candidates came back UNSCORED, the blind-gate
law left the window unmarked, and the tick spent 60 extracts + 234 cold asks to mark nothing.
On 2026-10-31, 15 of 19 runs lost the probe and the day drained 59 turns.

The fix banks the measurement per model id and reuses it when the probe cannot reach the
engine. A bank belongs to the boot that measured it, so a different model id does not spend it.

    .venv/bin/python tools/test_curate_geom.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from curate_loop import probe_delta, geom_bank_path

MODEL = "swift-1.5-flash-next-heretic-iq4_nl"
RENDER = 67                                    # the local render of the probe shape


def render_of(n=RENDER):
    return lambda probe: list(range(n))


def ptok_of(*answers):
    """A boot that answers the given prompt_tokens in order; None = transport failure."""
    it = iter(answers)

    def call(content):
        assert content.startswith("{REASON:off}\n\n"), f"the probe must use ask()'s channel: {content[:20]!r}"
        return next(it, None)
    return call


class BankedBank(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_bank(self, model=MODEL, delta=49):
        geom_bank_path(self.state, model).write_text(
            json.dumps({"model": model, "delta": delta, "at": "2026-11-03T18:46:58"}), encoding="utf-8")

    def read_bank(self, model=MODEL):
        return json.loads(geom_bank_path(self.state, model).read_text(encoding="utf-8"))


class Measured(BankedBank):
    def test_a_live_probe_measures_and_banks(self):
        # the boot charges +49 over the local render - the heretic boot's measured constant
        d, src = probe_delta(ptok_of(RENDER + 49), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (49, "measured"))
        self.assertEqual(self.read_bank()["delta"], 49)
        self.assertEqual(self.read_bank()["model"], MODEL)

    def test_a_negative_overhead_is_a_real_measurement(self):
        # a boot that strips the directive counts FEWER tokens than a template render can;
        # 2026-10-24's consuming boots measured 0, and the gate survived byte-identical
        d, src = probe_delta(ptok_of(RENDER - 3), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (-3, "measured"))
        self.assertEqual(self.read_bank()["delta"], -3)

    def test_a_retry_saves_the_tick(self):
        # the 2026-11-03 failure shape: the first attempt times out under engine load
        d, src = probe_delta(ptok_of(None, RENDER + 49), render_of(), "PROBE", self.state, MODEL,
                             retries=2, pause=0)
        self.assertEqual((d, src), (49, "measured"))

    def test_an_empty_local_render_is_a_failed_probe(self):
        # the closure's `not ids` guard: no render, no subtraction, nothing honest to bank
        d, src = probe_delta(ptok_of(120), lambda p: [], "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"))


class Banked(BankedBank):
    def test_a_dead_probe_spends_the_bank(self):
        self.write_bank(delta=49)
        d, src = probe_delta(ptok_of(None, None), render_of(), "PROBE", self.state, MODEL,
                             retries=2, pause=0)
        self.assertEqual((d, src), (49, "banked"), "the window must keep the boot's constant")

    def test_a_bank_belongs_to_the_model_that_measured_it(self):
        self.write_bank(model="qwen3.6-35b-a3b-q4_k_m", delta=42)
        d, src = probe_delta(ptok_of(None), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"), "a foreign boot's constant is not this boot's")

    def test_a_corrupt_bank_is_no_bank(self):
        geom_bank_path(self.state, MODEL).write_text("{not json", encoding="utf-8")
        d, src = probe_delta(ptok_of(None), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"))

    def test_a_bank_without_a_delta_is_no_bank(self):
        geom_bank_path(self.state, MODEL).write_text(json.dumps({"model": MODEL}), encoding="utf-8")
        d, src = probe_delta(ptok_of(None), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"))


class NoBankAtAll(BankedBank):
    def test_the_first_run_of_a_boot_falls_back_to_zero(self):
        d, src = probe_delta(ptok_of(None), render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"))

    def test_the_probe_never_raises_at_the_sweep(self):
        def boom(content):
            raise ConnectionResetError("engine away")
        d, src = probe_delta(boom, render_of(), "PROBE", self.state, MODEL, pause=0)
        self.assertEqual((d, src), (0, "none"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
