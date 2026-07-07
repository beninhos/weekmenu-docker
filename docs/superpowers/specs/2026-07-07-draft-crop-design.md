# Draft-afbeelding croppen op de /dump-reviewpagina

**Datum:** 2026-07-07
**Status:** goedgekeurd door Rutger
**Bouwt op:** `2026-07-05-recipe-dump-design.md` (recepten-dump, branch `recepten-dump`)

## Probleem

De dump-import kiest per recept een pagina als afbeelding, maar kookboekpagina's
bevatten meestal tekst én foto. Rutger wil na de import op de review-kaart de
afbeelding kunnen bijsnijden zodat alleen de gerechtfoto overblijft.

## Scope

- Alleen op de `/dump`-reviewpagina, alleen op de huidige afbeelding van de
  draft (geen bronpagina-keuze). Kaarten zonder afbeelding krijgen geen
  crop-knop.
- Croppen kan herhaald worden: er wordt altijd vanuit het origineel gesneden.

## Datamodel

Nieuw nullable veld op `RecipeDraft`: `original_image_path`
(String(200)). Wordt bij de **eerste** crop gevuld met de dan geldende
`image_path`; daarna wijzigt het nooit meer. Bestaande tabellen in dev worden
via een idempotente `ALTER TABLE`-migratie in `weekmenu/migrations.py`
bijgewerkt (zelfde patroon als bestaande kolom-migraties; `db.create_all()`
dekt alleen nieuwe installaties).

## Backend

Nieuw endpoint in `weekmenu/routes/dump.py`:

- **`POST /dump/draft/<int:id>/crop`** — JSON-body
  `{x, y, width, height}`: fracties (0–1) t.o.v. het bronbeeld.
  Gedrag:
  1. Bron = `original_image_path` als dat gezet is, anders `image_path`.
     Geen van beide → 400 "Geen afbeelding om bij te snijden".
  2. Valideer: alle vier waarden aanwezig, 0 ≤ x,y < 1, 0 < width,height ≤ 1,
     x+width ≤ 1, y+height ≤ 1; anders 400.
  3. Open het bronbestand met Pillow, crop naar pixelcoördinaten
     (afronden op int, minimaal 1×1 pixel), `convert('RGB')` (PNG/WebP met
     alpha), sla op als JPEG kwaliteit 85 onder `static/uploads/<md5>.jpg`.
     Kan Pillow het bronformaat niet openen (bijv. AVIF zonder plugin) →
     400 "Dit afbeeldingsformaat kan niet bijgesneden worden".
  4. Zet `original_image_path` (indien nog leeg) op de oude `image_path`,
     zet `image_path` op het nieuwe pad, commit.
  5. Response: `{status: 'success', image_path: <nieuw pad>}`.
  - Bronbestand ontbreekt op schijf → 404 met nette melding.

Het origineel blijft altijd staan (zowel het bestand als het pad in
`original_image_path`), dus hercroppen snijdt opnieuw uit de volle pagina.

## Frontend (`templates/dump.html`)

- Cropper.js via CDN (zelfde aanpak als Quill in `new_recipe.html`),
  versie 1.6.x: css + js alleen op deze pagina.
- Op `renderCard()`: bij kaarten met `image_path` een **✂️ Bijsnijden**-knop
  naast ✎ Aanpassen.
- Klik opent een modal (overlay, max ~90vw/80vh) met de bronafbeelding
  (origineel: `original_image_path ?? image_path` — de server bepaalt dit
  zelf; de modal laadt gewoon een aparte `GET /dump/draft/<id>` op voor de
  actuele paden) in een Cropper-instance, vrije verhouding, touch-support.
- "Opslaan" → bereken relatieve coördinaten uit `cropper.getData()` en de
  natuurlijke afmetingen, POST naar `/dump/draft/<id>/crop`, bij succes:
  kaart-afbeelding verversen (cache-buster `?t=Date.now()`), modal dicht.
- "Annuleren"/klik buiten modal → sluiten zonder actie.
- Serialisatie: `serialize_draft` krijgt `original_image_path` erbij zodat de
  modal het origineel kan tonen.

## Foutafhandeling

- Server-fouten (400/404/500) tonen een rode melding in de modal; modal
  blijft open zodat opnieuw geprobeerd kan worden.
- Cropper-load-fout (CDN onbereikbaar): knop toont melding "Bijsnijden niet
  beschikbaar"; de rest van de pagina blijft werken.

## Testen

- Unit-tests op het crop-endpoint: geldige crop (nieuw bestand met verwachte
  pixel-afmetingen, `image_path` bijgewerkt, `original_image_path` gezet),
  tweede crop snijdt weer uit origineel, ongeldige coördinaten → 400,
  draft zonder afbeelding → 400, PNG-bron (met alpha) → geldige JPEG.
- Handmatig op dev (poort 5002): croppen op pc (muis) en telefoon (touch),
  hercroppen, accept van een gecropte draft.

## Addendum (2026-07-07, goedgekeurd): croppen in het receptformulier

Croppen moet óók beschikbaar zijn op de bewerkpagina van een recept
(`edit_recipe.html` toont de afbeelding al):

- `Recipe` krijgt een kolom `original_image_path` (String(200), nullable)
  via migratie v8 (ALTER TABLE, idempotent patroon) — zelfde
  hercrop-vanuit-origineel-semantiek als bij drafts.
- De Pillow-cropkern en coördinaatvalidatie verhuizen uit
  `routes/dump.py` naar een gedeelde service `weekmenu/services/images.py`
  (`parse_crop_body(body)`, `crop_image(src_rel, x, y, w, h)`); het
  draft-endpoint gebruikt die voortaan ook.
- Nieuw endpoint `POST /recipe/<int:id>/crop`, zelfde contract als het
  draft-crop-endpoint (fracties 0–1, `{status, image_path}`).
- De Cropper.js-modal verhuist naar include `templates/_crop_modal.html`
  met generieke JS (`openCropModal(srcUrl, saveUrl, onSaved)`);
  `dump.html` en `edit_recipe.html` gebruiken beide de include. Op
  `edit_recipe.html` staat een ✂️ Bijsnijden-knop bij de afbeelding; na
  opslaan ververst de preview met cache-buster.

## Buiten scope

- Croppen op een andere bronpagina dan de huidige afbeelding.
- Automatisch croppen met Gemini's image-model.
