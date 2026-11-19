# Papirdesk Hub

Én app med syv faner – én pr. papirhandels-bot – og underfaner under hver bot.
Kun papirhandel med fiktive penge.

| Fane | Repo |
|---|---|
| Atlas AI (forex) | Dani-gh1/Atlas |
| Meridian AI (forex) | Dani-gh1/Meridian-AI |
| Comet AI (nye tokens) | Dani-gh1/Comet-AI |
| Delphi AI (prognosemarkeder) | Dani-gh1/Delphi-AI |
| Quasar AI (krypto-futures) | Dani-gh1/Quasar-AI |
| Orion AI (krypto) | Dani-gh1/Orion-AI |
| Nova AI (memecoins) | Dani-gh1/Coins |

Hver bot har de samme fire sider, så alt ser ens ud:

* **Overblik**: nøgletal, en glat graf over alle strategiers afkast og én tabel med alle strategier.
* **Strategier**: et kort pr. strategi med tal og strategiens egne regler (søg og sortér).
* **Desk**: botten som system: status, tragt, hvorfor ting bliver dræbt, og agenternes regler og indstillinger.
* **Handler**: åbne og lukkede handler, filtrérbare pr. strategi.

## Kom i gang

```bash
python3 -m hub fetch
```

```bash
python3 -m hub run
```

Åbn <http://127.0.0.1:8080>. `fetch` henter botterne ind i `bots/`, `run` starter dem (hver på sin egen port, kun lokalt)
og hubben. `python3 -m hub status` viser hvad der kører. Kun Python 3.11+ standardbibliotek.

## Alle botter

Første fane er **Overblik** for alle botter: en tabel over, om de kører, og en tabel med hver bots bedste strategi.

## Sådan virker det

* Hubben henter hver bots data fra dens eget dashboard og omsætter den til ét fælles format (`hub/adapters.py`),
  så alle botter vises med samme design (`hub/shell.html`). Botternes egne dashboards er stadig tilgængelige under
  `/b/<bot>/` (link på Desk-siden).
* Adresser kan deles: `#quasar/regler`.
* Hubben åbner kun på 127.0.0.1. Skal den åbnes på netværket: sæt `HUB_PASSWORD` og start med `--host 0.0.0.0`.
  Har et dashboard sit eget login (fx Delphi), sæt `HUB_UPSTREAM_AUTH_DELPHI=bruger:kode`.

## Tilføj en ny bot

Tilføj en post i `bots.json` med `repo`, `port`, `launch`, `adapter` og `hide`, og skriv en adapter i `hub/adapters.py`, hvis botten har en anden datastruktur end de eksisterende (`forex`, `delphi`, `quasar`, `orion`, `comet`, `nova`). Kør derefter `python3 -m hub fetch`.

## Test

```bash
python3 -m unittest discover -s tests -t .
```

## Hemmeligheder

Atlas og Meridian henter live kurser fra OANDA og kræver miljøvariablen `OANDA_TOKEN`, før deres `run` virker.
Mangler den, starter hubben kun deres dashboard (gemte data og regler), og de handler ikke. Sæt den, før du kører
`python3 -m hub run`, hvis de skal køre live.
