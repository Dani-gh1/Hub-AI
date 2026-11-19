"""Holder botternes kode ajour: git pull (kun fast-forward) i hver hentet bot. Rører aldrig botternes data (de er ikke i git)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(d: Path, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, timeout=timeout)


def update_dir(d: Path) -> tuple[str, str]:
    """Returnerer (status, tekst): 'ny' (opdateret), 'ens' (allerede nyeste) eller 'fejl'."""
    if not (d / ".git").exists():
        return "fejl", "ingen git-mappe"
    try:
        before = _git(d, "rev-parse", "HEAD").stdout.strip()
        pull = _git(d, "pull", "--ff-only", "-q")
        if pull.returncode != 0:
            return "fejl", (pull.stderr.strip().splitlines() or ["git pull fejlede"])[-1][:140]
        after = _git(d, "rev-parse", "HEAD").stdout.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return "fejl", str(e)[:140]
    return ("ens", "allerede nyeste") if before == after else ("ny", f"{before[:7]} → {after[:7]}")


def update_bots(bots: list[dict], bot_dir, say=print, quiet_same: bool = False) -> dict[str, str]:
    """Opdaterer alle hentede botter (springer slåede fra og eksterne over). Returnerer {bot: status}."""
    out = {}
    for b in bots:
        if b.get("disabled") or b.get("external") or not b.get("repo"):
            continue
        d = bot_dir(b)
        if not d.exists():
            continue
        status, text = update_dir(d)
        out[b["key"]] = status
        if status == "fejl":
            say(f"! {b['name']}: kunne ikke opdateres ({text}). Kører videre med den kode, der er hentet.")
        elif status == "ny" or not quiet_same:
            say(f"{'↑' if status == 'ny' else '✓'} {b['name']}: {text}")
    return out
