"""Bruges af deploy/verify.sh: læser /api/overview (JSON på stdin), skriver en linje pr. bot og afslutter med antal botter med problemer."""
from __future__ import annotations

import json
import sys

STALE = 1200      # sekunder uden scanning før en kørende bot regnes for et problem


def judge(rows: list[dict]) -> tuple[list[str], int]:
    lines, bad = [], 0
    for r in rows:
        n = r["name"]
        if not r.get("configured"):
            lines.append(f"  – {n}: {r.get('note_short') or 'ikke sat op her'} (tæller ikke med)")
            continue
        t = r.get("trades") or {}
        trades = f"{t.get('open', 0)} åbne / {t.get('closed', 0)} lukkede"
        age = r.get("scan_age")
        issue = f" – {r['issue']}" if r.get("issue") else ""
        if not r.get("up"):
            bad += 1
            lines.append(f"  ✗ {n}: kører ikke{issue}")
        elif r.get("idle"):
            lines.append(f"  ✓ {n}: venter på børsen ({r['idle']})")
        elif age is not None and age <= STALE:
            lines.append(f"  ✓ {n}: scanner (for {int(age)} s siden), {trades}")
        else:
            bad += 1
            lines.append(f"  ✗ {n}: kører, men scanner ikke" + (issue or " (ingen scanning set i 20 min.)"))
    return lines, bad


def main() -> int:
    try:
        rows = json.load(sys.stdin)
    except Exception:
        print("  ✗ Kunne ikke hente botternes status fra hubben")
        return 99
    lines, bad = judge(rows)
    print("\n".join(lines))
    return bad


if __name__ == "__main__":
    sys.exit(main())
