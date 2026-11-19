"""Sikkerhedskopi af botternes data (statistik, papirbøger, handler), så intet går tabt uanset hvad der sker.

Botternes data ligger uden for git (data/, var/, runs/, state.json, *.sqlite3 …). Før hver opdatering og mindst hver 6. time
(når hubben starter) pakkes alt, som git ignorerer, i backups/<tidspunkt>/<bot>.tar.gz. De 14 nyeste beholdes pr. bot.
Gendan en bot: tar -xzf backups/<tidspunkt>/<bot>.tar.gz -C bots/<bot>   (mens hubben er stoppet).
"""
from __future__ import annotations

import os
import subprocess
import tarfile
import time
from pathlib import Path

KEEP = 14
EVERY = 6 * 3600
SKIP = ("__pycache__", ".pyc", "/logs/", "node_modules")


def data_files(d: Path) -> list[str]:
    r = subprocess.run(["git", "-C", str(d), "ls-files", "--others", "--ignored", "--exclude-standard", "-z"], capture_output=True, text=True, timeout=60)
    names = [n for n in r.stdout.split("\0") if n]
    return [n for n in names if not any(s in "/" + n for s in SKIP) and (d / n).is_file()]


def backup_dir(root: Path) -> Path:
    return Path(os.environ.get("HUB_BACKUP_DIR", root / "backups"))


def _newest(base: Path) -> float:
    try:
        return max((p.stat().st_mtime for p in base.iterdir() if p.is_dir()), default=0.0)
    except OSError:
        return 0.0


def backup_bots(dirs: dict[str, Path], root: Path, say=print, force: bool = False, now=time.time) -> Path | None:
    """dirs = {botnøgle: mappe}. Returnerer mappen med kopien (eller None, hvis der ikke var noget nyt at gemme)."""
    base = backup_dir(root)
    if not force and now() - _newest(base) < EVERY:
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))
    out, made = base / stamp, 0
    seen: set[Path] = set()
    for key, d in dirs.items():
        if d.resolve() in seen:          # botter, der deler kode, deler også mappe: pak den kun én gang
            continue
        seen.add(d.resolve())
        try:
            files = data_files(d)
            if not files:
                continue
            out.mkdir(parents=True, exist_ok=True)
            with tarfile.open(out / f"{key}.tar.gz", "w:gz") as tar:
                for n in files:
                    try:
                        tar.add(d / n, arcname=n)
                    except OSError:
                        pass                                        # en fil, der netop skrives eller slettes: spring over
            made += 1
        except (OSError, subprocess.SubprocessError) as e:
            say(f"! sikkerhedskopi af {key} fejlede: {e}")
    if not made:
        return None
    prune(base)
    say(f"💾 sikkerhedskopi af botternes data: {out}")
    return out


def prune(base: Path, keep: int = KEEP) -> None:
    runs = sorted(p for p in base.iterdir() if p.is_dir())
    for old in runs[:-keep]:
        for f in old.iterdir():
            f.unlink(missing_ok=True)
        old.rmdir()
