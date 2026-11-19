"""python3 -m hub report: samler alt, der skal bruges til at finde fejl, i én udskrift, som kan sendes videre."""
from __future__ import annotations

import base64
import json
import os
import platform
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import certs, doctor


def _tail(path: Path, n: int = 4) -> list[str]:
    try:
        return [l[:200] for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][-n:]
    except OSError:
        return []


def run(bots: list[dict], root: Path, bot_dir, port: int, printer=print) -> None:
    certs.setup(say=printer)
    printer("== Maskine")
    printer(f"python {platform.python_version()} ({sys.executable}) · {platform.platform()}")
    p = ssl.get_default_verify_paths()
    printer(f"certifikater: cafile={p.cafile} findes={Path(p.cafile).is_file() if p.cafile else False} · SSL_CERT_FILE={os.environ.get('SSL_CERT_FILE', '-')}")
    rev = lambda d: (subprocess.run(["git", "-C", str(d), "log", "-1", "--format=%h %cd", "--date=short"], capture_output=True, text=True).stdout.strip() or "?")
    printer(f"hub-version: {rev(root)}")
    for b in bots:
        if b.get("repo") and not b.get("external") and not b.get("disabled") and bot_dir(b).exists():
            printer(f"  {b['name']:<12} kode-version: {rev(bot_dir(b))}")

    printer("\n== Datakilder")
    doctor.run(bots, printer)

    printer("\n== Hubben")
    headers = {}
    if os.environ.get("HUB_PASSWORD"):
        headers["Authorization"] = "Basic " + base64.b64encode(f"x:{os.environ['HUB_PASSWORD']}".encode()).decode()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/overview", headers=headers)
        rows = json.load(urllib.request.urlopen(req, timeout=20))
        for r in rows:
            t = r.get("trades") or {}
            age = r.get("scan_age")
            printer(f"{r['name']:<12} {'kører' if r.get('up') else 'kører ikke':<11} scanner: {('for %d s siden' % age) if age is not None else 'ukendt':<22} "
                    f"handler: {t.get('open', '–')} åbne / {t.get('closed', '–')} lukkede  {r.get('note_short') or ''}")
            if r.get("issue"):
                printer(f"             problem: {r['issue']}")
    except Exception as e:
        printer(f"hubben svarer ikke på port {port} ({e.__class__.__name__}). Start den med: python3 -m hub run")

    printer("\n== Seneste logliner")
    logdir = Path(os.environ.get("HUB_LOG_DIR", root / "logs"))
    for b in bots:
        for name in (f"{b['key']}-motor.log", f"{b['key']}.log"):
            lines = _tail(logdir / name)
            if lines:
                printer(f"[{name}]")
                for l in lines:
                    printer(f"  {l}")
