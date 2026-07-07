# Recepten-dump: batch-import vanaf kookboekfoto's en PDF

**Datum:** 2026-07-05
**Status:** goedgekeurd door Rutger

## Probleem

Recepten toevoegen vanaf een kookboek kost nu te veel klikken: per recept naar
"nieuw recept", max 3 foto's kiezen, wachten, formulier doorlopen. Geen
PDF-support (tinyscanner levert multi-page PDF's), geen batch. Doel: één
"dump"-moment (stapel foto's of PDF), de app splitst zelf in recepten, review
achteraf via een wachtrij.

## Scope

- Nieuwe pagina `/dump`, gebouwd en getest op de dev-omgeving
  (`docker-compose.dev.yml`, poort 5002, `weekmenu_dev.db`). Geen link vanaf de
  receptenpagina tot de feature bevalt; promotie naar prod is een aparte stap.
- PWA share-target zodat foto's delen vanaf de telefoon direct een dump start.
- De bestaande foto-import op `new_recipe` blijft ongewijzigd bestaan.

## Datamodel

Twee nieuwe tabellen (via het bestaande migratiemechanisme in
`weekmenu/migrations.py`):

- **`DumpJob`**: `id` (uuid-string, PK), `status`
  (`processing` | `done` | `error`), `error_message` (text, nullable),
  `created_at` (datetime).
- **`RecipeDraft`**: `id` (int PK), `job_id` (FK → DumpJob), `name`, `serves`
  (nullable int), `instructions` (text), `ingredients_json` (text: de ruwe
  Gemini-ingrediëntenlijst, nog niet gematcht), `image_path` (nullable),
  `source_page` (nullable int/omschrijving van de bronpagina), `status`
  (`pending` | `accepted` | `rejected`), `created_at`.

Drafts staan buiten de echte receptenlijst: planner, boodschappenlijst en
zoekfuncties zien ze niet tot acceptatie.

## Backend

Nieuwe blueprint/route-module `weekmenu/routes/dump.py`, extractielogica in
`weekmenu/services/dump.py` (hergebruikt helpers uit `services/gemini.py`).

- **`POST /dump/upload`** — accepteert meerdere foto's en/of één PDF
  (multipart). Bestanden gaan naar `static/uploads/dump/<job_id>/`. Maakt een
  `DumpJob` aan, start een achtergrondthread en retourneert direct
  `{job_id}`.
- **Verwerkingsthread** — één Gemini-call (`gemini-2.5-flash`): PDF gaat als
  `application/pdf`-part rechtstreeks mee, foto's als image-parts. Prompt is
  een uitbreiding van `_GEMINI_RECIPE_PROMPT`: er kunnen meerdere recepten in
  de invoer zitten; antwoord is een JSON-array van recepten, per recept ook
  `photo_page`: welke pagina/foto het gerecht toont (of null).
- **Receptafbeelding** — bij foto-invoer: de aangewezen foto wordt gekopieerd
  naar `static/uploads/` (md5-naam, zoals bestaande foto-import). Bij PDF:
  alleen de aangewezen pagina wordt met **pypdfium2** (nieuwe dependency in
  `requirements.txt`) naar JPG gerenderd. Faalt renderen, dan geen afbeelding
  — nooit een job-fout.
- **`GET /dump/status/<job_id>`** — jobstatus + drafts (voor polling).
- **`POST /dump/draft/<id>/accept`** — maakt een echt `Recipe` +
  `RecipeIngredient`s. Ingrediëntmatching identiek aan de bestaande
  foto-import-submit: match op naam/alias, onbekende ingrediënten worden
  aangemaakt. Body bevat `cookbook_id` (batch-brede keuze uit de UI).
- **`POST /dump/draft/<id>/reject`** — zet status op `rejected`.
- **`GET /dump/draft/<id>/edit`** — redirect naar het bestaande
  receptformulier, voorgevuld met de draftgegevens (zelfde prefill-mechanisme
  als de huidige foto-import); na opslaan wordt de draft `accepted`.

## UI (`/dump`, template `dump.html`)

- Bovenaan een dropzone: drag & drop op pc, "kies foto's/PDF"-knop op
  telefoon (`<input type="file" multiple accept="image/*,application/pdf">`).
- Tijdens verwerking: dansende banaan + statustekst, polling op de
  status-endpoint.
- Daarna per draft een kaart: afbeelding, naam, personen, ingrediëntenlijst,
  acties **✓ Opslaan**, **✎ Aanpassen**, **✗ Weg**.
- Eén kookboek-select bovenaan geldt voor alle accepts in de sessie
  (default: laatst gebruikte kookboek).
- Onafgehandelde `pending`-drafts van eerdere jobs blijven op de pagina staan:
  dumpen en dagen later reviewen kan.

## PWA share-target

`share_target`-blok in `static/manifest.json`:

```json
"share_target": {
  "action": "/dump/share",
  "method": "POST",
  "enctype": "multipart/form-data",
  "params": { "files": [{ "name": "files", "accept": ["image/*", "application/pdf"] }] }
}
```

`POST /dump/share` start een job met de gedeelde bestanden en redirect naar
`/dump`. Werkt op Android met geïnstalleerde PWA; elders verandert er niets.

## Foutafhandeling

- Gemini-fout, timeout of onparsebare JSON → job `error` met melding in de
  UI; bronbestanden blijven staan; "opnieuw proberen"-knop start een nieuwe
  verwerking op dezelfde bestanden.
- Recepten die individueel niet te parsen zijn worden overgeslagen; de rest
  van de batch komt gewoon door.
- Geen bestanden of alleen niet-ondersteunde types → directe 400 met melding.

## Testen

Op dev (poort 5002): een echte tinyscanner-PDF met meerdere recepten, en een
setje losse telefoonfoto's. Controle: correcte splitsing, ingrediëntmatching
bij accept, afbeeldingkeuze, foutpad (bewust kapotte invoer), share-target
vanaf Android.

## Buiten scope (later)

- Knop op de receptenpagina + promotie naar prod.
- Foto bijsnijden/opschonen met Gemini's image-model.
- Watch-map op de server.
