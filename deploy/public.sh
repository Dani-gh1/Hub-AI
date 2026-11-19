#!/usr/bin/env bash
# Åbn dashboardet fra hvor som helst via Tailscale (gratis, HTTPS, ingen åbne porte). Tre tilstande:
#   ./deploy/public.sh private       kun DINE egne enheder (med Tailscale) kan åbne det, fra hvor som helst. Ingen adgangskode nødvendig.
#   ./deploy/public.sh on            åbent for hele internettet, beskyttet af en lang adgangskode
#   ./deploy/public.sh open --yes    åbent for hele internettet UDEN adgangskode (alle, der kender adressen, kan se det)
#   ./deploy/public.sh off           slå det fra igen            ./deploy/public.sh status   vis adressen
# Kør det på den maskine, hvor hubben kører, helst en server, der altid er tændt.
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
url_of() { grep -oE 'https://[A-Za-z0-9.-]+\.ts\.net[^ ]*' | head -1 || true; }
funnel_url() { "$TS" funnel status 2>/dev/null | url_of; }
serve_url() { "$TS" serve status 2>/dev/null | url_of; }

need_login() { "$TS" status >/dev/null 2>&1 || { echo "Tailscale er ikke logget ind. Kør: $TS up"; exit 1; }; }
save_host() { [ -n "$(getvar HUB_HOST_BEFORE_PUBLIC)" ] || setvar HUB_HOST_BEFORE_PUBLIC "$(getvar HUB_HOST)"; setvar HUB_HOST 127.0.0.1; }   # hubben åbner kun lokalt
wait_hub() { [ "$DRY" = 1 ] || for _ in $(seq 1 30); do curl -fs -m 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done; }
tailscale_help() {
  echo "✗ Tailscale kunne ikke slå det til:"; echo "$1" | sed 's/^/    /'
  echo; echo "Det skal tillades én gang i din Tailscale-konto:"
  echo "  1. https://login.tailscale.com/admin/dns   → slå 'HTTPS Certificates' til"
  echo "  2. For internetadgang (on/open): https://login.tailscale.com/admin/acls → tillad Funnel (se linjen i fejlen ovenfor)"
  echo "  Kør så scriptet igen."
}
funnel_on() {
  set +e; OUT="$("$TS" funnel --bg "$PORT" 2>&1)"; RC=$?
  [ $RC -ne 0 ] && { OUT="$("$TS" funnel "$PORT" on 2>&1)"; RC=$?; }        # ældre Tailscale-versioner
  set -e; [ $RC -eq 0 ] || { tailscale_help "$OUT"; exit 1; }
  URL="$(echo "$OUT" | url_of)"; URL="${URL:-$(funnel_url)}"
}
serve_on() {
  set +e; "$TS" funnel --https=443 off >/dev/null 2>&1; OUT="$("$TS" serve --bg "$PORT" 2>&1)"; RC=$?
  [ $RC -ne 0 ] && { OUT="$("$TS" serve https / "http://127.0.0.1:$PORT" 2>&1)"; RC=$?; }
  set -e; [ $RC -eq 0 ] || { tailscale_help "$OUT"; exit 1; }
  URL="$(echo "$OUT" | url_of)"; URL="${URL:-$(serve_url)}"
}
phone_link() { [ -n "${URL:-}" ] && echo "  Til telefonen (gemmer adressen): https://dani-gh1.github.io/Hub-AI/?server=${URL%/}"; return 0; }

case "${1:-status}" in
  private)
    need_login
    setvar HUB_PASSWORD ""; setvar HUB_PUBLIC 0; setvar HUB_OPEN 0; save_host; restart; wait_hub; serve_on
    echo "✓ Dashboardet kan nu åbnes fra hvor som helst, men kun fra dine egne enheder med Tailscale. Ingen adgangskode."
    echo; echo "  Adresse: ${URL:-(se: $TS serve status)}"; phone_link
    echo; echo "Installér Tailscale-appen på telefonen og log ind med samme konto, så åbner adressen overalt. Andre kan ikke åbne den." ;;
  on)
    need_login
    PW="$(getvar HUB_PASSWORD)"; NEWPW=""
    if [ "${#PW}" -lt 12 ]; then NEWPW="$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 22)"; setvar HUB_PASSWORD "$NEWPW"; fi
    save_host; setvar HUB_PUBLIC 1; setvar HUB_OPEN 0; restart; wait_hub; funnel_on
    echo "✓ Dashboardet er nu åbent fra hele internettet, med HTTPS og adgangskode."
    echo; echo "  Adresse:     ${URL:-(se: $TS funnel status)}"; echo "  Brugernavn:  valgfrit"; echo "  Adgangskode: ${NEWPW:-$(getvar HUB_PASSWORD)}"; phone_link
    echo; echo "Efter 5 forkerte forsøg spærres adressen i et minut, derefter længere." ;;
  open)
    if [ "${2:-}" != "--yes" ]; then
      echo "Det her åbner dashboardet for HELE internettet uden adgangskode. Alle, der finder adressen, kan se dine papirhandler og strategier"
      echo "(kun papirhandel, ingen rigtige penge, og ingen kan ændre noget). Adresser på .ts.net kan findes via certifikatlister."
      echo "Vil du kun selv kunne åbne det fra hvor som helst, så brug i stedet:  ./deploy/public.sh private"
      echo; echo "Er du sikker, så kør:  ./deploy/public.sh open --yes"; exit 1
    fi
    need_login
    setvar HUB_PASSWORD ""; save_host; setvar HUB_PUBLIC 1; setvar HUB_OPEN 1; restart; wait_hub; funnel_on
    echo "✓ Dashboardet er nu åbent for alle uden adgangskode (kun læsning)."
    echo; echo "  Adresse: ${URL:-(se: $TS funnel status)}"; phone_link
    echo; echo "Hastighedsgrænse: højst 240 forespørgsler i minuttet pr. besøgende. Slå det fra igen med: ./deploy/public.sh off" ;;
  off)
    set +e
    "$TS" funnel --https=443 off >/dev/null 2>&1 || "$TS" funnel "$PORT" off >/dev/null 2>&1
    "$TS" serve --https=443 off >/dev/null 2>&1 || "$TS" serve "$PORT" off >/dev/null 2>&1
    set -e
    setvar HUB_PUBLIC 0; setvar HUB_OPEN 0
    BEFORE="$(getvar HUB_HOST_BEFORE_PUBLIC)"; [ -n "$BEFORE" ] && setvar HUB_HOST "$BEFORE"
    restart
    echo "✓ Adgang udefra er slået fra. Dashboardet kan kun åbnes som før (${BEFORE:-kun på denne maskine})." ;;
  status)
    MODE="fra"; [ "$(getvar HUB_PUBLIC)" = 1 ] && MODE="internettet, $([ "$(getvar HUB_OPEN)" = 1 ] && echo "uden adgangskode" || echo "med adgangskode")"
    [ "$MODE" = fra ] && [ -n "$(serve_url)" ] && MODE="privat (kun dine egne enheder med Tailscale)"
    echo "Adgang: $MODE   Vært: $(getvar HUB_HOST)   Port: $PORT"
    echo "Adresse: $(funnel_url || true)$(serve_url || true)" ;;
  *) echo "Brug: $0 private | on | open --yes | off | status"; exit 1 ;;
esac
