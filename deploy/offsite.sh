#!/usr/bin/env bash
# Sender botternes sikkerhedskopier til et privat git-repo hver nat, så data overlever, selv om serveren forsvinder.
#   ./deploy/offsite.sh setup git@github.com:DIT-BRUGERNAVN/hub-data.git   én gang: gem adressen, lav nøgle, slå nattekørsel til
#   ./deploy/offsite.sh run                                                kør en sikkerhedskopi nu
#   ./deploy/offsite.sh restore <mappe>                                    hent kopierne ned igen på en ny server
set -euo pipefail
HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF="${HUB_OFFSITE_CONF:-$HOME/.hub-offsite}"
KEY="${HUB_OFFSITE_KEY:-$HOME/.ssh/hub_offsite}"
WORK="${HUB_OFFSITE_WORK:-$HOME/.hub-offsite-repo}"
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

case "${1:-run}" in
  setup)
    REMOTE="${2:?Skriv repo-adressen, fx git@github.com:dig/hub-data.git}"
    echo "$REMOTE" > "$CONF"
    mkdir -p "$(dirname "$KEY")"
    [ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -C "hub-offsite" -f "$KEY" >/dev/null
    ( crontab -l 2>/dev/null | grep -v "offsite.sh run" || true; echo "17 3 * * * $HUB_DIR/deploy/offsite.sh run >> $HOME/.hub-offsite.log 2>&1" ) | crontab -
    echo "✓ Nattekørsel kl. 03:17 er slået til."
    echo
    echo "Sidste trin: læg denne nøgle ind som deploy key MED skriveadgang i dit private repo"
    echo "(GitHub → repoet → Settings → Deploy keys → Add deploy key → sæt kryds i 'Allow write access'):"
    echo
    cat "$KEY.pub"
    echo
    echo "Test bagefter med: $HUB_DIR/deploy/offsite.sh run" ;;
  run)
    [ -f "$CONF" ] || { echo "Kør først: ./deploy/offsite.sh setup <repo-adresse>"; exit 1; }
    REMOTE="$(cat "$CONF")"
    (cd "$HUB_DIR" && python3 -m hub backup >/dev/null 2>&1 || true)
    SRC="${HUB_BACKUP_DIR:-$HUB_DIR/backups}"
    [ -d "$SRC" ] || { echo "Ingen backups at sende endnu."; exit 0; }
    if [ ! -d "$WORK/.git" ]; then
      git clone -q "$REMOTE" "$WORK" 2>/dev/null || { mkdir -p "$WORK"; git -C "$WORK" init -q -b main; git -C "$WORK" remote add origin "$REMOTE"; }
    fi
    git -C "$WORK" config user.name "hub-offsite"; git -C "$WORK" config user.email "hub-offsite@localhost"
    git -C "$WORK" pull -q --rebase origin main 2>/dev/null || true
    mkdir -p "$WORK/backups"
    cp -a "$SRC"/. "$WORK/backups/"                    # kun nye kopier; gamle slettes aldrig i repoet
    git -C "$WORK" add -A
    if git -C "$WORK" diff --cached --quiet; then echo "$(date -Is) intet nyt"; exit 0; fi
    git -C "$WORK" commit -q -m "Sikkerhedskopi $(date -Is)"
    git -C "$WORK" push -q origin HEAD:main
    echo "$(date -Is) ✓ sendt" ;;
  restore)
    DEST="${2:?Skriv en mappe, fx ~/hub-gendan}"
    [ -f "$CONF" ] || { echo "Skriv adressen: echo git@github.com:dig/hub-data.git > $CONF"; exit 1; }
    git clone -q "$(cat "$CONF")" "$DEST"
    echo "✓ Kopierne ligger i $DEST/backups. Gendan en bot: tar -xzf $DEST/backups/<tidspunkt>/<bot>.tar.gz -C bots/<bot>" ;;
  *) sed -n 2,6p "$0"; exit 1 ;;
esac
