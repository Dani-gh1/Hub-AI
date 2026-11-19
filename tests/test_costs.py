import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from hub.server import clean_costs, make_handler, net_strategies


class CleanTests(unittest.TestCase):
    def test_defaults_and_clamping(self):
        c = clean_costs({"capital": -5, "fee_pct": 999, "pos_pct": 0, "tax_pct": "x", "evil": 1, "currency": "<b>kr"})
        self.assertEqual((c["capital"], c["fee_pct"], c["pos_pct"], c["tax_pct"]), (0, 20, 0.1, 0.0))
        self.assertNotIn("evil", c)
        self.assertNotIn("<", c["currency"])
        self.assertTrue(clean_costs(None)["enabled"])         # efter omkostninger som standard
        self.assertEqual(clean_costs(None, {"slip_pct": 1.5})["slip_pct"], 1.5)      # botten egne standardtal

    def test_rejects_nan_and_bool(self):
        c = clean_costs({"capital": float("nan"), "fee_pct": True})
        self.assertEqual(c["capital"], 10000.0)
        self.assertEqual(c["fee_pct"], 0.1)


class NetTests(unittest.TestCase):
    def test_costs_reduce_return_per_trade_and_tax_only_on_gain(self):
        c = clean_costs({"capital": 10000, "fee_pct": 0.1, "slip_pct": 0.05, "pos_pct": 10, "tax_pct": 0})
        out = net_strategies([{"return_pct": 5.0, "trades": 40, "open": 2}, {"return_pct": None}], c)
        self.assertAlmostEqual(out[0]["return_pct"], 5.0 - 40 * 0.03 - 2 * 0.015, places=6)      # 0,03 % af kontoen pr. handel
        self.assertIsNone(out[1]["return_pct"])
        t = clean_costs({"fee_pct": 0, "slip_pct": 0, "tax_pct": 25})
        self.assertEqual(net_strategies([{"return_pct": 8.0, "trades": 0}, {"return_pct": -4.0, "trades": 0}], t)[0]["return_pct"], 6.0)
        self.assertEqual(net_strategies([{"return_pct": -4.0, "trades": 0}], t)[0]["return_pct"], -4.0)
        self.assertEqual(net_strategies([{"return_pct": 5.0, "trades": 9}], clean_costs({"enabled": False}))[0]["return_pct"], 5.0)


class ServerTests(unittest.TestCase):
    def serve(self, password=""):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HUB_COSTS_FILE"] = str(Path(self.tmp.name) / "costs.json")
        if password:
            os.environ["HUB_PASSWORD"] = password
        self.addCleanup(lambda: (os.environ.pop("HUB_COSTS_FILE", None), os.environ.pop("HUB_PASSWORD", None), self.tmp.cleanup()))
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler([{"key": "atlas", "name": "A", "port": 1}]))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(self, url, body=None, headers=None):
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers or {}, method="GET" if body is None else "POST")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_roundtrip(self):
        base = self.serve()
        self.assertEqual(self.call(base + "/api/costs/atlas")[1]["enabled"], True)
        st, saved = self.call(base + "/api/costs/atlas", {"enabled": True, "capital": 5000, "fee_pct": 0.25}, {"Content-Type": "application/json"})
        self.assertEqual(st, 200)
        self.assertEqual(self.call(base + "/api/costs/atlas")[1], saved)
        self.assertEqual((saved["enabled"], saved["capital"], saved["fee_pct"]), (True, 5000, 0.25))

    def test_rejects_unknown_bot_wrong_type_and_foreign_origin(self):
        base = self.serve()
        j = {"Content-Type": "application/json"}
        self.assertEqual(self.call(base + "/api/costs/nope", {}, j)[0], 404)
        self.assertEqual(self.call(base + "/api/costs/atlas", {}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call(base + "/api/costs/atlas", {}, {**j, "Origin": "https://evil.example"})[0], 403)

    def test_open_mode_visitors_from_the_internet_can_only_look(self):
        os.environ["HUB_OPEN"] = "1"
        self.addCleanup(lambda: os.environ.pop("HUB_OPEN", None))
        base = self.serve()
        j = {"Content-Type": "application/json"}
        self.assertEqual(self.call(base + "/api/costs/atlas", {"enabled": True}, {**j, "Tailscale-Funnel-Request": "?1"})[0], 403)
        self.assertEqual(self.call(base + "/api/costs/atlas")[0], 200)                  # men de kan godt se
        self.assertEqual(self.call(base + "/api/costs/atlas", {"enabled": True}, j)[0], 200)   # egne enheder (via Tailscale) kan ændre

    def test_post_needs_password(self):
        base = self.serve("hemmelig-kode")
        self.assertEqual(self.call(base + "/api/costs/atlas", {"enabled": True}, {"Content-Type": "application/json"})[0], 401)
        auth = {"Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(b"u:hemmelig-kode").decode()}
        self.assertEqual(self.call(base + "/api/costs/atlas", {"enabled": True}, auth)[0], 200)


if __name__ == "__main__":
    unittest.main()
