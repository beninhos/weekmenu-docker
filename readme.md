# Weekmenu Planner

Een web-applicatie om je weekmenu te plannen en automatisch boodschappenlijsten te genereren.

## Functionaliteiten

- Beheer recepten met ingrediënten en aantal personen
- Plan weekmenu's voor ontbijt, lunch en diner
- Portie aanpassing op basis van aantal personen per maaltijd (automatische herberekening)
- Automatisch gegenereerde boodschappenlijst op productgroep
- Autocomplete voor recepten (zoek terwijl je typt)
- Koppelingen met kookboeken en paginanummers
- Kookboek afkortingen (voor snelle toegang)
- Favorieten, recent gebruikt en populaire recepten
- Afbeelding upload voor recepten en kookboeken

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

