#!/usr/bin/env bash
# Gør dashboardet nåbart fra hvor som helst (telefon, arbejde, ferie) med HTTPS og adgangskode, via Tailscale Funnel.
#   ./deploy/public.sh on       slå offentlig adgang til (laver en lang adgangskode, hvis der ikke er en)
#   ./deploy/public.sh off      slå det fra igen
#   ./deploy/public.sh status   vis adressen og indstillingerne
# Kør det på den maskine, hvor hubben kører, helst en server, der altid er tændt. Kræver Tailscale (gratis).
set -euo pipefail
OS="${HUB_OS:-$(uname -s)}"
DRY="${HUB_DRY_RUN:-0}"
if [ "$OS" = Darwin ]; then ENV_FILE="${HUB_ENV_FILE:-$HOME/Library/Application Support/Hub AI/hub.env}"; else ENV_FILE="${HUB_ENV_FILE:-/etc/hub.env}"; fi
[ -f "$ENV_FILE" ] || { echo "Fandt ikke $ENV_FILE. Kør først ./deploy/install.sh"; exit 1; }
SUDO=""; [ -w "$ENV_FILE" ] || SUDO="sudo"

TS="${HUB_TAILSCALE:-$(command -v tailscale || true)}"
[ -n "$TS" ] || { [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ] && TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale; }
[ -n "$TS" ] || { echo "Tailscale er ikke installeret her. Hent det på https://tailscale.com/download og log ind, og kør så scriptet igen."; exit 1; }

getvar() { grep "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- || true; }
setvar() { local tmp; tmp="$(mktemp)"; { grep -v "^$1=" "$ENV_FILE" || true; echo "$1=$2"; } > "$tmp"; $SUDO sh -c "cat '$tmp' > '$ENV_FILE'"; rm -f "$tmp"; }
restart() {
  [ "$DRY" = 1 ] && return 0
  if [ "$OS" = Darwin ]; then launchctl kickstart -k "gui/$(id -u)/ai.hub.dashboard"; else sudo systemctl restart hub; fi
}
PORT="$(getvar HUB_PORT)"; PORT="${PORT:-8080}"

funnel_url() { "$TS" funnel status 2>/dev/null | grep -oE 'https://[A-Za-z0-9.-]+\.ts\.net[^ ]*' | head -1 || true; }

case "${1:-status}" in
  on)
    "$TS" status >/dev/null 2>&1 || { echo "Tailscale er ikke logget ind. Kør: $TS up"; exit 1; }
    PW="$(getvar HUB_PASSWORD)"; NEWPW=""
    if [ "${#PW}" -lt 12 ]; then                      # offentligt kræver en lang adgangskode
      NEWPW="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 22)"; setvar HUB_PASSWORD "$NEWPW"
    fi
    [ -n "$(getvar HUB_HOST_BEFORE_PUBLIC)" ] || setvar HUB_HOST_BEFORE_PUBLIC "$(getvar HUB_HOST)"
    setvar HUB_PUBLIC 1; setvar HUB_HOST 127.0.0.1    # hubben åbner kun lokalt; al trafik går gennem den krypterede tunnel
    restart
    if [ "$DRY" != 1 ]; then for _ in $(seq 1 30); do curl -fs -m 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done; fi
    set +e; OUT="$("$TS" funnel --bg "$PORT" 2>&1)"; RC=$?
    if [ $RC -ne 0 ]; then OUT="$("$TS" funnel "$PORT" on 2>&1)"; RC=$?; fi        # ældre Tailscale-versioner
    set -e
    if [ $RC -ne 0 ]; then
      echo "✗ Tailscale Funnel kunne ikke slås til:"; echo "$OUT" | sed 's/^/    /'
      echo; echo "Funnel skal tillades én gang i din Tailscale-konto:"
      echo "  1. https://login.tailscale.com/admin/dns   → slå 'HTTPS Certificates' til"
      echo "  2. https://login.tailscale.com/admin/acls  → tillad Funnel (se linjen i fejlen ovenfor, eller tilføj 'funnel' under nodeAttrs)"
      echo "  Kør så scriptet igen."; exit 1
    fi
    URL="$(echo "$OUT" | grep -oE 'https://[A-Za-z0-9.-]+\.ts\.net[^ ]*' | head -1)"; URL="${URL:-$(funnel_url)}"
    echo "✓ Dashboardet er nu åbent fra hele internettet, med HTTPS og adgangskode."
    echo
    echo "  Adresse:     ${URL:-(se: $TS funnel status)}"
    echo "  Brugernavn:  valgfrit"
    echo "  Adgangskode: ${NEWPW:-$(getvar HUB_PASSWORD)}"
    [ -n "$URL" ] && echo "  Til telefonen (gemmer adressen): https://dani-gh1.github.io/Hub-AI/?server=${URL%/}"
    echo
    echo "Tip: gem adgangskoden i telefonens adgangskodeadministrator. Efter 5 forkerte forsøg spærres adressen i et minut, derefter længere." ;;
  off)
    set +e
    "$TS" funnel --https=443 off >/dev/null 2>&1 || "$TS" funnel "$PORT" off >/dev/null 2>&1 || "$TS" funnel reset >/dev/null 2>&1
    set -e
    setvar HUB_PUBLIC 0
    BEFORE="$(getvar HUB_HOST_BEFORE_PUBLIC)"; [ -n "$BEFORE" ] && setvar HUB_HOST "$BEFORE"
    restart
    echo "✓ Offentlig adgang er slået fra. Dashboardet kan kun åbnes som før (${BEFORE:-kun på denne maskine})." ;;
  status)
    echo "Offentlig tilstand: $( [ "$(getvar HUB_PUBLIC)" = 1 ] && echo til || echo fra )   Vært: $(getvar HUB_HOST)   Port: $PORT"
    URL="$(funnel_url)"; echo "Adresse: ${URL:-ingen aktiv Funnel-adresse}" ;;
  *) echo "Brug: $0 on | off | status"; exit 1 ;;
esac
