# Weekmenu Planner

Een web-applicatie om je weekmenu te plannen en automatisch boodschappenlijsten te genereren.

## Functionaliteiten

- Beheer recepten met ingrediënten
- Plan weekmenu's voor ontbijt, lunch en diner
- Automatisch gegenereerde boodschappenlijst
- Sortering van boodschappen op categorie
- Koppelingen met kookboeken en paginanummers

## Vereisten

- Docker
- Docker Compose

## Installatie

1. Clone de repository:
```bash
git clone https://github.com/yourusername/weekmenu-planner.git
cd weekmenu-planner
mkdir -p static/uploads
chmod 755 static/uploads
mkdir data
chmod 755 data
docker-compose up