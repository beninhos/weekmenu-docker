# Eén boodschappenlijst + slimmere weeknavigatie

**Datum:** 2026-07-07
**Status:** goedgekeurd door Rutger

## Probleem

1. De boodschappenlijst is per week (`/shopping-list/<jaar>/<week>`). Rutger
   plant op zaterdag voor de volgende week en moet daarna handmatig de lijst
   leegmaken na het doorzetten naar AH. Hij wil één doorlopende lijst waarop
   híj items afvinkt ("af = afgevinkt door mij"); versturen naar AH vinkt ze
   alvast af.
2. De app opent altijd op de huidige ISO-week; op zaterdag is dat de
   verkeerde. De weeknavigatie valt bovendien niet op.

Expliciet besloten: géén weeklabels in de lijst-UI (boodschappen doen is één
platte lijst) en géén aparte "planlijst"-feature.

## Deel A — Eén boodschappenlijst

### Model

Nieuwe tabel **`ShoppingCheck`** (via migratie v8, idempotent patroon):
`id`, `year`, `week_number`, `ingredient_id` (FK), `checked_at` (datetime),
`via_ah` (bool, default False), unique op (`year`, `week_number`,
`ingredient_id`). Een rij = "dit ingrediënt is voor die week afgevinkt".

De lijst zelf blijft **afgeleid** uit de weekmenu's (bestaande
`_build_shopping_dict(year, week)` + overrides/exclusions per week blijven
ongewijzigd): menu wijzigen = lijst klopt direct.

### Aggregatie

Nieuwe servicefunctie `build_combined_shopping_list()` in
`weekmenu/services/shopping.py`:
- **Venster:** de ISO-weken van (vandaag − 7 dagen) t/m (vandaag + 14 dagen)
  — in de praktijk vorige, huidige en de twee komende weken.
- Per week het bestaande per-week-resultaat opbouwen; daarna per
  (`ingredient_id`, genormaliseerde eenheid) optellen over de weken tot één
  regel. Elke regel onthoudt intern zijn bijdragende (year, week)-paren.
- Een regel is **afgevinkt** als álle bijdragende weken een
  `ShoppingCheck`-rij hebben; anders open (de open hoeveelheid = som van de
  niet-afgevinkte weken).
- Sortering en groepering per categorie zoals de bestaande per-week-lijst
  (`CATEGORY_ORDER_SUPERMARKET`).

### Pagina en API

- **`GET /boodschappen`** — dé lijstpagina, nieuw template
  `boodschappen.html` (opgezet naar het model van `shopping_list.html`;
  het oude template blijft ongewijzigd bestaan voor de redirect-periode).
  Geen weeknummer in URL of UI. Open items bovenaan
  gegroepeerd per categorie; onderaan een inklapbaar blok **"Afgevinkt (n)"**
  met doorgestreepte items en een "via AH"-badge waar van toepassing.
  Afgevinkte items met `checked_at` ouder dan **14 dagen** worden niet meer
  getoond (query-filter; rijen blijven bestaan).
- **`POST /api/boodschappen/item/<ingredient_id>/check`** body
  `{checked: true|false}` — zet/verwijdert `ShoppingCheck`-rijen voor álle
  bijdragende weken van die regel (server berekent die zelf opnieuw).
- **Hoeveelheid aanpassen en uitsluiten**: hergebruik van de bestaande
  per-week-endpoints; de UI stuurt ze naar de **laatste (hoogste)
  bijdragende week** van de regel. Uitsluiten (✗) stuurt de exclusion naar
  álle bijdragende weken.
- **Handmatig item toevoegen**: bestaand `add-item`-mechanisme, gekoppeld
  aan de huidige ISO-week; blijft op de lijst tot afgevinkt (ook als de week
  uit het venster loopt: regels met een override maar zonder check blijven
  meetellen zolang hun week ≤ 4 weken oud is — feestje-boodschappen blijven
  dus staan).
- **Verstuur naar AH**: knop toont het aantal openstaande items en verstuurt
  alléén die (bestaand `send_to_ah`-mechanisme incl. order-mode-detectie,
  gevoed met de gecombineerde open items i.p.v. één week). Na succes worden
  alle verzonden regels afgevinkt met `via_ah=True`.
- **Oude URL's**: `/shopping-list/<jaar>/<week>` → 301 naar `/boodschappen`.
  De bijbehorende per-week-API-endpoints blijven bestaan (de nieuwe UI
  gebruikt ze). Navigatie in `base.html` wijst naar `/boodschappen`.

## Deel B — Weeknavigatie

- **Weekbalk** bovenaan `week_menu.html`: grote vorige/volgende-pijlen,
  gecentreerd "Week N" met datumbereik ("ma 13 – zo 19 juli"). Als de
  getoonde week ≠ huidige ISO-week: gele indicator "Je kijkt naar
  volgende/vorige week" + knop "Naar deze week".
- **Laatst bekeken week onthouden**: `week_menu` zet een cookie
  `last_viewed_week` (`<year>-<week>`, max-age 14 dagen). De homepage
  (`weekmenu/routes/main.py`) leest die cookie en redirect daarheen; bij
  ontbrekende/ongeldige cookie → huidige week zoals nu.

## Foutafhandeling

- Check-endpoint op onbekend ingrediënt/regel buiten venster → 404.
- AH-verzendfouten: bestaand gedrag (foutmelding, niets afvinken bij
  mislukking; bij gedeeltelijk succes alleen de gelukte items afvinken —
  volg wat `send_to_ah` per item rapporteert).
- Cookie met week buiten bereik (bv. week 60) → negeren, huidige week.

## Testen

Unit-tests (pytest, bestaande suite):
- Aggregatie: zelfde ingrediënt in twee weken → één regel met som; check in
  één week → regel open met restant; check in alle weken → regel afgevinkt.
- Check-endpoint: zet rijen voor alle bijdragende weken; uncheck verwijdert.
- 14-dagen-filter op afgevinkte items.
- AH-flow: na (gesimuleerd) succes zijn verzonden items `via_ah=True`.
- Redirect oude URL en cookie-gedrag homepage (geldig, afwezig, ongeldig).

Handmatig op dev: plannen in week N+1 op "zaterdag", lijst toont alles
samengevoegd, afvinken, versturen, weekbalk-indicator.

## Buiten scope

- Aparte planlijst voor verre toekomst (bewust niet — handmatig item blijft
  gewoon staan tot afgevinkt).
- Weeklabels of week-filters in de lijst-UI.
- Wijzigingen aan de AH-order-bewerkpagina.
