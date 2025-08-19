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
### Vereisten
- Docker
- Docker Compose

git clone https://github.com/beninhos/weekmenu-docker.git
cd weekmenu-docker
mkdir -p static/uploads data
chmod 755 static/uploads 
cmod 755 data
docker-compose up --build
# → http://localhost:5001

