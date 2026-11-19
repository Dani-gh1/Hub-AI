"""Hub-server: viser skallen, og sender /b/<key>/... videre til hver bots eget dashboard (kun GET)."""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .adapters import normalize
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = Path(__file__).with_name("shell.html")


def load_bots(path: Path | None = None) -> list[dict]:
    """Læser bots.json. HUB_EXTERNAL_<BOT>=<port> betyder, at botten allerede kører som egen service på den port
    (fx Nova på serveren): hubben viser den, men starter ingen ekstra kopi."""
    bots = json.loads((path or ROOT / "bots.json").read_text(encoding="utf-8"))["bots"]
    for b in bots:
        ext = os.environ.get(f"HUB_EXTERNAL_{b['key'].upper()}")
        if ext and ext.isdigit():
            b["port"], b["external"] = int(ext), True
    return bots


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def inject(html: bytes, key: str, hide: str) -> bytes:
    """Prefikser absolutte fetch-stier med /b/<key> og skjuler botens egen fanelinje."""
    snippet = (
        '<script>(function(){var P="/b/%s",f=window.fetch;window.fetch=function(u,o){'
        'if(typeof u==="string"&&u.charAt(0)==="/"&&u.charAt(1)!=="/"&&u.indexOf(P+"/")!==0)u=P+u;'
        'return f.call(this,u,o)}})()</script>' % key
    )
    if hide:
        snippet += "<style>%s{display:none!important}</style>" % hide
    text = html.decode("utf-8", "replace")
    text = re.sub(r'((?:src|href)=["\'])/(?![/]|b/)', r'\1/b/%s/' % key, text)
    m = re.search(r"<head[^>]*>", text, re.I)
    text = text[:m.end()] + snippet + text[m.end():] if m else snippet + text
    return text.encode("utf-8")


def upstream(bot: dict, sub: str, query: str = "", timeout: float = 15):
    """GET mod botens eget dashboard. Returnerer (statuskode, content-type, body); kaster OSError hvis den ikke svarer."""
    url = f"http://127.0.0.1:{bot['port']}{sub}" + (f"?{query}" if query else "")
    req = urllib.request.Request(url)
    auth = os.environ.get(f"HUB_UPSTREAM_AUTH_{bot['key'].upper()}")   # fx "user:kode" til Delphis dashboard
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", "application/octet-stream"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "text/plain"), e.read()


_cache: dict[str, tuple[float, dict]] = {}


def bot_data(bot: dict) -> dict:
    """Fælles format for én bot (cachet i 5 sekunder, så flere faner ikke belaster botten)."""
    hit = _cache.get(bot["key"])
    if hit and time.time() - hit[0] < 5:
        return hit[1]
    data = normalize(bot, lambda sub: upstream(bot, sub, timeout=10))
    _cache[bot["key"]] = (time.time(), data)
    return data


def best_of(strategies: list[dict]) -> dict | None:
    rows = [s for s in strategies if isinstance(s.get("return_pct"), (int, float))]
    if not rows:
        return None
    top = max(rows, key=lambda r: r["return_pct"])
    return {"name": top["name"], "return_pct": round(top["return_pct"], 2), "trades": top.get("trades") or 0,
            "count": len(rows), "positive": sum(1 for r in rows if r["return_pct"] > 0)}


def bot_overview(bot: dict) -> dict:
    out = {"key": bot["key"], "name": bot["name"], "short": bot.get("short", ""), "invests": bot.get("invests", ""),
           "configured": bool(bot.get("repo")), "up": port_open(bot["port"]), "mode": "live", "best": None}
    ln = bot.get("launch") or {}
    if ln.get("needs_env") and not os.environ.get(ln["needs_env"]):
        out["mode"] = "dashboard"     # nøgle mangler: kun gemte data, ingen live handler
    if out["up"]:
        try:
            out["best"] = best_of(bot_data(bot)["strategies"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return out


def make_handler(bots: list[dict]):
    by_key = {b["key"]: b for b in bots}
    password = os.environ.get("HUB_PASSWORD", "")

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not password:
                return True
            h = self.headers.get("Authorization", "")
            if not h.startswith("Basic "):
                return False
            try:
                given = base64.b64decode(h[6:]).decode().partition(":")[2]
            except Exception:
                return False
            return hmac.compare_digest(given, password)

        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            if path == "/healthz":
                return self._send(200, "text/plain", b"ok")
            if not self._authorized():
                return self._send(401, "text/plain", b"login", {"WWW-Authenticate": 'Basic realm="hub"'})
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, "text/html; charset=utf-8", SHELL.read_bytes())
                if path == "/api/bots":
                    out = [{"key": b["key"], "name": b["name"], "desc": b.get("desc", ""),
                            "short": b.get("short", ""),
                            "configured": bool(b.get("repo")), "up": port_open(b["port"])} for b in bots]
                    return self._send(200, "application/json", json.dumps(out).encode())
                if path == "/api/overview":
                    with ThreadPoolExecutor(max_workers=len(bots) or 1) as ex:
                        out = list(ex.map(bot_overview, bots))
                    return self._send(200, "application/json", json.dumps(out).encode())
                m = re.match(r"^/api/bot/([a-z0-9_-]+)$", path)
                if m and m.group(1) in by_key:
                    try:
                        return self._send(200, "application/json", json.dumps(bot_data(by_key[m.group(1)])).encode())
                    except (OSError, ValueError, KeyError, TypeError) as e:
                        return self._send(502, "application/json", json.dumps({"error": "Botten svarer ikke som forventet", "detail": str(e)[:200]}).encode())
                m = re.match(r"^/b/([a-z0-9_-]+)(/.*)?$", path)
                if m and m.group(1) in by_key:
                    if m.group(2) is None:
                        return self._send(302, "text/plain", b"", {"Location": f"/b/{m.group(1)}/"})
                    return self._proxy(by_key[m.group(1)], m.group(2), query)
                self._send(404, "text/plain; charset=utf-8", b"findes ikke")
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self._send(500, "application/json", b'{"error": "internal error"}')

        def _proxy(self, bot: dict, sub: str, query: str):
            try:
                code, ctype, body = upstream(bot, sub, query)
            except (urllib.error.URLError, OSError):
                msg = f"{bot['name']} kører ikke på port {bot['port']}.".encode()
                return self._send(502, "text/plain; charset=utf-8", msg)
            if ctype.startswith("text/html"):
                body = inject(body, bot["key"], bot.get("hide", ""))
            self._send(code, ctype, body)

        def log_message(self, *_a):
            pass

    return Handler


def serve(host: str, port: int, bots: list[dict] | None = None) -> None:
    bots = bots if bots is not None else load_bots()
    if host not in ("127.0.0.1", "localhost") and not os.environ.get("HUB_PASSWORD"):
        print("ADVARSEL: hubben er åben på netværket uden HUB_PASSWORD.")
    httpd = ThreadingHTTPServer((host, port), make_handler(bots))
    httpd.daemon_threads = True
    print(f"Hub: http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
