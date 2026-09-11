# Weekmenu Planner

Weekmenu plannen, recepten beheren en de boodschappenlijst rechtstreeks naar je AH-app sturen. Draait als Docker-container.

## Wat het doet

Maaltijden plannen per dag (ontbijt, lunch, diner), recepten beheren met ingrediënten en kookboeken, en een gesorteerde boodschappenlijst genereren. Ingrediënten worden samengevoegd op basis van een aliassysteem dat spellingsvarianten, meervouden en hoofdletterverschillen samenvoegt.

Recepten importeer je via URL (scraping, met Gemini 2.5 Flash als fallback), of je leest ze in vanaf foto's of een PDF van kookboekpagina's en receptkaarten.

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

Stel onder **Instellingen** twee API-sleutels in:

- **Cloud Vision** leest de tekst van gescande pagina's. Maak de sleutel aan in de Google Cloud Console en zet de Cloud Vision API aan. Vision vraagt een gekoppelde betaalmethode; de eerste 1.000 pagina's per maand zijn gratis.
- **Gemini** maakt van die tekst een recept, en is de fallback bij URL-import. Een sleutel maak je gratis aan via Google AI Studio.

## Recepten inlezen

Via **Recepten → Foto-dump** lees je een hele stapel in één keer in. Kies eerst de soort scan:

- **Kookboekpagina's** — één pagina per recept
- **Receptkaarten** — voor- en achterkant samen vormen één recept

Cloud Vision leest de tekst, Gemini maakt er een recept van. De bereiding wordt letterlijk uit de gelezen tekst geknipt, niet door het model herschreven; kopjes als "1. Pasta koken" komen op een eigen regel boven hun stap. Bij receptkaarten is de ingrediëntentabel leidend, en neemt de app ook de bereidingstijd en de "zelf toevoegen"-ingrediënten over.

Elk recept verschijnt eerst als nakijkkaart. Daar zie je:

- regels waar Vision twijfelde aan een getal (vaak een ½ die als cijfer gelezen is), gemarkeerd naast de foto
- wat er bij dit recept nog na te kijken valt, zoals een zin na de laatste stap die niet is overgenomen
- de foto, die je kunt bijsnijden en draaien; het origineel en bij een kaart de achterkant zijn erbij te openen

Via **Aanpassen** open je het recept in het formulier voordat je het opslaat.

## Albert Heijn koppeling

Stuur je boodschappenlijst rechtstreeks naar je AH-winkelwagentje.

1. Open een SSH-tunnel: `ssh -L 9002:localhost:9002 user@server`
2. Ga naar **Instellingen** → **Start AH-koppelaar**
3. Open `http://localhost:9002` en log in met je AH-account

Soms moet je twee keer achter elkaar inloggen: de eerste poging bouwt de sessie-trust op, de tweede lukt. De koppeling wordt automatisch opgepikt; tokens vernieuwen op de achtergrond.

Op **AH producten** koppel je ingrediënten aan een product. Staat een recept in stuks terwijl het product per gewicht verkocht wordt (tien tomaatjes tegen een bakje van 380 g), dan stelt de app voor wat één stuk weegt, met de bron erbij. Pas na jouw bevestiging telt het mee, zodat de lijst geen tien bakjes meer bestelt.

De AH-login is mogelijk dankzij het werk van [appie-go](https://github.com/gwillem/appie-go) van **gwillem**.

## Testomgeving

Een dev-versie naast de live versie:

```bash
docker compose -f docker-compose.dev.yml -p weekmenu-dev up -d --build
# → http://localhost:5002
```

Eigen database, te koppelen met een apart AH-account — testen zonder de live versie te raken.

## Overige functies

- **Portieberekening** — pas het aantal personen aan, hoeveelheden worden herberekend
- **Ingrediënt-normalisatie** — aliassysteem dedupliceert op spelling, meervoud en hoofdletters
- **Varianten samenvoegen** — onder **Voorraad → Twijfelgevallen nakijken** stelt de app namen voor die hetzelfde product zijn, zoals knoflook en knoflookteen. Jij kiest welke naam blijft; de kaart laat vooraf zien wat er verandert
- **Voorraad** — wat je altijd in huis hebt, komt niet op de boodschappenlijst
- **3 weekmenu-weergaven** — rasterkaart, coverflow, lijstweergave

## Ontwikkelen

```bash
python3 -m pytest -q
```

De service worker (`static/sw.js`) serveert alles onder `/static/` uit de cache zonder te controleren of er een nieuwere versie is. Verhoog bij elke wijziging aan JavaScript of CSS de `CACHE`-naam in dat bestand, anders blijven browsers de oude versie gebruiken. Na een update is een harde verversing (Ctrl+Shift+R) nodig.
