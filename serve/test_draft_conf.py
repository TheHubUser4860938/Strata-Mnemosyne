"""POST /v1/conf: the drafter's bar on the running engine - the CONF command's line and answer, the route, the
bar /metrics reports to the Monitor, the busy and foreign-page refusals, and the unloaded answer that points at
the run config.  A bar sweep is a boot-free knob: the window rule reads it every window, so the next window is
drafted at the new value; --spec cannot say that (each row count is its own captured CUDA graph)."""
import io
import json
import queue
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from serve.frontend import ChatTemplate
from serve.server import ByteTokenizer, EngineDied, Service, StrataEngine, serve
from serve.test_lifecycle import ResidentEngine
from strata_control import drafting


class ConfEngine(ResidentEngine):
    """The resident test engine with a drafter's bar: CONF p moves it, bare CONF answers with what is in force."""
    def __init__(self, tok, bar=0.7):
        super().__init__(tok)
        self.bar, self.calls = bar, []

    def conf(self, draft_conf, timeout=60.0):
        self.calls.append(draft_conf)
        if draft_conf is not None:
            self.bar = float(draft_conf)
        self.info["draft_conf"] = self.bar
        return {"draft_conf": self.bar}


class EngineCommand(unittest.TestCase):
    def engine(self, replies):
        e = StrataEngine("missing-executable", [], lazy=True)
        e.proc = mock.Mock()
        e.proc.poll.return_value = None
        e.proc.stdin = io.StringIO()
        e.ended = False
        e.lines = queue.Queue()
        for r in replies:
            e.lines.put(r)
        return e

    def test_the_line_and_the_answer(self):
        e = self.engine(["strata serve: something else\n", "CONF 0.60\n"])
        out = e.conf(0.6)
        self.assertEqual(e.proc.stdin.getvalue(), "CONF 0.6\n")     # %g: 0.60 writes as 0.6
        self.assertEqual(out, {"draft_conf": 0.6})
        self.assertEqual(e.info["draft_conf"], 0.6)                 # /metrics spreads info to the Monitor

    def test_bare_conf_asks_for_the_bar_in_force(self):
        e = self.engine(["CONF 0.70\n"])
        self.assertEqual(e.conf(None), {"draft_conf": 0.7})
        self.assertEqual(e.proc.stdin.getvalue(), "CONF\n")

    def test_refused_and_died(self):
        e = self.engine(["ERR CONF: send CONF <0..1> (the selector's cumulative bar)\n"])
        with self.assertRaises(ValueError) as c:
            e.conf(1.5)
        self.assertIn("cumulative bar", str(c.exception))
        e = self.engine([None])
        with self.assertRaises(EngineDied):
            e.conf(0.5)
        e = self.engine(["CONF not-a-number\n"])
        with self.assertRaises(EngineDied):
            e.conf(0.5)


class WhatTheStartSaid(unittest.TestCase):
    """The bar the config gave is in the engine facts from the start; a start that set none adds no key."""
    def test_the_bar_the_config_gave(self):
        info = drafting.engine_info(["--draft", "dflash2", "--draft-model", "/p", "--draft-conf", "0.7"])
        self.assertEqual(info["drafting"], "dflash2")
        self.assertEqual(info["draft_conf"], "0.7")

    def test_no_bar_no_key(self):
        self.assertEqual(drafting.engine_info(["--mtp", "/m"]), {"drafting": "mtp", "drafting_note": ""})


class Route(unittest.TestCase):
    def setUp(self):
        tok = ByteTokenizer()
        self.engine = ConfEngine(tok)
        self.svc = Service(self.engine, tok, ChatTemplate(Path(__file__).parent / "chat_template.jinja"))
        self.httpd = serve(self.svc, port=0)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.loads(response.read().decode())

    def test_the_bar_moves_and_the_monitor_sees_it(self):
        self.engine.loaded = True
        code, body = self.request("/v1/conf", {"draft_conf": 0.55})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["draft_conf"], 0.55)
        self.assertEqual(self.request("/metrics")[1]["engine"]["draft_conf"], 0.55)   # the card's Speculation row
        code, body = self.request("/v1/conf", {"draft_conf": None})                    # ask, do not set
        self.assertEqual(code, 200, body)
        self.assertEqual(body["draft_conf"], 0.55)
        self.assertEqual(self.engine.calls, [0.55, None])

    def test_bad_input_busy_and_foreign_pages(self):
        self.engine.loaded = True
        for bad in ({"draft_conf": -0.1}, {"draft_conf": 1.5}, {"draft_conf": "0.6"}, {"draft_conf": True}):
            self.assertEqual(self.request("/v1/conf", bad)[0], 400, bad)
        self.assertEqual(self.request("/v1/conf", {"draft_conf": 0.5}, {"Origin": "https://other.example"})[0], 403)
        self.assertEqual(self.request("/v1/conf", {"draft_conf": 0.5}, {"Content-Type": "text/plain"})[0], 415)
        self.svc.conf_wait_s = 0.2
        with self.svc.fifo:                                   # a request is running: the bar waits for it
            self.assertEqual(self.request("/v1/conf", {"draft_conf": 0.5})[0], 409)
        self.assertEqual(self.engine.calls, [])

    def test_an_unloaded_engine_points_at_the_run_config(self):
        code, body = self.request("/v1/conf", {"draft_conf": 0.8})
        self.assertEqual(code, 200, body)
        self.assertEqual(body["status"], "not loaded")
        self.assertEqual(body["draft_conf"], 0.8)
        self.assertIn("run config", body["note"])


if __name__ == "__main__":
    unittest.main()
