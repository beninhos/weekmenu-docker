# Weekmenu Planner

Weekmenu plannen, recepten beheren en de boodschappenlijst rechtstreeks naar je AH-app sturen. Draait als Docker-container (Flask + SQLite).

## Wat het doet

Maaltijden plannen per dag (ontbijt, lunch, diner), recepten beheren met ingrediënten en kookboeken, en een gesorteerde boodschappenlijst genereren. Ingrediënten worden samengevoegd op basis van een aliassysteem dat spellingsvarianten, meervouden en hoofdletterverschillen samenvoegt.

Recepten importeer je via URL (scraping, met Gemini 2.5 Flash als fallback) of door een foto van een kookboekpagina te maken. Gemini extraheert het recept inclusief ingrediënten en bereidingswijze.

De boodschappenlijst stuur je rechtstreeks naar je **Albert Heijn winkelwagentje** via de officieuze AH mobiele API — inclusief bonusaanduidingen en actuele prijzen.

## Installatie

```bash
git clone https://github.com/beninhos/weekmenu-docker.git
cd weekmenu-docker
mkdir -p static/uploads data
chmod 755 static/uploads data
docker-compose up --build
# → http://localhost:5001
```

Stel een Gemini API-sleutel in via **Instellingen** om foto-import en URL-scraping als fallback te gebruiken.

## Albert Heijn koppeling

AH gebruikt hCaptcha op de loginpagina die alleen werkt wanneer de browser de pagina ziet als `localhost`. Een ingebouwde Go reverse proxy ([gebaseerd op appie-go](https://github.com/gwillem/appie-go)) serveert de AH-loginpagina op poort 9002. Via een SSH-tunnel ziet je browser die pagina als localhost — waardoor de login werkt.

1. Open een SSH-tunnel vanaf je eigen computer:
   ```bash
   ssh -L 9002:localhost:9002 user@server
   ```
2. Ga naar **Instellingen** → **Start AH-koppelaar**
3. Open `http://localhost:9002` en log in met je AH-account

De app detecteert de koppeling automatisch en vernieuwt tokens op de achtergrond via het opgeslagen refresh token.

**Technische details:** de Go proxy bindt op poort 9002, herschrijft `appie://login-exit` redirects naar `/callback`, wisselt de OAuth-code in voor tokens en slaat ze op in `/tmp/appie-tokens.json`. Flask leest ze via `GET /api/ah/poll-token`.

## Overige functies

- **Foto-import** — foto van een kookboek, Gemini leest het recept inclusief ingrediëntenlijst
- **Portieberekening** — pas het aantal personen aan, hoeveelheden worden herberekend
- **Ingrediënt-normalisatie** — aliassysteem dedupliceert op spelling, meervoud en hoofdletters
- **3 weekmenu-weergaven** — rasterkaart, coverflow, lijstweergave
