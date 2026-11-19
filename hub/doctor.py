"""python3 -m hub doctor: tester de adresser, botterne henter data fra, og siger på dansk, hvad der er galt.

Typiske årsager: børsen er spærret i dit land (HTTP 451/403), DNS finder ikke adressen, eller netværket/routeren/et antivirus-
program overvåger forbindelsen, så certifikatet afvises ("self-signed certificate in certificate chain").
"""
from __future__ import annotations

import http.client
import socket
import ssl
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT = 8
PUBLIC_CAS = ("digicert", "amazon", "google trust", "let's encrypt", "isrg", "cloudflare", "sectigo", "globalsign", "microsoft",
              "comodo", "godaddy", "entrust", "starfield", "usertrust", "baltimore", "gts")


def status_verdict(code: int) -> tuple[bool, str]:
    if code == 451:
        return False, "spærret (HTTP 451: ikke tilladt i dit land eller hos din udbyder)"
    if code == 403:
        return False, "afvist (HTTP 403: ofte en geo-spærring af dit land eller datacenter)"
    if code == 429:
        return True, "svarer (HTTP 429: for mange kald lige nu)"
    return True, f"svarer (HTTP {code})"


def issuer_of(host: str, port: int = 443) -> str:
    """Hvem har udstedt certifikatet, selv om det ikke godkendes? (Afslører en overvågende proxy eller et antivirusprogram.)"""
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        with socket.create_connection((host, port), TIMEOUT) as s, ctx.wrap_socket(s, server_hostname=host) as t:
            pem = ssl.DER_cert_to_PEM_cert(t.getpeercert(True))
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pem)
        try:
            info = ssl._ssl._test_decode_cert(f.name)                     # type: ignore[attr-defined]
        finally:
            Path(f.name).unlink(missing_ok=True)
        parts = {k: v for rdn in info.get("issuer", ()) for k, v in rdn}
        return parts.get("organizationName") or parts.get("commonName") or "ukendt udsteder"
    except Exception:
        return "ukendt udsteder"


def check(host: str, port: int = 443) -> tuple[bool, str]:
    try:
        socket.gethostbyname(host)
    except OSError:
        return False, "DNS finder ikke adressen (internet nede, eller adressen er blokeret af DNS)"
    try:
        conn = http.client.HTTPSConnection(host, port, timeout=TIMEOUT, context=ssl.create_default_context())
        conn.request("GET", "/", headers={"User-Agent": "Mozilla/5.0 (hub doctor)"})
        code = conn.getresponse().status
        conn.close()
        return status_verdict(code)
    except ssl.SSLCertVerificationError as e:
        who = issuer_of(host, port)
        reason = getattr(e, "verify_message", "") or str(e)
        if any(ca.lower() in who.lower() for ca in PUBLIC_CAS):
            return False, (f"certifikatet er udstedt af {who} (en almindelig, troværdig udsteder), men Python kender ikke udstederen "
                           f"({reason}). Pythons rod-certifikater mangler, typisk for Python fra python.org på en Mac. "
                           "Det er ikke dit netværk. `python3 -m hub run` retter det selv; ellers kør Install Certificates.command")
        return False, (f"certifikatet afvises ({reason}). Udstedt af: {who}, som ikke er en kendt udsteder. Dit netværk, din router "
                       f"eller et antivirusprogram overvåger sandsynligvis forbindelsen til {host}")
    except (socket.timeout, TimeoutError):
        return False, "ingen svar inden for 8 sekunder (blokeret af firewall eller meget langsom forbindelse)"
    except OSError as e:
        return False, f"kunne ikke forbinde ({e.__class__.__name__}: {str(e)[:80]})"


def run(bots: list[dict], printer=print) -> int:
    """Tester alle botters adresser. Returnerer antal adresser, der fejler."""
    wanted = [(b, h) for b in bots if not b.get("disabled") and not b.get("external") for h in b.get("hosts", [])]
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(zip([(b["key"], h) for b, h in wanted], ex.map(lambda bh: check(bh[1]), wanted)))
    bad = 0
    for b in bots:
        if b.get("disabled") or b.get("external") or not b.get("hosts"):
            continue
        rows = [(h, *results[(b["key"], h)]) for h in b["hosts"]]
        ok_all = all(ok for _h, ok, _m in rows)
        printer(f"\n{'✓' if ok_all else '✗'} {b['name']}")
        for h, ok, msg in rows:
            printer(f"    {'✓' if ok else '✗'} {h:<28} {msg}")
            bad += 0 if ok else 1
    printer("")
    printer("Alt ser fint ud." if not bad else
            f"{bad} adresse(r) fejler. En bot, hvor alle adresser fejler, kan ikke scanne her. Kør den i stedet et andet sted, fx på serveren, "
            "eller skift netværk (fx mobilens hotspot) for at se, om det er dit netværk.")
    return bad
