import json
from pathlib import Path
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hub.adapters import ADAPTERS, fmt, group_settings, points, ts
from hub import server as srv
from hub.server import best_of, inject, load_bots, make_handler


class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><head></head><body><img src='/static/a.png'></body></html>" if self.path == "/" else b'{"ok": 1}'
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/" else "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def start(handler, port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class HubTests(unittest.TestCase):
    def test_bots_json_has_seven_unique_bots(self):
        bots = load_bots()
        self.assertEqual(len(bots), 7)
        self.assertEqual(len({b["key"] for b in bots}), 7)
        self.assertEqual(len({b["port"] for b in bots}), 7)
        for b in bots:
            if b.get("repo"):
                self.assertTrue(b["launch"])
            self.assertIn(b["adapter"], ADAPTERS)

    def test_bots_can_be_external_on_another_host_or_disabled(self):
        import os
        os.environ.update({"HUB_EXTERNAL_NOVA": "100.64.0.9:8787", "HUB_EXTERNAL_ORION": "9999", "HUB_DISABLE_COMET": "1"})
        try:
            by = {b["key"]: b for b in load_bots()}
        finally:
            for k in ("HUB_EXTERNAL_NOVA", "HUB_EXTERNAL_ORION", "HUB_DISABLE_COMET"):
                del os.environ[k]
        self.assertEqual((by["nova"]["host"], by["nova"]["port"], by["nova"]["external"]), ("100.64.0.9", 8787, True))
        self.assertEqual((by["orion"]["port"], by["orion"].get("host")), (9999, None))
        self.assertTrue(by["comet"]["disabled"] and by["comet"]["note"])
        self.assertNotIn("external", by["delphi"])
        os.environ["HUB_EXTERNAL_NOVA"] = "ikke-et-tal; rm -rf"
        try:
            self.assertNotIn("external", {b["key"]: b for b in load_bots()}["nova"])   # ugyldig værdi ignoreres
        finally:
            del os.environ["HUB_EXTERNAL_NOVA"]

    def test_last_problem_reads_the_latest_error_line_from_the_bot_log(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.log").write_text('start\nTraceback (most recent call last):\n  File "a.py", line 3, in f\nValueError: dårlig\nok igen\n'
                                           'desk.net.HttpError: Ingen børs svarer (binance/bybit): spærret eller nede?\nstadig i gang\n')
            old = srv.LOG_DIR
            srv.LOG_DIR = Path(d)
            try:
                self.assertIn("Ingen børs svarer", srv.last_problem({"key": "x"}))
                self.assertEqual(srv.last_problem({"key": "findes-ikke"}), "")
            finally:
                srv.LOG_DIR = old

    def test_every_bot_has_label(self):
        for b in load_bots():
            self.assertTrue(b["short"] and b["invests"], b["key"])

    def test_best_of(self):
        rows = [{"name": "X", "return_pct": -1.5, "trades": 4}, {"name": "Y", "return_pct": 2.345, "trades": 30},
                {"name": "Z", "return_pct": None}]
        self.assertEqual(best_of(rows), {"name": "Y", "return_pct": 2.35, "trades": 30, "count": 2, "positive": 1})
        self.assertIsNone(best_of([]))
        self.assertIsNone(best_of([{"name": "Z", "return_pct": None}]))

    def test_adapter_helpers(self):
        self.assertEqual(ts(1795046573949), 1795046573.949)      # millisekunder
        self.assertEqual(ts(1795046573), 1795046573.0)
        self.assertEqual(ts("2026-11-19T00:00:00Z"), 1795046400.0)
        self.assertIsNone(ts(None))
        self.assertEqual(points([[1795000000, 1.23456], [1795000060, 2.0]]), [[1795000000.0, 1.235], [1795000060.0, 2.0]])
        self.assertEqual(points([0.5, 1.5]), [[0.0, 0.5], [1.0, 1.5]])   # uden tid bruges positionen
        self.assertEqual(fmt(True), "ja")
        self.assertEqual(fmt(0.50), "0,5")
        names = [g["title"] for g in group_settings({"SCOUT_X": 1, "FILTER_Y": 2, "DASHBOARD_PASSWORD": "hemmelig", "TICK": 3})]
        self.assertEqual(names, ["Scout", "Filter", "Drift"])
        self.assertNotIn("hemmelig", str(group_settings({"DASHBOARD_PASSWORD": "hemmelig", "NTFY_TOPIC": "x"})))

    def test_inject_prefixes_paths_and_hides_nav(self):
        out = inject(b"<head></head><img src='/x.png'><a href='/b/k/y'>", "k", "nav").decode()
        self.assertIn('"/b/k"', out)
        self.assertIn("nav{display:none!important}", out)
        self.assertIn("src='/b/k/x.png'", out)
        self.assertIn("href='/b/k/y'", out)  # allerede prefikset: røres ikke

    def test_proxy_and_status(self):
        up = start(Fake)
        bots = [{"key": "a", "name": "A", "repo": "x/y", "port": up.server_port, "adapter": "nova", "hide": "nav"},
                {"key": "b", "name": "B", "repo": None, "port": 1, "adapter": "nova"}]
        hub = start(make_handler(bots))
        base = f"http://127.0.0.1:{hub.server_port}"
        data = json.load(urllib.request.urlopen(base + "/api/bots"))
        self.assertTrue(data[0]["up"] and data[0]["configured"])
        self.assertFalse(data[1]["configured"])
        ov = json.load(urllib.request.urlopen(base + "/api/overview"))
        self.assertEqual([o["key"] for o in ov], ["a", "b"])
        self.assertTrue(ov[0]["up"] and ov[0]["best"] is None)  # fake-botten har ingen strategidata
        page = urllib.request.urlopen(base + "/b/a/").read().decode()
        self.assertIn("window.fetch", page)
        self.assertIn("/b/a/static/a.png", page)
        self.assertEqual(json.load(urllib.request.urlopen(base + "/b/a/api/x")), {"ok": 1})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/b/b/")
        self.assertEqual(e.exception.code, 502)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/b/ukendt/")
        self.assertEqual(e.exception.code, 404)

    def test_static_files_and_manifest_are_open_but_confined(self):
        import os
        os.environ["HUB_PASSWORD"] = "hemmelig"
        try:
            hub = start(make_handler([]))
        finally:
            del os.environ["HUB_PASSWORD"]
        base = f"http://127.0.0.1:{hub.server_port}"
        man = urllib.request.urlopen(base + "/manifest.webmanifest")            # uden login: telefonen henter den uden
        self.assertEqual(man.headers["Content-Type"], "application/manifest+json")
        data = json.load(man)
        self.assertEqual((data["display"], data["start_url"]), ("standalone", "/"))
        sizes = {(i["sizes"], i["purpose"]) for i in data["icons"]}
        self.assertEqual(sizes, {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")})
        for icon in data["icons"]:                                              # alle ikoner i manifestet findes
            r = urllib.request.urlopen(base + icon["src"])
            self.assertEqual((r.status, r.headers["Content-Type"]), (200, "image/png"))
            self.assertTrue(r.read().startswith(b"\x89PNG"))
        self.assertEqual(urllib.request.urlopen(base + "/static/logo.svg").headers["Content-Type"], "image/svg+xml")
        for bad in ("/static/../server.py", "/static/..%2fserver.py", "/static/shell.html", "/static/nope.png", "/static/"):
            with self.assertRaises(urllib.error.HTTPError, msg=bad) as e:
                urllib.request.urlopen(base + bad)
            self.assertEqual(e.exception.code, 404, bad)
        with self.assertRaises(urllib.error.HTTPError) as e:                    # selve dashboardet kræver stadig login
            urllib.request.urlopen(base + "/api/bots")
        self.assertEqual(e.exception.code, 401)

    def test_an_empty_password_means_no_login(self):
        import os
        os.environ["HUB_PASSWORD"] = ""
        try:
            hub = start(make_handler([]))
        finally:
            del os.environ["HUB_PASSWORD"]
        base = f"http://127.0.0.1:{hub.server_port}"
        self.assertEqual(urllib.request.urlopen(base + "/").status, 200)
        self.assertEqual(json.load(urllib.request.urlopen(base + "/api/bots")), [])

    def test_password(self):
        import base64, os
        os.environ["HUB_PASSWORD"] = "hemmelig"
        try:
            hub = start(make_handler([]))
        finally:
            del os.environ["HUB_PASSWORD"]
        base = f"http://127.0.0.1:{hub.server_port}"
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/")
        self.assertEqual(e.exception.code, 401)
        req = urllib.request.Request(base + "/", headers={"Authorization": "Basic " + base64.b64encode(b"x:hemmelig").decode()})
        self.assertEqual(urllib.request.urlopen(req).status, 200)


if __name__ == "__main__":
    unittest.main()
