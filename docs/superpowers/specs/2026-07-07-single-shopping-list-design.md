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

Aanvullend besloten (2026-07-07): de oude quick-add-flow (sessie-items via
URL-parameters, `/quick-add`) wordt **vervangen** door "recept direct op de
lijst" (zie hieronder); Rutgers hoofdflow is "alles naar AH sturen"
(auto-afvinken), handmatig vinken blijft voor uitzonderingen.

## Deel A — Eén boodschappenlijst

### Model

Nieuwe tabel **`ShoppingCheck`** (via migratie v8, idempotent patroon):
`id`, `year`, `week_number`, `ingredient_id` (FK), `checked_at` (datetime),
`via_ah` (bool, default False), unique op (`year`, `week_number`,
`ingredient_id`). Een rij = "dit ingrediënt is voor die week afgevinkt".

Nieuwe tabel **`ShoppingExtra`** (zelfde migratie): `id`, `recipe_id` (FK),
`people_count` (nullable int), `year`, `week_number` (ISO-week van
toevoegen), `created_at`. Een rij = "los recept op de boodschappenlijst,
zonder menuplanning".

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
  niet-afgevinkte weken). De check is per **ingrediënt** (eenheid-
  onafhankelijk): staat één ingrediënt door eenheidsverschil als twee regels
  op de lijst, dan vinken die samen af — bewuste vereenvoudiging.
- Getoonde AH-hoeveelheid (pakketten) per regel = som van de per-week-qty's
  (override waar aanwezig, anders `_calc_ah_qty` per week).
- Handmatige overrides van weken buiten het venster tellen mee zolang hun
  week niet ouder is dan 4 weken en er geen check-rij is (de aggregatie
  scant daarvoor overrides tot 4 weken terug).
- **Losse recepten** (`ShoppingExtra`): hun ingrediënten tellen mee in de
  aggregatie alsof ze in hun (year, week) gepland waren —
  `amount × multiplier` via dezelfde `_calc_multiplier`-logica als het menu.
  Afvinken werkt dus vanzelf (per ingrediënt per week). Zelfde 4-weken-regel
  als handmatige overrides.
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
- **Verstuur naar AH**: knop toont het aantal openstaande items. Nieuw
  endpoint `POST /api/boodschappen/send-to-ah` dat de bestaande
  `send_to_ah`-logica (order-mode-detectie, merge per AH-productId,
  qty_overrides) hergebruikt maar gevoed wordt met de **gecombineerde open
  items** i.p.v. één week — de kern wordt daarvoor uit de route
  gerefactored naar een servicefunctie die een shopping-dict accepteert.
  Let op: de AH-call is één gebundeld request zonder per-item-rapportage;
  daarom geldt: bij succes worden alléén de daadwerkelijk meegestuurde
  (AH-gekoppelde) regels afgevinkt met `via_ah=True`; `not_linked`-items
  blijven open; bij een fout wordt níets afgevinkt.
- **Recept direct op de lijst**: knop "+ Recept" op `/boodschappen` →
  receptzoeker (hergebruik van het bestaande zoek-/pickerpatroon) + aantal
  personen → `POST /api/boodschappen/extra` `{recipe_id, people_count}`.
  Bovenaan de lijst een chips-regel "Losse recepten: <naam> (Np) ✕";
  verwijderen via `DELETE /api/boodschappen/extra/<id>` (haalt de bijdrage
  uit de aggregatie; al gezette checks blijven staan).
- **Alles afvinken**: knop bij de lijst die alle openstaande regels in één
  keer afvinkt (`via_ah=False`) — vervangt Rutgers huidige handmatige
  "alles wissen" na een niet-AH-boodschappenronde.
- **Oude URL's en quick-add**: `/shopping-list/<jaar>/<week>` → 301 naar
  `/boodschappen` (onvoorwaardelijk). `/quick-add` en de bijbehorende
  quick-add-API's/template vervallen: route redirect naar `/boodschappen`,
  template en dode code opruimen. De per-week-API-endpoints voor
  qty/exclude/add-item blijven bestaan (de nieuwe UI gebruikt ze).
  Navigatie in `base.html` wijst naar `/boodschappen`.

## Deel B — Weeknavigatie

- **Weekbalk** bovenaan `week_menu.html`: grote vorige/volgende-pijlen,
  gecentreerd "Week N" met datumbereik ("ma 13 – zo 19 juli"). Als de
  getoonde week ≠ huidige ISO-week: gele indicator "Je kijkt naar
  volgende/vorige week" + knop "Naar deze week".
- **Laatst bekeken week onthouden**: `week_menu` zet een cookie
  `last_viewed_week` (`<iso-jaar>-<week>`, max-age 14 dagen; ISO-jaar uit
  `isocalendar()`, niet het kalenderjaar — die verschillen rond de
  jaarwisseling). De homepage
  (`weekmenu/routes/main.py`) leest die cookie en redirect daarheen; bij
  ontbrekende/ongeldige cookie → huidige week zoals nu.

## Foutafhandeling

- Check-endpoint op onbekend ingrediënt/regel buiten venster → 404.
- AH-verzendfouten: foutmelding tonen, níets afvinken (de AH-call is één
  gebundeld request — er bestaat geen per-item-succes).
- Cookie met week buiten bereik (bv. week 60) → negeren, huidige week.

## Testen

Unit-tests (pytest, bestaande suite):
- Aggregatie: zelfde ingrediënt in twee weken → één regel met som; check in
  één week → regel open met restant; check in alle weken → regel afgevinkt.
- Check-endpoint: zet rijen voor alle bijdragende weken; uncheck verwijdert.
- 14-dagen-filter op afgevinkte items.
- AH-flow: na (gesimuleerd) succes zijn verzonden items `via_ah=True`.
- Losse recepten: extra toevoegen → ingrediënten verschijnen open op de
  lijst; verwijderen → bijdrage weg; alles-afvinken vinkt ook extra-items.
- Redirect oude URL en cookie-gedrag homepage (geldig, afwezig, ongeldig).

Handmatig op dev: plannen in week N+1 op "zaterdag", lijst toont alles
samengevoegd, afvinken, versturen, weekbalk-indicator.

## Buiten scope

- Aparte planlijst voor verre toekomst (bewust niet — handmatig item blijft
  gewoon staan tot afgevinkt).
- Weeklabels of week-filters in de lijst-UI.
- Wijzigingen aan de AH-order-bewerkpagina.
