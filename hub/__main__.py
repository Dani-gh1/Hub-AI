"""python3 -m hub {serve,run,fetch,status}

serve  kun hubben (botterne kører allerede på deres egne porte)
run    starter alle installerede botter og hubben
fetch  henter manglende botter fra GitHub ind i bots/
status viser hvad der er installeret og kører
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .server import ROOT, load_bots, port_open, serve

BOTS_DIR = Path(os.environ.get("HUB_BOTS_DIR", ROOT / "bots"))


def bot_dir(bot: dict) -> Path:
    return BOTS_DIR / bot["repo"].split("/")[-1] if bot.get("repo") else BOTS_DIR / bot["key"]


def commands(bot: dict) -> list[list[str]]:
    """Kommandoer der starter botten med dashboard kun på 127.0.0.1:<port> (nogle botter bruger to processer)."""
    ln, port = bot["launch"], bot["port"]
    if ln["kind"] == "flag":
        return [[sys.executable, "-m", "desk", *[a.format(port=port) for a in ln["args"]]]]
    out = []
    all_args = [ln["args"], *ln.get("also", [])]
    if ln.get("needs_env") and not os.environ.get(ln["needs_env"]):
        all_args = [ln["fallback_args"]]   # fx kun dashboardet, når datakildens nøgle mangler
        print(f"· {bot['name']}: {ln['needs_env']} er ikke sat – viser kun dashboardet (ingen live handler)")
    for args in all_args:
        code = ("import sys, runpy, importlib; c = importlib.import_module(%r); "
                "c.DASHBOARD_PORT = %d; c.DASHBOARD_HOST = '127.0.0.1'; "
                "sys.argv = ['desk'] + %r; runpy.run_module('desk', run_name='__main__')"
                % (ln["config"], port, args))
        out.append([sys.executable, "-c", code])
    return out


def cmd_fetch(bots) -> None:
    BOTS_DIR.mkdir(parents=True, exist_ok=True)
    for b in bots:
        if not b.get("repo"):
            print(f"- {b['name']}: ingen repo sat i bots.json endnu")
        elif bot_dir(b).exists():
            print(f"✓ {b['name']}: findes allerede")
        else:
            print(f"↓ {b['name']}: henter {b['repo']}")
            subprocess.run(["git", "clone", "-q", f"https://github.com/{b['repo']}.git", str(bot_dir(b))], check=False)


def cmd_status(bots) -> None:
    for b in bots:
        inst = "installeret" if b.get("repo") and bot_dir(b).exists() else "mangler"
        run = "kører" if port_open(b["port"]) else "kører ikke"
        print(f"{b['name']:<12} {inst:<12} {run:<11} port {b['port']}")


def cmd_run(bots, host: str, port: int) -> None:
    procs = []
    for b in bots:
        d = bot_dir(b)
        if not b.get("repo") or not d.exists() or "launch" not in b:
            print(f"· springer {b['name']} over (ikke installeret)")
            continue
        for cmd in commands(b):
            procs.append((b, subprocess.Popen(cmd, cwd=d, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)))
        print(f"▶ {b['name']} på port {b['port']}")

    def stop(*_):
        for _b, p in procs:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    time.sleep(1.5)
    try:
        serve(host, port, bots)
    finally:
        for _b, p in procs:
            p.terminate()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hub", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["serve", "run", "fetch", "status"])
    ap.add_argument("--host", default=os.environ.get("HUB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("HUB_PORT", "8080")))
    a = ap.parse_args(argv)
    bots = load_bots()
    {"fetch": lambda: cmd_fetch(bots), "status": lambda: cmd_status(bots),
     "run": lambda: cmd_run(bots, a.host, a.port), "serve": lambda: serve(a.host, a.port, bots)}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
