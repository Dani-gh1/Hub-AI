#!/usr/bin/env bash
# Installerer Papirdesk Hub på en Linux-server (Ubuntu), så alt kører 24/7 uden at nogen gør noget:
#   * starter automatisk ved boot og genstarter sig selv, hvis den går ned
#   * vagthunden i hubben genstarter botter, der går ned eller hænger
#   * henter nye versioner fra GitHub hvert kvarter (testet, med automatisk tilbagerulning)
# Kør én gang:   ./deploy/install.sh        (kan køres igen uden skade)
set -euo pipefail

HUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRY="${HUB_DRY_RUN:-0}"
ENV_FILE="${HUB_ENV_FILE:-/etc/hub.env}"
UNIT_DIR="${HUB_UNIT_DIR:-/etc/systemd/system}"
if [ "$(id -u)" -ne 0 ]; then exec sudo -E bash "$0" "$@"; fi
RUN_USER="${HUB_USER:-$(stat -c %U "$HUB_DIR")}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
PY="$(command -v python3)"
as_user() { if [ "$RUN_USER" != root ]; then runuser -u "$RUN_USER" -- "$@"; else "$@"; fi; }

echo "== Papirdesk Hub installeres (bruger: $RUN_USER, mappe: $HUB_DIR)"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11 eller nyere mangler: sudo apt install python3"; exit 1; }
command -v git >/dev/null || { echo "git mangler: sudo apt install git"; exit 1; }

# --- Nova kører måske allerede som egen service (så må hubben ikke starte en ekstra kopi) ---
NOVA_DIR="${HUB_NOVA_DIR:-$RUN_HOME/Coins}"
NOVA_SERVICE="${HUB_NOVA_SERVICE:-desk}"
NOVA_PORT=""
if [ "$DRY" != 1 ] && systemctl cat "$NOVA_SERVICE.service" >/dev/null 2>&1 && [ -d "$NOVA_DIR/.git" ]; then
  NOVA_PORT="$(systemctl cat "$NOVA_SERVICE.service" | grep -oE -- '--dashboard[ =]+[0-9]+' | grep -oE '[0-9]+' | head -1 || true)"
  NOVA_PORT="${NOVA_PORT:-8787}"
  echo "• Fandt Nova som tjenesten '$NOVA_SERVICE' (port $NOVA_PORT) i $NOVA_DIR – hubben viser den, men starter ingen kopi"
elif [ -n "${HUB_NOVA_PORT:-}" ]; then
  NOVA_PORT="$HUB_NOVA_PORT"
fi
if [ "$DRY" != 1 ]; then
  others="$(systemctl list-units --type=service --state=running --no-legend 2>/dev/null | grep -Ei 'papirdesk|desk' | grep -v "^ *$NOVA_SERVICE\.service" | grep -v '^ *hub' || true)"
  [ -n "$others" ] && { echo "• Der kører allerede andre desk-tjenester:"; echo "$others" | sed 's/^/    /'; echo "  Hubben starter sine egne kopier af de øvrige botter (hver med egen database). Stop de gamle, hvis du ikke vil have dem to gange."; }
fi

# --- hent botterne ---
if [ -n "$NOVA_PORT" ]; then export HUB_EXTERNAL_NOVA="$NOVA_PORT"; fi
( cd "$HUB_DIR" && as_user env ${HUB_EXTERNAL_NOVA:+HUB_EXTERNAL_NOVA="$HUB_EXTERNAL_NOVA"} "$PY" -m hub fetch )

# --- /etc/hub.env: oprettes første gang; eksisterende værdier overskrives aldrig ---
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
add() { grep -q "^$1=" "$ENV_FILE" || echo "$1=$2" >> "$ENV_FILE"; }
add HUB_HOST 0.0.0.0
add HUB_PORT 8080
if ! grep -q '^HUB_PASSWORD=' "$ENV_FILE"; then
  PASS="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)"
  echo "HUB_PASSWORD=$PASS" >> "$ENV_FILE"; NEWPASS="$PASS"
fi
if [ -n "$NOVA_PORT" ]; then
  add HUB_EXTERNAL_NOVA "$NOVA_PORT"; add HUB_UPDATE_NOVA_DIR "$NOVA_DIR"; add HUB_UPDATE_NOVA_SERVICE "$NOVA_SERVICE"
  add HUB_UPDATE_NOVA_BRANCH "$(as_user git -C "$NOVA_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)"
fi
grep -q '^#\? *OANDA_TOKEN=' "$ENV_FILE" || echo '#OANDA_TOKEN=   # fjern # og indsæt nøglen, hvis Atlas og Meridian skal handle live' >> "$ENV_FILE"

# --- systemd ---
sub() { sed -e "s#@USER@#$RUN_USER#g" -e "s#@DIR@#$HUB_DIR#g" -e "s#@PY@#$PY#g" "$1" > "$UNIT_DIR/$(basename "$1")"; }
mkdir -p "$UNIT_DIR"
for f in hub.service hub-update.service hub-update.timer; do sub "$HUB_DIR/deploy/$f"; done
chmod +x "$HUB_DIR/deploy/update.sh"
if [ "$DRY" = 1 ]; then echo "(tør kørsel: systemd røres ikke)"; exit 0; fi
systemctl daemon-reload
systemctl enable --now hub.service hub-update.timer
sleep 5
systemctl is-active --quiet hub.service && echo "✓ hub kører" || { echo "✗ hub startede ikke: sudo journalctl -u hub -n 30"; exit 1; }

IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"; IP="${IP:-$(hostname -I | awk '{print $1}')}"
PORT="$(grep '^HUB_PORT=' "$ENV_FILE" | cut -d= -f2)"
echo
echo "Færdig. Hubben åbner på:  http://$IP:$PORT"
echo "Brugernavn: valgfrit   Adgangskode: ${NEWPASS:-(den står i $ENV_FILE)}"
echo "Logs:    sudo journalctl -u hub -f      og botternes egne i $HUB_DIR/logs/"
echo "Status:  systemctl status hub           Opdatering: systemctl list-timers hub-update"
