# Weekmenu Planner

Een web-applicatie om je weekmenu te plannen en automatisch boodschappenlijsten te genereren.

## Functionaliteiten

### 📋 Recepten
- Beheer recepten met ingrediënten en aantal personen
- **Automatisch importeren van online recepten via URL** — scrape titel, afbeelding, ingrediënten, bereidingswijze
- **Autocomplete voor ingrediënten** — zoek bestaande ingrediënten terwijl je typt
- **Bereiding-veld per recept** — "gesnipperd", "in ringen", apart van de ingrediëntnaam
- Ingrediënt-normalisatie: dedup op spelling, meervoud, case-variaties via alias-systeem
- Koppelingen met kookboeken en paginanummers
- Afbeelding upload voor recepten en kookboeken
- Favorieten, recent gebruikt en populaire recepten

### 📅 Weekmenu & Planning
- Plan weekmenu's voor ontbijt, lunch en diner
- **3 weergaven**: rasterkaart, coverflow (flip-through), en lijstweergave
- **Detail-panel**: volledige receptinfo, ingrediënten-checklist, afbeelding
- Portie aanpassing op basis van aantal personen per maaltijd (automatische herberekening)
- Keyboard-navigatie: pijltjes of klik om recepten te bladeren

### 🛒 Boodschappenlijst
- **Automatisch gegenereerde boodschappenlijst per productgroep**
- Aggregatie op ingredient_id + eenheid (geen dubbele regels meer)
- **AH-productkoppeling**: zoeken en koppelen van Albert Heijn producten
- Kleurgecodeerde productblokken (per merk/verpakking)
- Hoeveelheid-controls (−/+/🗑) met persistentie
- Vink items af (strikethrough)
- Wissen en versturen naar AH

### 🔗 Albert Heijn Integratie
- **Productkoppeling**: zoek AH-producten en koppel ze aan ingrediënten
- **Boodschappenlijst → AH-app**: verstuur gegenereerde lijst rechtstreeks naar je AH-winkelkarretje (OAuth via reverse proxy)
- Bonus-aanduidingen en actuele prijzen
- AH-categorie grouping (Vers, Pantry, Drank, etc.)

### 📚 Kookboeken
- Beheer kookboeken met afbeelding
- Sorteren en filteren op kookboek
- Recepten verplaatsen tussen kookboeken
- Archiveren/terugzetten van kookboeken

### 💾 Import/Export
- **Import**: recepten vanuit URL, JSON-bestanden
- **Export**: alle recepten als JSON
- Bewaar bakups van je receptenverzameling

### 🎨 UI/UX
- **Ink & Paper kleurpalet**: warm grijs/bruin/beige design
- **Tailwind CSS v3** met arbitrary value support
- Responsive design (mobile-first)
- Dark mode-compatibel

## Vereisten

- Docker
- Docker Compose

## Installatie
```bash

git clone https://github.com/beninhos/weekmenu-docker.git
cd weekmenu-docker
mkdir -p static/uploads data
chmod 755 static/uploads 
cmod 755 data
docker-compose up --build
# → http://localhost:5001
```

## Albert Heijn koppeling

De app kan boodschappenlijsten rechtstreeks naar de AH-app sturen via de officieuze AH mobiele API.

### Hoe werkt het

AH gebruikt een invisible hCaptcha op hun loginpagina die alleen voor `localhost` (en `login.ah.nl` zelf) geldig is. Om dit te omzeilen draait er een kleine Go reverse proxy ([gebaseerd op appie-go](https://github.com/gwillem/appie-go)) in de Docker-container die de AH loginpagina doorstuurt op poort 9002. Via een SSH-tunnel ziet je browser de pagina als `localhost:9002` — waardoor hCaptcha gewoon werkt.

### Koppelen

1. Open een SSH-tunnel op je eigen computer:
   ```bash
   ssh -L 9002:localhost:9002 user@server
   ```
2. Ga naar **Instellingen** in de app en klik **"Start AH-koppelaar"**
3. Open `http://localhost:9002` in je browser en log in met je AH-account
4. De app detecteert de koppeling automatisch — de instellingenpagina toont daarna **✓ Verbonden**

### Technische details

- Go proxy: [ah-proxy/main.go](ah-proxy/main.go) — bindt op `0.0.0.0:9002`, herschrijft `appie://login-exit` redirects naar `/callback`, wisselt de OAuth-code in voor tokens en slaat ze op in `/tmp/appie-tokens.json`
- Flask leest de tokens via `GET /api/ah/poll-token` en slaat ze op in de lokale SQLite-database
- Token auto-refresh: verlopen access tokens worden automatisch ververst via het opgeslagen refresh token
- Dank aan [gwillem/appie-go](https://github.com/gwillem/appie-go) voor de reverse proxy aanpak

