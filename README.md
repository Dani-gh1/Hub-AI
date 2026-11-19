# Papirdesk Hub

Én app med syv faner – én pr. papirhandels-bot – og underfaner under hver bot.
Kun papirhandel med fiktive penge.

| Fane | Repo | Underfaner |
|---|---|---|
| Atlas AI | Dani-gh1/Atlas | Oversigt, Strategier, Handler, Regler |
| Meridian AI | Dani-gh1/Meridian-AI | Oversigt, Strategier, Handler, Regler |
| Comet AI | Dani-gh1/Comet-AI | Oversigt, Strategier, Handler, Regler |
| Delphi AI | Dani-gh1/Delphi-AI | Oversigt, Strategier, Handler, Regler |
| Quasar AI | Dani-gh1/Quasar-AI | Oversigt, Strategier, Handler, Regler |
| Orion AI | Dani-gh1/Orion-AI | Oversigt, Strategier, Handler, Regler |
| Nova AI | Dani-gh1/Coins | Overblik, Handler, Marked, Desk |

## Kom i gang

```bash
python3 -m hub fetch
```

```bash
python3 -m hub run
```

Åbn <http://127.0.0.1:8080>. `fetch` henter botterne ind i `bots/`, `run` starter dem (hver på sin egen port, kun lokalt)
og hubben. `python3 -m hub status` viser hvad der kører. Kun Python 3.11+ standardbibliotek.

## Overblik

Første fane er **Overblik**: en tabel over, om alle botter kører, og en tabel med hver bots bedste strategi og dens
afkast i procent (sorteret, med antal lukkede handler). Fanenavnene viser, hvad hver bot investerer i, fx
*Nova AI (memecoins)*. Hvordan den bedste strategi findes, står pr. bot under `best` i `bots.json`.

## Sådan virker det

* Hver bot beholder sit eget dashboard. Hubben sender `/b/<bot>/…` videre til det (kun GET) og skjuler botens egen
  fanelinje. Hubbens underfaner klikker på botens faner indenfor iframen.
* Adresser kan deles: `#quasar/regler`.
* Hubben åbner kun på 127.0.0.1. Skal den åbnes på netværket: sæt `HUB_PASSWORD` og start med `--host 0.0.0.0`.
  Har et dashboard sit eget login (fx Delphi), sæt `HUB_UPSTREAM_AUTH_DELPHI=bruger:kode`.

## Tilføj en ny bot

Tilføj en post i `bots.json` med `repo`, `port`, `launch`, `hide` og `tabs` (kopiér fra en eksisterende bot med samme opbygning), og kør `python3 -m hub fetch`.

## Test

```bash
python3 -m unittest discover -s tests -t .
```

## Hemmeligheder

Atlas og Meridian henter live kurser fra OANDA og kræver miljøvariablen `OANDA_TOKEN`, før deres `run` virker.
Mangler den, starter hubben kun deres dashboard (gemte data og regler), og de handler ikke. Sæt den, før du kører
`python3 -m hub run`, hvis de skal køre live.
