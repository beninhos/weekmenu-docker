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

Stuur je boodschappenlijst rechtstreeks naar je AH-winkelwagentje.

1. Open een SSH-tunnel: `ssh -L 9002:localhost:9002 user@server`
2. Ga naar **Instellingen** → **Start AH-koppelaar**
3. Open `http://localhost:9002` en log in met je AH-account

Soms moet je twee keer achter elkaar inloggen: de eerste poging bouwt de sessie-trust op, de tweede lukt. De koppeling wordt automatisch opgepikt; tokens vernieuwen op de achtergrond.

## Testomgeving

Een dev-versie naast de live versie:

```bash
docker compose -f docker-compose.dev.yml -p weekmenu-dev up -d --build
# → http://localhost:5002
```

Eigen database, te koppelen met een apart AH-account — testen zonder de live versie te raken.

## Overige functies

- **Foto-import** — foto van een kookboek, Gemini leest het recept inclusief ingrediëntenlijst
- **Portieberekening** — pas het aantal personen aan, hoeveelheden worden herberekend
- **Ingrediënt-normalisatie** — aliassysteem dedupliceert op spelling, meervoud en hoofdletters
- **3 weekmenu-weergaven** — rasterkaart, coverflow, lijstweergave
