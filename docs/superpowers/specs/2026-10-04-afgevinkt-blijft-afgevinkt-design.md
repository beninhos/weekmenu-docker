# Afgevinkt blijft afgevinkt: toevoegen zet alleen het nieuwe op de lijst

**Datum:** 2026-10-04
**Status:** gedrag goedgekeurd door Rutger in de sessie van 4 okt 2026; spec ter review
**Vervangt:** de regel "opnieuw toevoegen zet alles terug" (`zet_terug_op_de_lijst`,
commits 97a7f39, 81db2c9, 91d6011, ce531e8)

## Probleem

Een vinkje en een ✕ onthouden nu alleen "dit ingrediënt, deze week: klaar". Komt
er die week iets bij dat hetzelfde ingrediënt gebruikt, dan moet de app kiezen
tussen alles dicht laten (het nieuwe valt weg) of alles openen (het oude komt
terug). Sinds 13 sep (plannen) en 22 sep (toevoegen op de lijst) opent hij
alles. Gemeten in week 40 op een kopie van de live-database met 0.8.0-beta:
dinsdag chili voor 2 gekocht, gehakt/tomatenpuree/rode peper weggehaald; daarna
+ Recept chili voor 12. De lijst gaf 7 blik kidneybonen in plaats van 6 en
1600 g gehakt in plaats van 1200 g: het al gekochte en het bewust weggehaalde
kwamen terug, inclusief 200 g gehakt van een ander recept die week.

Rutger, 4 okt: "Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik iets
opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan." Voor ✕
koos hij hetzelfde: weg is weg.

## Gedrag

| Wat je doet | Wat er gebeurt |
|---|---|
| Afvinken, ✕, alles afvinken, naar de AH sturen | Weg van de lijst, zoals nu. Blijft weg, ook als er later iets bijkomt. |
| Iets toevoegen: plannen, + Recept, + Los item, personen erbij, recept bewerken | Alleen de extra hoeveelheid komt op de lijst. |
| Personen eraf, recept uit het weekmenu | Er verschijnt niets; wat al afgevinkt is blijft afgevinkt. |
| Een recept toevoegen dat die week al als los recept op de lijst staat (via het weekmenu, de receptenplanner of + Recept) | De app vraagt: "Is dit dezelfde maaltijd?" Ja: één keer op de lijst (weekmenu neemt het losse recept over; bij + Recept wordt het aantal personen aangepast). Nee: komt erbij. |
| Per ongeluk afgevinkt of weggehaald | Onderin bij "Afgevinkt" staat de regel, met "weggehaald" of "via AH" erbij. Eén tik zet hem terug. |

Het controlegebaar van 13/20 sep (regel wegklikken en het recept opnieuw
toevoegen om te zien wat er nodig is) vervalt; Rutger koos daar bewust voor.

## Rekenregel

Per week, per ingrediënt, per eenheid:

    open = nodig − afgevinkt − weggehaald      (nooit onder nul)

- **nodig**: wat de geplande recepten, losse recepten en losse items die week
  vragen, na voorraadfilter en eenheidsomrekening — de huidige
  `_build_shopping_dict`, maar zonder de uitsluitfilter.
- **afgevinkt** en **weggehaald**: de hoeveelheid die open stond op het moment
  van afvinken of wegklikken. Een vinkje legt een getal vast, geen status.

Toevoegen raakt afgevinkt en weggehaald niet aan; het maakt alleen "nodig"
groter. Daarmee vervalt `zet_terug_op_de_lijst` op vier van de vijf plekken
(zie Uitzondering).

## Datamodel (migratie v23, additief)

- `shopping_check.hoeveelheden` en `shopping_list_exclusion.hoeveelheden`:
  JSON-tekst `{"<eenheid>": hoeveelheid}`, met dezelfde eenheidssleutels als de
  uitvoer van `_build_shopping_dict`. De unieke sleutel (jaar, week,
  ingrediënt) blijft.
- `shopping_list_exclusion.weggehaald_op` (datetime), zodat weggehaalde regels
  net als afgevinkte 14 dagen in het afgevinkt-blok staan.
- **Vullen bij de migratie:** elke bestaande rij krijgt wat er op dat moment
  nodig is voor dat ingrediënt in die week. Voor uitsluitingen alleen het
  receptdeel, niet de losse items: die werden ook nu nooit door een ✕
  verborgen (BUG 4 FIX). Gevolg: de lijst ziet er na de migratie precies zo uit
  als ervoor. Dat wordt gemeten op een kopie van de live-database.

## Gebaren, per plek in de code

- **Afvinken** (`_set_checks`, ook voor alles afvinken en naar de AH sturen):
  per week van het ingrediënt `afgevinkt += open`, voor alle eenheden, zoals
  nu. `checked_at` wordt nu. De aantal-override (`ShoppingListOverride`) van die
  week vervalt: die hoorde bij wat nu gekocht is. Het bestel-log krijgt, zoals
  nu, de open hoeveelheid.
- **✕ weghalen** (`boodschappen_remove`, `exclude_shopping_item`):
  `weggehaald += open`, `weggehaald_op` wordt nu. Losse items worden niet
  meer verwijderd; het getal dekt ze. Een later toegevoegd los item komt dan
  gewoon bovenop.
- **Terugzetten** (afgevinkt-blok): afgevinkt resp. weggehaald voor dat
  ingrediënt naar nul, voor precies de week-rijen waarvan het blok de
  hoeveelheid toont (de laatste 14 dagen). Oudere weken blijven dicht.
- **Plannen met uitgevinkte ingrediënten** (`plan_recipe`, "heb ik al"):
  `weggehaald += de hoeveelheid van dít recept`, niet meer de hele week.
- **Plannen, + Recept, + Los item, week opslaan** (`plan_recipe`,
  `update_week_menu`, `boodschappen_extra_add`, `add_shopping_item`): alleen de
  bron toevoegen; geen terugzet meer. `update_week_menu` houdt alleen het bijhouden
  van usage_count/last_used.
- **"Zelfde maaltijd?"**: het weekmenu en de receptenplanner krijgen de losse
  recepten van die week in hun paginadata. Kies je een recept dat erbij staat,
  dan verschijnt een klein venster met twee knoppen ("Ja, zelfde maaltijd" /
  "Nee, komt erbij"), geen `confirm()`. Bij ja stuurt de client
  `neem_los_recept_over: [id]` mee met `/update_menu` of `/api/planner/plan`,
  en de server verwijdert dat QuickAddItem in dezelfde transactie. Het aantal
  personen van het weekmenu geldt. Bij + Recept vraagt `addExtra()` hetzelfde;
  ja = personen aanpassen (huidig gedrag), nee = de client stuurt `erbij: true`
  mee en de server maakt een tweede QuickAddItem. Staat het recept die week al
  in het weekmenu (niet als los recept), dan vraagt + Recept niets en komt het
  erbij: dat was de echte chili-week (dinsdag gepland, extra set via + Recept).
- **Recept bewerken** (`routes/recipes.py`) en **uit de voorraad halen**
  (`services/pantry.py`) blijven via `stem_af_op_de_week` lopen:
  - lopende week: bewerken doet niets extra (de groei verschijnt vanzelf);
  - afgeronde week: `houd_de_week_afgerond` vult afgevinkt aan tot wat nodig
    is, zodat er niets uit augustus opduikt.
- **Varianten samenvoegen** (`_wis_weekbesluiten`): ✕ en aantal-overrides van
  de verliezer vervallen, zoals nu. Vinkjes zijn een feit ("ligt al in de
  kar") en worden per eenheid opgeteld bij die van de winnaar. Dat vervangt de
  drie gevallen in de huidige docstring.
- **Week wissen / lijst wissen**: ongewijzigd.

### Uitzondering: uit de voorraad halen

"Ik heb het toch niet in huis" zegt iets over nu, en spreekt een oud vinkje
van vóór de voorraad tegen. In een lopende week blijft dit gebaar afgevinkt en
weggehaald voor dat ingrediënt wissen (het enige resterende gebruik van
`zet_terug_op_de_lijst`). In een afgeronde week vult het aan, zoals hierboven.

## Weergave op /boodschappen

- Een open regel toont alleen het open deel: 6 blik, niet 7. De recepthint
  noemt de recepten uit de weken waarin nog iets open staat.
- Het afgevinkt-blok toont per ingrediënt wat er de laatste 14 dagen is
  afgevinkt of weggehaald, met de hoeveelheid van dat moment. Nu telt het
  blok de hoeveelheden van alle weken ooit op (kidneybonen: 1 + 1 + 7 = 9
  blik, uit week 13, 33 en 40); dat verdwijnt hiermee.
- Weggehaalde regels staan erbij met het label "weggehaald" en een
  terugzet-knop; afgevinkte houden hun vinkje-checkbox.
- `lopende_weken()`: een week loopt als hij niet achter ons ligt, of als er
  iets open > 0 is (was: een ingrediënt zonder vinkje).

## Randgevallen (bewust zo)

- **Afgevinkt telt als "in huis".** Haal je een recept uit het weekmenu nadat
  je ervoor gekocht hebt, dan blijft het vinkje staan. Voeg je daarna iets toe
  met hetzelfde ingrediënt, dan gaat het al gekochte er eerst vanaf.
  Voorbeeld: chili voor 12 gekocht (6 blik), los recept weer weggehaald, later
  opnieuw chili voor 12: 0 blik open. Je hebt ze in huis.
- **Weggehaald werkt hetzelfde.** "Gehakt had ik al" blijft gelden als het
  recept waarvoor je het wegklikte verdwijnt.
- **Eenheid veranderd.** Komt een opgeslagen eenheid niet meer voor (andere
  voorkeurseenheid, conversie aangepast), dan rekent de app om via dezelfde
  conversietabel als de lijst. Lukt dat niet, dan telt het vinkje voor de hele
  week van dat ingrediënt (dicht) en schrijft de app een logregel. Liever een
  regel te weinig in beeld dan iets kopen wat al in de kar lag.

## Tests

De tests die het oude terugzetgedrag vastleggen (`tests/test_opnieuw_plannen.py`
en de toevoeg-tests van 22 sep) worden herschreven naar de nieuwe regel. Nieuw,
in Nederlandse gedragsnamen:

- chili-week: chili 2 afgevinkt + gehakt weggehaald, dan + Recept chili 12 →
  6 blik kidneybonen, 1200 g gehakt;
- personen 2→4 op een afgevinkt recept → alleen 2 personen open; 4→2 → niets open;
- ✕ en daarna een los item van hetzelfde ingrediënt → alleen het losse item open;
- terugzetten na ✕ en na afvinken;
- plannen met uitgevinkt ingrediënt → alleen dat recept-deel weggehaald;
- "zelfde maaltijd?" ja/nee, via weekmenu, receptenplanner en + Recept;
- afvinken laat de aantal-override van die week vervallen;
- recept bewerken in een lopende en in een afgeronde week;
- uit de voorraad halen (uitzondering);
- samenvoegen: vinkjes opgeteld, ✕ van de verliezer weg;
- migratie v23: open lijst identiek voor en na, op een fixture met vinkjes,
  uitsluitingen en losse items;
- afgevinkt-blok telt alleen de laatste 14 dagen.

Plus: het chili-scenario (`repro_chili.py`) op een kopie van de live-database
moet 6 blik geven, en de volledige suite blijft groen.

## Uitrol

1. Bouwen op branch `afgevinkt-blijft-afgevinkt` (dev-werkmap), test-first.
2. Dev-container herbouwen, scenario doorklikken op dev, ook op 390 px.
3. Migratie v23 meten op een kopie van de live-database: open lijst voor en na
   gelijk, afgevinkt-blok alleen nog 14 dagen.
4. Versie 0.9.0-beta (gedragswijziging + schema).
5. Live pas na Rutgers akkoord, met back-up vooraf; daarna versie, schema,
   logs en `/boodschappen` op live controleren.

## Niet in scope

- Vinkjes per maaltijd (aanpak B): afgewogen en niet gekozen.
- Het bestel-log terugkoppelen naar de lijst ("wat de AH niet had").
- De andere openstaande punten uit CLAUDE.md.
