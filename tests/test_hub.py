import json
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hub.server import inject, load_bots, make_handler


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
                self.assertTrue(b["tabs"] and b["launch"])

    def test_inject_prefixes_paths_and_hides_nav(self):
        out = inject(b"<head></head><img src='/x.png'><a href='/b/k/y'>", "k", "nav").decode()
        self.assertIn('"/b/k"', out)
        self.assertIn("nav{display:none!important}", out)
        self.assertIn("src='/b/k/x.png'", out)
        self.assertIn("href='/b/k/y'", out)  # allerede prefikset: røres ikke

    def test_proxy_and_status(self):
        up = start(Fake)
        bots = [{"key": "a", "name": "A", "repo": "x/y", "port": up.server_port, "tabs": [["t", "T", "#t"]], "hide": "nav"},
                {"key": "b", "name": "B", "repo": None, "port": 1, "tabs": []}]
        hub = start(make_handler(bots))
        base = f"http://127.0.0.1:{hub.server_port}"
        data = json.load(urllib.request.urlopen(base + "/api/bots"))
        self.assertTrue(data[0]["up"] and data[0]["configured"])
        self.assertFalse(data[1]["configured"])
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
