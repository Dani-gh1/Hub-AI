# Papirdesk Hub

Én app med syv faner – én pr. papirhandels-bot – og underfaner under hver bot.
Kun papirhandel med fiktive penge.

| Fane | Repo | Underfaner |
|---|---|---|
| Atlas AI | (ikke koblet endnu) | – |
| Meridian AI | (ikke koblet endnu) | – |
| Comet AI | (ikke koblet endnu) | – |
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

## Sådan virker det

* Hver bot beholder sit eget dashboard. Hubben sender `/b/<bot>/…` videre til det (kun GET) og skjuler botens egen
  fanelinje. Hubbens underfaner klikker på botens faner indenfor iframen.
* Adresser kan deles: `#quasar/regler`.
* Hubben åbner kun på 127.0.0.1. Skal den åbnes på netværket: sæt `HUB_PASSWORD` og start med `--host 0.0.0.0`.
  Har et dashboard sit eget login (fx Delphi), sæt `HUB_UPSTREAM_AUTH_DELPHI=bruger:kode`.

## Tilføj Atlas, Meridian og Comet

Når deres kode ligger på GitHub: i `bots.json` sæt `repo`, `launch`, `hide` og `tabs` som for de andre,
og kør `python3 -m hub fetch`. Bruger en bot Pythons `desk`-pakke, kan `launch` kopieres fra Quasar.

## Test

```bash
python3 -m unittest discover -s tests -t .
```
