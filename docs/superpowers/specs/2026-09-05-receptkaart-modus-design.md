# Receptkaart-modus: twee pagina's = één recept, tabel leidend

**Datum:** 2026-09-05
**Status:** ontwerp goedgekeurd op hoofdlijnen door Rutger ("ga verder op eigen inzicht")
**Bouwt op:** `2026-07-05-recipe-dump-design.md` (dump-import), de Cloud
Vision-route en de ankerknip (`services/ankers.py`, commits 650443d–c92cfa2),
en stap 2 + 3 van het vervolgplan (fcd286c, 356d3d3: bereiding op de
nakijkkaart, `check` in het formulier, bredere twijfelfilter).

## Probleem

De import gaat uit van één kookboekpagina per recept. Een maaltijdbox-kaart
(HelloFresh en soortgelijke) is een recept over twee pagina's: de voorkant
heeft titel, gerechtfoto, bereidingstijd en de ingrediëntnamen zonder
hoeveelheden; de achterkant heeft de ingrediëntentabel (naam | hoeveelheid),
de stappen, een voedingswaardentabel en allergenen. Nu levert zo'n kaart twee
halve concepten op, en de tabel komt in de OCR-tekst uit elkaar getrokken
aan: eerst een blok namen, dan een blok hoeveelheden met stapnummers ertussen,
en de laatste hoeveelheden pas ná de kop "Voedingswaarden". Het model maakte
daar op de ene kaart die we hebben 14 van de 15 rijen goed van — maar niets
in de tekst verraadt het als een hoeveelheid aan de verkeerde naam wordt
gehangen, en dat is precies de fout die stil in de boodschappenlijst belandt.

## Uitgangspunten

- **Niets wordt getraind.** Gemini draait zero-shot; de tabellezer is
  regelgebaseerd. De kaarten zijn een meetlat, geen trainingsset.
- **Generiek waar het werk zit, merkspecifiek alleen aan de rand.** Paren,
  rijen uit geometrie, de tabel-leidend-controle en ankers over twee
  pagina's kennen geen merk. Alleen de voorkant/achterkant-herkenning en het
  voorraadblok hebben per merk een signatuur, in één klein bestand, met een
  merkloze terugval.
- **Markeren, niet corrigeren.** Wijkt het model af van de tabel, dan wordt
  dat zichtbaar (`check`, melding); de app schrijft geen getallen om.
- **Geen stille gaten.** Een paar dat niet klopt levert geen concept op maar
  wél een melding met paginanummers; een tabelrij die het model niet
  teruggeeft wordt gemeld.

## Scope

In: modus-keuze en vlag op de batch, paren met controle, tabelrijen uit
Vision-coördinaten, kaartprompt, tabel-leidend-controle, ankers over beide
pagina's, voorraad-items, benodigdheden en tips in de bereiding,
bereidingstijd als veld, nakijkkaart met achterkant.

Uit: tabellen met meer dan één hoeveelheidkolom (worden herkend en
geweigerd, niet geraden), automatisch omschakelen van modus, andere
kaartformaten dan twee pagina's, herkenning van gerechtfoto op de kaart.

## Datamodel

Alle kolommen nullable/met default, via een idempotente `ALTER TABLE`-migratie
(`_migrate_v16`, zelfde patroon als `_migrate_v15`; `db.create_all()` dekt
alleen nieuwe installaties).

| Tabel | Kolom | Type | Doel |
|---|---|---|---|
| `dump_job` | `mode` | VARCHAR(10), default `'boek'` | `'boek'` of `'kaart'`; gelezen door `process_dump_job` en dus ook door retry |
| `recipe` | `prep_time` | INTEGER | bereidingstijd in minuten |
| `recipe_draft` | `prep_time` | INTEGER | idem, vóór acceptatie |
| `recipe_draft` | `back_image_path` | VARCHAR(200) | achterkantfoto, alleen voor de nakijkkaart |

`prep_time` wordt al aan het model gevraagd (`services/gemini.py`) maar
bestond nergens; dit is de eerste plek die hem bewaart.

## Modus

`/dump` krijgt naast de kookboekkeuze een keuze **Soort scan**:
"kookboekpagina's" (default) of "receptkaarten — 2 pagina's per recept".
`dump_upload` en `dump_share` geven `mode` door aan `start_dump_job`, die hem
op `DumpJob.mode` zet. `process_dump_job` leest de vlag van de job, nooit uit
het request: retry draait in een achtergrondthread zonder request.

**Vangnet in boekmodus:** matchen twee of meer pagina's de `voorkant`-
signatuur van een merk (alleen die tekstregex; de tabellezer draait in
boekmodus niet), dan komt er een melding bij de batch: "Pagina's 1, 2, 3, 4
lijken receptkaarten. Kies 'receptkaarten' als soort scan en probeer
opnieuw." De batch wordt verder gewoon als boek verwerkt; er wordt niet stil
omgeschakeld.

## Paren en controle

In kaartmodus worden pagina's op volgorde gepaard: (1, 2), (3, 4), …

Per paar de controle: precies één **achterkant** en één **voorkant**.
- Achterkant = de pagina waarop een ingrediëntentabel wordt gevonden (zie
  Tabel). Dat is merkloos.
- Voorkant = de andere pagina, mits hij géén tabel heeft. Een merksignatuur
  (`HELLO`/`FRESH` op de pagina) telt als bevestiging, niet als vereiste.

Volgorde binnen het paar maakt niet uit (achterkant eerst is ook goed).

Klopt het niet (twee tabellen, geen tabel, oneven aantal pagina's), dan
levert dat paar **geen concept** op en komt er een melding: "Pagina's 5 en 6
zijn niet als één kaart te lezen: op geen van beide staat een
ingrediëntentabel." Een oneven laatste pagina: "Pagina 7 heeft geen
tegenhanger." De overige paren gaan gewoon door — Vision en Gemini zijn dan
niet voor niets aangeroepen.

Het concept krijgt `source_page` en `image_path` van de **voorkant**
(gerechtfoto) en `back_image_path` van de achterkant.

## Tabel uit geometrie

Nieuwe module `weekmenu/services/tabel.py`. Vision levert per woord vier
hoekpunten (`boundingBox.vertices`); op de kaart in de cache hebben 654 van
660 woorden ze volledig. **Vision laat nulwaarden weg in JSON**: een vertex
zonder `x` betekent `x = 0`. De parser vult dat aan.

`tabelrijen(annotation)` geeft `[{'naam', 'hoeveelheid', 'blok', 'y'}]` of
`None`:

1. Woorden → boxen (`tekst, x0, x1, y0, y1`), uit dezelfde
   `fullTextAnnotation` die `lees_paginas` al in handen heeft. `lees_paginas`
   geeft daarom in kaartmodus de annotaties per pagina terug in plaats van ze
   weg te gooien (nieuwe functie `lees_paginas_met_annotaties`, de bestaande
   blijft voor boekmodus).
2. Rijen: woorden gesorteerd op verticaal middelpunt; een woord hoort bij de
   lopende rij als zijn middelpunt binnen de y-band van die rij valt.
3. Cellen: per rij het grootste horizontale gat als kolomgrens → links de
   naam, rechts de hoeveelheid. Gat kleiner dan een drempel (~ 1,5 × de
   gemiddelde woordhoogte) → geen tabelrij.
4. Tabelgebied, **merkloos**: het langste blok van opeenvolgende rijen
   waarvan de rechtercel op een hoeveelheid lijkt (`\d`, breukteken, `naar
   smaak`, of leeg terwijl de buren gevuld zijn). Rijen met een linkercel
   zonder letters (losse stapnummers) worden overgeslagen, niet meegeteld.
   Minimaal 3 zulke rijen, anders `None`.
5. Naam opschonen: allergeencodes (`\s\d+\)`)+ en asterisken eraf; een naam
   die over twee rijen loopt (rechtercel leeg, volgende rij heeft wel een
   hoeveelheid en begint met kleine letter) wordt samengevoegd.
6. Blok: rijen onder een rij die op een voorraadkop lijkt (merksignatuur,
   HelloFresh: "Zelf toevoegen") krijgen `blok = 'voorraad'`, de rest
   `'kaart'`. Zonder signatuur: alles `'kaart'`.
7. **Meerdere hoeveelheidkolommen**: clusteren de rechtercellen op x in twee
   of meer groepen die elk minstens 3 rijen bevatten, dan `None` met reden
   `'meerdere kolommen'`. Er wordt niet geraden welke kolom bedoeld is.

Uitvoer wordt bewaard in de jobmap (`tabel_p<N>.json`) zodat hermeten geen
Vision-aanroep kost, net als de `.full.json`-cache in de benchmark.

## Signaturen (merkspecifiek)

`weekmenu/services/kaartsignaturen.py`: één dict per merk met
`voorkant` (regex op paginatekst), `voorraadkop` (regex op een tabelrij),
`bereidingstijd` (regex met minutengroep), `benodigdheden` (regex op een
kopregel). Eerst alleen HelloFresh: `HELLO\s*FRESH`, `^Zelf toevoegen`,
`Bereidingstijd:\s*(\d+)\s*min`, `^Benodigdheden`. Alle
gebruikers van dit bestand werken ook zonder treffer (dan: geen bevestiging,
alles `'kaart'`, `prep_time = None`). Een nieuw merk is een nieuwe dict,
geen nieuwe code.

## Prompt

`_KAART_PROMPT` naast `_BATCH_PROMPT` in `services/dump.py`, per paar één
aanroep. Invoer:

```
--- Voorkant (pagina 1) ---
<opgeschoonde tekst voorkant>
--- Ingrediënten (tabel) ---
Halfkruimige aardappelen | 500 g
Pindakaas | 2 kuipje
Extra vierge olijfolie | naar smaak
--- Achterkant (pagina 2) ---
<opgeschoonde tekst achterkant, tabelrijen eruit>
```

Verschillen met de boekprompt: precies één recept; `ingredients` uitsluitend
uit het tabelblok, in die volgorde; `yields` uit "voor N personen" als dat
er staat; `photo_page` wordt niet gevraagd; `steps` als ankers zoals nu, met
de opmerking dat een stap op de voorkant kan beginnen. Verder gelden alle
regels van `_BATCH_PROMPT` (eenheden, breuken letterlijk, "volle", geen
verzinsels). De tabelrijen worden uit de achterkanttekst gehaald zodat de
ankers niet op een tabelregel kunnen vallen.

## Tabel is leidend: de controle

Na `parse_batch_response` (het bestaande `steps`-pad) koppelt
`_controleer_tegen_tabel(recipe, rijen)` elk ingrediënt aan een rij op
woordoverlap (≥ 3 letters, zelfde helper-stijl als `_ingredient_bij_regel`),
elke rij hooguit één keer.

| Situatie | Gevolg |
|---|---|
| Hoeveelheid + eenheid van het model ≠ celtekst (na normalisatie van breuken en eenheden via de bestaande `units`-logica) | `check` op het ingrediënt: "tabel zegt '500 g'" |
| Ingrediënt zonder rij | `check`: "staat niet in de tabel" — blijft staan, gaat niet weg |
| Rij zonder ingrediënt | melding bij de batch: "Pagina 2: tabelrij 'Kokosmelk | 100 ml' ontbreekt in het concept" |
| Rij uit blok `'voorraad'` | ingrediënt krijgt `in_pantry: true` (alleen als `annotate_pantry_status` geen echte treffer had) |

De nakijkkaart (`dump.html`) toont `check` al oranje en het formulier ook;
er is geen nieuwe weergave nodig. De nakijkkaart krijgt wél een link naar
de achterkant (`back_image_path`) naast de gerechtfoto.

## Ankers over beide pagina's

`knip_stappen` krijgt als paginatekst de opgeschoonde voorkant + `'\n'` +
achterkant (zonder tabelrijen). De bestaande machinerie werkt daar
ongewijzigd op: exact → zonder hoofdletters → fuzzy, gat bij de vorige stap,
`_zonder_meubilair` (bestaat al vanwege deze tabel), staartmelding.
Meldingen noemen het paginanummer: de knipper krijgt de startpositie van de
achterkant mee en vertaalt een regelpositie naar "pagina 1" of "pagina 2".

Benodigdheden: de regel(s) onder een kop die op `Benodigdheden` matcht (in
de signaturen; HelloFresh en de meeste merken gebruiken dat woord) worden
als eerste regel van de bereiding gezet, letterlijk uit de OCR-tekst, met
het voorvoegsel "Benodigdheden: ". Tips en weetjes blijven in de bereiding
zoals de huidige route ze al meeneemt.

## Bereidingstijd

Losse eerste stap, onafhankelijk van de kaartmodus: `prep_time` op `Recipe`
en `RecipeDraft`, veld "Bereidingstijd (min.)" in het receptformulier
(nieuw en bewerken), zichtbaar op de receptpagina en op de nakijkkaart. De
bestaande foto- en linkimport (`services/gemini.py`) vullen hem vanaf dan
ook, want die vragen hem al. Kaartmodus vult hem uit de voorkant via de
signatuur.

## Fouten en meldingen

Alles via het bestaande `job.warning`-kanaal en de `check`-tekst. Nieuw
zijn alleen de teksten (paar klopt niet, oneven pagina, meerdere kolommen,
tabelrij ontbreekt, vangnet in boekmodus). Een paar dat faalt kost de batch
niet: de rest gaat door, en de rollback bij een mislukte batch blijft zoals
hij is.

## Testen

**Unit (pytest, zonder API):** `tabelrijen` op de bewaarde annotatie van
8f4d4064 (fixture in `tests/fixtures/`) én op synthetische annotaties
(rij-samenvoeging, allergeencodes, stapnummer tussen de rijen, meerdere
kolommen → `None`, ontbrekende `x`); paren en controle op synthetische
teksten; `_controleer_tegen_tabel` op de vier situaties uit de tabel
hierboven; ankers over twee pagina's met een stap die op de voorkant begint;
retry leest `mode` van de job; vangnet in boekmodus.

**Meetlat:** 12 kaarten van Rutger, waarvan 3 blind (niet bekeken tijdens
het bouwen; als er een ander merk bij zit hoort die bij de blinde drie).
Vision-antwoorden als `.full.json` in `benchmark-import/ocrtekst/`, één
Gemini-aanroep per kaart, daarna alles uit cache (`herknip`-stijl script
`proef2/acceptatie_kaart.py`).

**Acceptatie per kaart:** elke tabelrij is een ingrediënt met exact de
celhoeveelheid; 0 ingrediënten buiten de tabel zonder `check`; 0 meldingen
"tabelrij ontbreekt" op de negen zichtbare kaarten; bereiding letterlijk uit
de OCR (zelfde toets als `herknip.py`); voorraad-items gemarkeerd. Op de
drie blinde kaarten dezelfde toets één keer, zonder bijstellen; afwijkingen
worden gerapporteerd, niet weggewerkt.

**Terugval:** slaagt de rij-reconstructie op de bestaande kaart niet (eerste
taak in het plan), dan vervalt het tabelblok in de prompt en blijft de
controle achteraf staan tegen wat er wél aan rijen is gevonden. Dat wordt dan
gemeld als ontwerpwijziging, niet stil doorgevoerd.

## Open punten

- Een kaart waarvan de voorkant ontbreekt (alleen achterkant gescand) heeft
  geen titel; bewust buiten scope — de melding "geen tegenhanger" dekt het.
- `back_image_path` is het eerste dat sneuvelt als de stap kleiner moet;
  niets anders hangt eraan.
