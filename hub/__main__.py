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
from pathlib import Path

from .server import ROOT, bot_host, load_bots, port_open, scan_age, serve

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
        if b.get("disabled") or b.get("external"):
            print(f"· {b['name']}: hentes ikke på denne maskine")
        elif not b.get("repo"):
            print(f"- {b['name']}: ingen repo sat i bots.json endnu")
        elif bot_dir(b).exists():
            print(f"✓ {b['name']}: findes allerede")
        else:
            print(f"↓ {b['name']}: henter {b['repo']}")
            subprocess.run(["git", "clone", "-q", f"https://github.com/{b['repo']}.git", str(bot_dir(b))], check=False)


def cmd_status(bots) -> None:
    for b in bots:
        inst = "slået fra" if b.get("disabled") else "ekstern" if b.get("external") else "installeret" if b.get("repo") and bot_dir(b).exists() else "mangler"
        run = "kører" if port_open(b["port"], bot_host(b)) else "kører ikke"
        print(f"{b['name']:<12} {inst:<12} {run:<11} port {b['port']}")


def cmd_run(bots, host: str, port: int) -> None:
    from .supervisor import Supervisor, Unit
    units = []
    for b in bots:
        d = bot_dir(b)
        if b.get("disabled"):
            print(f"· {b['name']}: slået fra på denne maskine")
            continue
        if b.get("external"):
            print(f"· {b['name']}: kører allerede som egen service ({bot_host(b)}:{b['port']}) – starter ingen kopi")
            continue
        if not b.get("repo") or not d.exists() or "launch" not in b:
            print(f"· springer {b['name']} over (ikke installeret)")
            continue
        for i, cmd in enumerate(commands(b)):
            units.append(Unit(b["key"], b["name"] if i == 0 else f"{b['name']} (motor)", cmd, d, b["port"] if i == 0 else None,
                              None if i == 0 else f"{b['key']}-motor",
                              health=(lambda b=b: scan_age(b)) if i == 0 else None))
    sup = Supervisor(units, Path(os.environ.get("HUB_LOG_DIR", ROOT / "logs")), port_open)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    sup.start_thread()                       # botterne starter i baggrunden, så hubben svarer med det samme
    try:
        serve(host, port, bots)
    finally:
        sup.shutdown()


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
