"""Hub-server: viser skallen, og sender /b/<key>/... videre til hver bots eget dashboard (kun GET)."""
from __future__ import annotations

import base64
import hmac
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from .adapters import normalize
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = Path(__file__).with_name("shell.html")
STATIC = Path(__file__).with_name("static")
STATIC_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".webmanifest": "application/manifest+json", ".ico": "image/x-icon"}


def load_bots(path: Path | None = None) -> list[dict]:
    """Læser bots.json. Miljøvariabler kan ændre en bot:
    HUB_EXTERNAL_<BOT>=<port> eller =<vært>:<port>  botten kører allerede som egen service (fx Nova på serveren):
                                                    hubben viser den, men starter ingen ekstra kopi
    HUB_DISABLE_<BOT>=1                             slå botten fra på denne maskine (fx Nova på en Mac)"""
    bots = json.loads((path or ROOT / "bots.json").read_text(encoding="utf-8"))["bots"]
    for b in bots:
        key = b["key"].upper()
        m = re.fullmatch(r"(?:([A-Za-z0-9.-]+):)?(\d{1,5})", os.environ.get(f"HUB_EXTERNAL_{key}", ""))
        if m:
            b["external"], b["port"] = True, int(m.group(2))
            if m.group(1):
                b["host"] = m.group(1)
        elif os.environ.get(f"HUB_DISABLE_{key}") == "1":
            b["disabled"], b["note"] = True, "Slået fra på denne maskine. Botten kører et andet sted (fx din server)."
    return bots


def bot_host(bot: dict) -> str:
    return bot.get("host", "127.0.0.1")


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
    url = f"http://{bot_host(bot)}:{bot['port']}{sub}" + (f"?{query}" if query else "")
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


LOG_DIR = Path(os.environ.get("HUB_LOG_DIR", ROOT / "logs"))


def last_problem(bot: dict) -> str:
    """Sidste fejllinje i botens log (til at forklare, hvorfor den ikke scanner), ellers tom tekst."""
    for name in (f"{bot['key']}-motor.log", f"{bot['key']}.log"):      # motoren (hvis botten har en) skriver typisk fejlene
        try:
            tail = (LOG_DIR / name).read_bytes()[-8000:].decode("utf-8", "replace")
        except OSError:
            continue
        for line in reversed(tail.splitlines()):
            if re.search(r"Error|Exception|fejlede|svarer ikke|spærret|Traceback", line) and 'File "' not in line:
                return line.strip()[-170:]
    return ""


STALE_AFTER_S = 20 * 60          # så længe uden scanning før overblikket advarer
RESTART_AFTER_S = 45 * 60        # så længe uden scanning før vagthunden genstarter en bot


def scan_age(bot: dict) -> float | None:
    """Sekunder siden botten sidst scannede markedet, eller None hvis det ikke kan ses."""
    try:
        ts = bot_data(bot).get("scan")
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return max(0.0, time.time() - ts) if ts else None


def best_of(strategies: list[dict]) -> dict | None:
    rows = [s for s in strategies if isinstance(s.get("return_pct"), (int, float))]
    if not rows:
        return None
    top = max(rows, key=lambda r: r["return_pct"])
    return {"name": top["name"], "return_pct": round(top["return_pct"], 2), "trades": top.get("trades") or 0,
            "count": len(rows), "positive": sum(1 for r in rows if r["return_pct"] > 0)}


BOTS_DIR = Path(os.environ.get("HUB_BOTS_DIR", ROOT / "bots"))


def not_installed(bot: dict) -> bool:
    """En bot med repo, som hverken kører et andet sted eller er slået fra, men som ikke er hentet til denne maskine."""
    return bool(bot.get("repo")) and not bot.get("external") and not bot.get("disabled") \
        and not (BOTS_DIR / bot["repo"].split("/")[-1]).exists()


def bot_overview(bot: dict) -> dict:
    out = {"key": bot["key"], "name": bot["name"], "short": bot.get("short", ""), "invests": bot.get("invests", ""),
           "configured": bool(bot.get("repo")) and not bot.get("disabled"), "note": bot.get("note", ""),
           "up": not bot.get("disabled") and port_open(bot["port"], bot_host(bot)), "mode": "live", "best": None}
    ln = bot.get("launch") or {}
    if ln.get("needs_env") and not os.environ.get(ln["needs_env"]):
        out["mode"] = "dashboard"     # nøgle mangler: kun gemte data, ingen live handler
    out["scan_age"], out["issue"], out["trades"] = None, "", None
    out["note_short"] = "Slået fra her" if bot.get("disabled") else ""
    if not_installed(bot):
        out["configured"], out["up"] = False, False
        out["note"], out["note_short"] = "Ikke hentet til denne maskine. Kør: python3 -m hub fetch", "Ikke hentet her"
    if out["up"]:
        try:
            data = bot_data(bot)
            out["best"] = best_of(data["strategies"])
            out["trades"] = {"open": sum(x.get("open") or 0 for x in data["strategies"]),
                             "closed": sum(x.get("trades") or 0 for x in data["strategies"])}
            out["scan_age"] = max(0.0, time.time() - data["scan"]) if data.get("scan") else None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if out["scan_age"] is None or out["scan_age"] > STALE_AFTER_S:
            out["issue"] = data.get("problem") or last_problem(bot)
    return out


class Throttle:
    """Bremser gætning af adgangskoden: efter MAX_FAILS forkerte forsøg fra samme adresse spærres den, først i BASE sekunder,
    derefter dobbelt så længe for hvert nyt forkert forsøg (højst CAP). Et rigtigt forsøg nulstiller."""

    def __init__(self, max_fails: int = 5, base: float = 60.0, cap: float = 900.0, now=time.monotonic):
        self.max_fails, self.base, self.cap, self.now = max_fails, base, cap, now
        self.state: dict[str, list[float]] = {}          # adresse -> [antal fejl, spærret til]
        self.lock = threading.Lock()

    def locked(self, ip: str) -> float:
        with self.lock:
            st = self.state.get(ip)
            return max(0.0, st[1] - self.now()) if st else 0.0

    def failed(self, ip: str) -> None:
        with self.lock:
            if len(self.state) > 5000:                    # hold hukommelsen i ave under et angreb fra mange adresser
                self.state = {k: v for k, v in self.state.items() if v[1] > self.now()}
            st = self.state.setdefault(ip, [0, 0.0])
            st[0] += 1
            if st[0] >= self.max_fails:
                st[1] = self.now() + min(self.cap, self.base * 2 ** (st[0] - self.max_fails))

    def ok(self, ip: str) -> None:
        with self.lock:
            self.state.pop(ip, None)


def client_ip(peer: str, forwarded: str | None) -> str:
    """Klientens adresse. Kommer forbindelsen fra maskinen selv (Tailscale Funnel/Serve), bruges den SIDSTE adresse i
    X-Forwarded-For, som proxyen selv tilføjer. De første kan klienten have opfundet for at undgå spærringen."""
    if peer in ("127.0.0.1", "::1") and forwarded:
        last = forwarded.split(",")[-1].strip()
        if re.fullmatch(r"[0-9a-fA-F:.]{3,45}", last):
            return last
    return peer


def check_public_config(env) -> tuple[str, str | None]:
    """HUB_PUBLIC=1 betyder, at hubben nås fra internettet (via Tailscale Funnel). Så kræves en lang adgangskode, og hubben
    åbner kun på denne maskine (127.0.0.1), så al trafik går gennem den krypterede tunnel. Returnerer (vært, fejltekst)."""
    host = env.get("HUB_HOST", "127.0.0.1")
    if env.get("HUB_PUBLIC") != "1":
        return host, None
    if len(env.get("HUB_PASSWORD", "")) < 12:
        return "127.0.0.1", "HUB_PUBLIC=1 kræver en adgangskode på mindst 12 tegn (HUB_PASSWORD). Kør ./deploy/public.sh on"
    return "127.0.0.1", None


def make_handler(bots: list[dict], throttle: Throttle | None = None):
    by_key = {b["key"]: b for b in bots}
    password = os.environ.get("HUB_PASSWORD", "")
    throttle = throttle or Throttle()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, ctype: str, body: bytes, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                       "X-Frame-Options": "SAMEORIGIN", **(extra or {})}
            if self.headers.get("X-Forwarded-Proto") == "https":
                headers["Strict-Transport-Security"] = "max-age=31536000"
            for k, v in headers.items():
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
            return hmac.compare_digest(given.encode("utf-8"), password.encode("utf-8"))     # bytes: tekst med æøå kan ikke sammenlignes direkte

        def do_GET(self):  # noqa: N802
            path, _, query = self.path.partition("?")
            if path == "/healthz":
                return self._send(200, "text/plain", b"ok")
            name = "manifest.webmanifest" if path == "/manifest.webmanifest" else path[8:] if path.startswith("/static/") else None
            if name is not None:        # logo og manifest er ikke hemmelige, og telefonen henter dem uden login
                f = STATIC / name
                if re.fullmatch(r"[A-Za-z0-9._-]+", name) and f.suffix in STATIC_TYPES and f.is_file():
                    return self._send(200, STATIC_TYPES[f.suffix], f.read_bytes(), {"Cache-Control": "public, max-age=86400"})
                return self._send(404, "text/plain; charset=utf-8", b"findes ikke")
            ip = client_ip(self.client_address[0], self.headers.get("X-Forwarded-For"))
            wait = throttle.locked(ip) if password else 0
            if wait:
                return self._send(429, "text/plain; charset=utf-8", "For mange forkerte forsøg. Prøv igen om lidt.".encode(),
                                  {"Retry-After": str(int(wait) + 1)})
            if not self._authorized():
                if self.headers.get("Authorization"):          # et forsøg med forkert kode tæller; første kald uden kode gør ikke
                    throttle.failed(ip)
                return self._send(401, "text/plain", b"login", {"WWW-Authenticate": 'Basic realm="hub"'})
            if password and self.headers.get("Authorization"):
                throttle.ok(ip)
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, "text/html; charset=utf-8", SHELL.read_bytes())
                if path == "/api/bots":
                    out = [{"key": b["key"], "name": b["name"], "desc": b.get("desc", ""),
                            "short": b.get("short", ""),
                            "configured": bool(b.get("repo")) and not b.get("disabled"), "note": b.get("note", ""), "note_short": "Slået fra her" if b.get("disabled") else "",
                            "up": not b.get("disabled") and port_open(b["port"], bot_host(b))} for b in bots]
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
    host, problem = check_public_config({**os.environ, "HUB_HOST": host})
    if problem:
        raise SystemExit(problem)
    if os.environ.get("HUB_PUBLIC") == "1":
        print("Offentlig tilstand: hubben åbner kun på 127.0.0.1 og nås gennem den krypterede tunnel.", flush=True)
    if host not in ("127.0.0.1", "localhost") and not os.environ.get("HUB_PASSWORD"):
        print("ADVARSEL: hubben er åben på netværket uden HUB_PASSWORD.")
    httpd = ThreadingHTTPServer((host, port), make_handler(bots))
    httpd.daemon_threads = True
    print(f"Hub: http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
