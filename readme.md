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

AH beschermt de login met een WAF (Akamai bot-protectie) én hCaptcha. Een ingebouwde reverse proxy ([gebaseerd op appie-go](https://github.com/gwillem/appie-go)) serveert de AH-loginpagina op poort 9002. De proxy gebruikt **curl_cffi met een Chrome-fingerprint** zodat de WAF de verzoeken niet blokkeert (een gewone Go/Python-client krijgt anders `403 Access Denied`). Via een SSH-tunnel logt je eigen browser in op de geproxiede pagina.

1. Open een SSH-tunnel vanaf je eigen computer:
   ```bash
   ssh -L 9002:localhost:9002 user@server
   ```
2. Ga naar **Instellingen** → **Start AH-koppelaar**
3. Open `http://localhost:9002` en log in met je AH-account

> **LET OP:** Als hCaptcha een foutmelding geeft bij het inloggen via de koppelaar, open dan eerst een regulier tabblad in de browser, ga naar de officiële Albert Heijn website (ah.nl) en log daar handmatig in. Dit bouwt de benodigde sessie-trust op. Ga daarna pas terug naar de HTTPS-proxy/koppelaar om de koppeling succesvol af te ronden.

De app detecteert de koppeling automatisch en vernieuwt tokens op de achtergrond via het opgeslagen refresh token (atomic refresh met lock; bij een ongeldig token wordt de status op "niet verbonden" gezet).

**Technische details:** de proxy (`ah-proxy/proxy.py`, Flask + curl_cffi) bindt op poort 9002, herschrijft `appie://login-exit` redirects naar `/callback`, wisselt de OAuth-code in voor tokens en slaat ze op in `/tmp/appie-tokens.json`. Flask leest ze via `GET /api/ah/poll-token`.

## Overige functies

- **Foto-import** — foto van een kookboek, Gemini leest het recept inclusief ingrediëntenlijst
- **Portieberekening** — pas het aantal personen aan, hoeveelheden worden herberekend
- **Ingrediënt-normalisatie** — aliassysteem dedupliceert op spelling, meervoud en hoofdletters
- **3 weekmenu-weergaven** — rasterkaart, coverflow, lijstweergave
