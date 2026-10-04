# Afgevinkt blijft afgevinkt — implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een vinkje en een ✕ leggen een hoeveelheid vast; toevoegen zet alleen het nieuwe op de boodschappenlijst.

**Architecture:** Nieuw bestand `weekmenu/services/afgehandeld.py` beheert per (week, ingrediënt) wat afgevinkt en weggehaald is, als JSON `{eenheid: hoeveelheid}` (NULL = alles). `services/shopping.py` rekent per week `open = nodig − afgevinkt − weggehaald`; alle gebaren (afvinken, ✕, plannen, + Recept, bewerken, voorraad, samenvoegen) schrijven via `afgehandeld`. `zet_terug_op_de_lijst` blijft alleen voor uit de voorraad halen.

**Tech Stack:** Flask, Flask-SQLAlchemy (SQLite), pytest (in-memory), vanilla JS.

**Spec:** `docs/superpowers/specs/2026-10-04-afgevinkt-blijft-afgevinkt-design.md`

## Global Constraints

- Werkmap `/pool/apps/weekmenu/dev`, branch `afgevinkt-blijft-afgevinkt`, bovenop `main` (61965fb).
- Migratie v23 additief; oude migraties nooit wijzigen (CLAUDE.md).
- Nooit buiten de app om in `/pool/apps/weekmenu/live/data/weekmenu.db` schrijven; meten op een kopie in de scratchpad.
- Nederlandse gedragsnamen voor tests, waarom-gedreven docstrings, Nederlandse commitberichten zonder `Co-Authored-By`.
- `python3 -m pytest -q -p no:cacheprovider` groen na elke taak.
- Versie wordt `0.9.0-beta`.
- Afrondingsruis: alles onder `EPS = 1e-6` telt als nul.

## Review Focus

1. **Vinkje uitzetten in het afgevinkt-blok** mag alleen de weken van de laatste 14 dagen openen (nu: kidneybonen 9 + 1 blik). Test in Taak 4.
2. **Eenheid die niet meer bestaat** (2 ui stuks afgevinkt, los item weg, recept 100 g ui erbij) mag de nieuwe ui niet stil verbergen. Test in Taak 3.
3. **Afrondingsruis**: drie keer een derde afvinken mag geen regel van 0,0000001 open laten. Test in Taak 3.
4. **Afgeronde week** (v21-rijen zonder getal) blijft dicht bij plannen-in-een-andere-week, bewerken en samenvoegen, en verschijnt niet in het afgevinkt-blok. Test in Taak 6 en 8.
5. **"Zelfde maaltijd?" met een los recept uit een andere week** mag dat losse recept niet weghalen. Test in Taak 5.

---

## Bestanden

| Bestand | Rol |
|---|---|
| `weekmenu/services/afgehandeld.py` (nieuw) | Lezen/schrijven van afgevinkt en weggehaald per week; eenmalig vullen na v23 |
| `weekmenu/models.py` | Kolommen `hoeveelheden` (check + uitsluiting), `weggehaald_op` (uitsluiting) |
| `weekmenu/migrations.py` | `_migrate_v23` + `target = 23` |
| `weekmenu/__init__.py` | `vul_hoeveelheden_aan()` na `migrate_db()`; versie 0.9.0-beta |
| `weekmenu/services/shopping.py` | `week_nodig`, `bijdrage_van_regel`, `_week_stand`, nieuwe `build_combined_shopping_list` en `lopende_weken`, `momentopname`, `weken_van_recept` |
| `weekmenu/routes/shopping.py` | Afvinken, ✕, terugzetten, + Recept (`erbij`), dode routes weg |
| `weekmenu/services/menu.py` | `plan_recipe`/`update_week_menu` zonder terugzet, met `neem_over`; dode `clear_shopping_list` weg |
| `weekmenu/routes/menu.py` | `neem_los_recept_over` doorgeven; losse recepten in paginadata |
| `weekmenu/routes/recipes.py` | Bewerken: afgehandeld deel groeit mee |
| `weekmenu/services/ingredienten.py` | Samenvoegen: vinkjes optellen |
| `templates/boodschappen.html`, `static/js/boodschappen.js` | Afgevinkt-blok met weggehaald + terugzetten; + Recept vraagt |
| `static/js/zelfde-maaltijd.js` (nieuw) | Het venster "Is dit dezelfde maaltijd?" |
| `templates/week_menu.html`, `static/js/week_menu.js` | Vraag bij plannen in het weekmenu |
| `templates/receptenplanner.html`, `static/js/receptenplanner.js` | Vraag bij plannen via de receptenplanner |
| `tests/test_afgevinkt_blijft_afgevinkt.py` (nieuw) | Gedragstests van deze spec |
| `tests/test_opnieuw_plannen.py`, `tests/test_toevoeg_gebaren.py`, `tests/test_combined_shopping.py`, `tests/test_ingredient_varianten.py` | Aanpassen waar ze de oude regel vastleggen |
| `CLAUDE.md` | v1..v23, `afgehandeld.py`, versie |

---

### Task 1: Dode boodschappencode opruimen

**Files:**
- Modify: `weekmenu/routes/shopping.py` (routes `clear_shopping_list`, `exclude_shopping_item`, import `_clear_shopping_list`)
- Modify: `weekmenu/services/menu.py` (functie `clear_shopping_list`)
- Modify: `weekmenu/services/shopping.py` (`window_weeks(today=None)` → `window_weeks()`)

**Interfaces:**
- Produces: `window_weeks() -> list[tuple[int, int]]` (geen parameter meer)

- [ ] **Step 1: Bewijs dat ze dood zijn**

Run: `grep -rn "item/.*/exclude\|shopping-list/.*/clear\|clear_shopping_list\|exclude_shopping_item" static templates tests weekmenu`
Expected: alleen de definities in `routes/shopping.py` en `services/menu.py`.

- [ ] **Step 2: Verwijderen**

In `weekmenu/routes/shopping.py`: verwijder de route `clear_shopping_list` (`/api/shopping-list/<int:year>/<int:week>/clear`) en `exclude_shopping_item` (`/api/shopping-list/<int:year>/<int:week>/item/<int:ingredient_id>/exclude`), en `clear_shopping_list as _clear_shopping_list` uit de import van `weekmenu.services.menu`.
In `weekmenu/services/menu.py`: verwijder `def clear_shopping_list(week, year)`.
In `weekmenu/services/shopping.py`: `def window_weeks():` zonder `today`, haal `del today` weg, en roep in `build_combined_shopping_list` `window_weeks()` aan.

- [ ] **Step 3: Tests**

Run: `python3 -m pytest -q -p no:cacheprovider`
Expected: 576 passed, 1 skipped.

- [ ] **Step 4: Commit**

```bash
git add -A weekmenu
git commit -m "Dode boodschappenroutes weg: uitsluiten en lijst wissen per week

Geen aanroeper in de frontend of de tests, en ze schreven uitsluitingen
buiten de lijst om. window_weeks gebruikte zijn parameter al niet meer."
```

---

### Task 2: Datamodel, migratie v23 en het afgehandeld-model

**Files:**
- Modify: `weekmenu/models.py` (`ShoppingCheck`, `ShoppingListExclusion`)
- Modify: `weekmenu/migrations.py` (`_migrate_v23`, `migrate_db`)
- Create: `weekmenu/services/afgehandeld.py`
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`

**Interfaces:**
- Produces (in `weekmenu/services/afgehandeld.py`):
  - `ALLES = None`, `EPS = 1e-6`
  - `lees(rij) -> dict[str, float] | None` — `{}` voor geen rij, `ALLES` voor NULL
  - `vink_af(jaar, week, ingredient_id, per_eenheid: dict, via_ah=False) -> None`
  - `haal_weg(jaar, week, ingredient_id, per_eenheid: dict) -> None`
  - `vinkje_eraf(jaar, week, ingredient_id) -> None`, `kruisje_eraf(jaar, week, ingredient_id) -> None`
  - `zet_terug(jaar, week, ingredient_id) -> None` — beide weg
  - `sluit_af(jaar, week, ingredient_id) -> None` — vinkje op ALLES, datum = maandag van die week 12:00 als de rij nieuw is
  - `groei_mee(jaar, week, ingredient_id, eenheid, extra, nodig_oud) -> None`

- [ ] **Step 1: Failing tests**

```python
# tests/test_afgevinkt_blijft_afgevinkt.py
"""Afgevinkt blijft afgevinkt; toevoegen zet alleen het nieuwe op de lijst.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import ShoppingCheck, ShoppingListExclusion
from weekmenu.services import afgehandeld


def test_afvinken_telt_hoeveelheden_per_eenheid_op(app):
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    afgehandeld.vink_af(2026, 40, 7, {'blik': 6, 'g': 50})
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) == {'blik': 7, 'g': 50}


def test_een_rij_zonder_getal_betekent_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES
    assert afgehandeld.lees(None) == {}


def test_afvinken_bovenop_alles_blijft_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES


def test_weghalen_zet_de_datum_voor_het_afgevinkt_blok(app):
    afgehandeld.haal_weg(2026, 40, 2, {'g': 200})
    db.session.commit()
    rij = ShoppingListExclusion.query.one()
    assert afgehandeld.lees(rij) == {'g': 200}
    assert rij.weggehaald_op is not None


def test_afsluiten_dateert_een_nieuw_vinkje_op_de_maandag_van_die_week(app):
    afgehandeld.sluit_af(2026, 32, 7)
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) is afgehandeld.ALLES
    assert rij.checked_at.date() == date.fromisocalendar(2026, 32, 1)


def test_meegroeien_naar_rato_van_wat_al_afgehandeld_was(app):
    # Chili-week: nodig 7 blik, 1 gekocht; recept +50% geeft 3,5 extra.
    afgehandeld.vink_af(2026, 40, 158, {'blik': 1})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 158, 'blik', extra=3.5, nodig_oud=7)
    assert afgehandeld.lees(ShoppingCheck.query.one()) == {'blik': 1.5}


def test_meegroeien_verdeelt_over_vinkje_en_kruisje_en_nooit_meer_dan_het_extra(app):
    afgehandeld.vink_af(2026, 40, 1, {'g': 600})
    afgehandeld.haal_weg(2026, 40, 1, {'g': 600})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 1, 'g', extra=100, nodig_oud=1000)  # 120% afgehandeld
    a = afgehandeld.lees(ShoppingCheck.query.one())['g']
    w = afgehandeld.lees(ShoppingListExclusion.query.one())['g']
    assert round(a + w - 1200, 6) == 100
    assert round(a - w, 6) == 0
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py`
Expected: FAIL met `ImportError: cannot import name 'afgehandeld'`.

- [ ] **Step 3: Model + migratie**

In `weekmenu/models.py`, `ShoppingListExclusion` erbij:
```python
    # JSON {eenheid: hoeveelheid}; NULL = alles van het receptdeel (rijen van
    # vóór v23). Zie services/afgehandeld.py.
    hoeveelheden  = db.Column(db.Text, nullable=True)
    weggehaald_op = db.Column(db.DateTime, nullable=True)
```
In `ShoppingCheck` erbij:
```python
    # JSON {eenheid: hoeveelheid}; NULL = alles, ook wat er later bij komt.
    hoeveelheden  = db.Column(db.Text, nullable=True)
```
In `weekmenu/migrations.py`, na `_migrate_v22`:
```python
def _migrate_v23(conn):
    """Vinkjes en kruisjes onthouden hoeveel, niet alleen dat.

    Rutger, 4 okt 2026: 'Voeg ik iets opnieuw toe, moet dat geen impact hebben
    op wat ik eerder heb gedaan.' Met alleen een status moest de app bij elke
    toevoeging kiezen tussen alles dicht of alles open; in week 40 gaf dat 7
    blik kidneybonen waar 6 klopte. Een rij zonder getal blijft 'alles'
    betekenen, precies zoals voorheen. Het vullen met echte getallen gebeurt
    na de migratie via de ORM (afgehandeld.vul_hoeveelheden_aan): daarvoor is
    de rekenkant van de lijst nodig, en die hoort niet in een migratie.
    """
    for tabel, kolommen in (('shopping_check', (('hoeveelheden', 'TEXT'),)),
                            ('shopping_list_exclusion', (('hoeveelheden', 'TEXT'),
                                                         ('weggehaald_op', 'DATETIME')))):
        bestaand = {r[1] for r in conn.execute(text(f'PRAGMA table_info({tabel})')).fetchall()}
        for naam, soort in kolommen:
            if naam not in bestaand:
                conn.execute(text(f'ALTER TABLE {tabel} ADD COLUMN {naam} {soort}'))

    rijen = conn.execute(text(
        'SELECT (SELECT COUNT(*) FROM shopping_check) + '
        '(SELECT COUNT(*) FROM shopping_list_exclusion)')).scalar()
    if rijen:
        conn.execute(text("DELETE FROM settings WHERE key = 'afgehandeld_vullen'"))
        conn.execute(text("INSERT INTO settings (key, value) VALUES ('afgehandeld_vullen', '1')"))
```
In `migrate_db()`: `if current < 23: _migrate_v23(conn)` na v22, en `target = 23`.

- [ ] **Step 4: `weekmenu/services/afgehandeld.py`**

```python
"""Wat er per week per ingredient al afgehandeld is: afgevinkt of weggehaald.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status. Op
de lijst staat per week: nodig - afgevinkt - weggehaald (services/shopping.py).

`hoeveelheden` is JSON {eenheid: hoeveelheid}. NULL betekent 'alles', ook wat
er later bij komt: zo bleven rijen van voor v23 werken, en zo houdt
sluit_af een week die geweest is dicht.
"""
import json
from datetime import date, datetime

from weekmenu.extensions import db
from weekmenu.models import ShoppingCheck, ShoppingListExclusion

ALLES = None
EPS = 1e-6


def lees(rij):
    """{eenheid: hoeveelheid} van een rij; {} zonder rij, ALLES zonder getal."""
    if rij is None:
        return {}
    if rij.hoeveelheden is None:
        return ALLES
    return json.loads(rij.hoeveelheden)


def _schrijf(rij, per_eenheid):
    if per_eenheid is ALLES:
        rij.hoeveelheden = None
    else:
        rij.hoeveelheden = json.dumps(
            {u: round(a, 6) for u, a in sorted(per_eenheid.items()) if a > EPS})


def _tel_op(oud, erbij):
    if oud is ALLES:
        return ALLES
    som = dict(oud)
    for eenheid, hoeveel in erbij.items():
        som[eenheid] = som.get(eenheid, 0) + hoeveel
    return som


def _rij(model, jaar, week, ingredient_id, **nieuw):
    rij = model.query.filter_by(year=jaar, week_number=week,
                                ingredient_id=ingredient_id).first()
    if rij is None:
        rij = model(year=jaar, week_number=week, ingredient_id=ingredient_id,
                    hoeveelheden='{}', **nieuw)
        db.session.add(rij)
    return rij


def vink_af(jaar, week, ingredient_id, per_eenheid, via_ah=False):
    """Leg vast dat deze hoeveelheid gekocht is (in de kar ligt)."""
    rij = _rij(ShoppingCheck, jaar, week, ingredient_id, via_ah=via_ah)
    _schrijf(rij, _tel_op(lees(rij), per_eenheid))
    rij.checked_at = datetime.now()
    rij.via_ah = bool(rij.via_ah) or via_ah


def haal_weg(jaar, week, ingredient_id, per_eenheid):
    """Leg vast dat deze hoeveelheid niet gekocht hoeft te worden (✕)."""
    rij = _rij(ShoppingListExclusion, jaar, week, ingredient_id)
    _schrijf(rij, _tel_op(lees(rij), per_eenheid))
    rij.weggehaald_op = datetime.now()


def vinkje_eraf(jaar, week, ingredient_id):
    ShoppingCheck.query.filter_by(year=jaar, week_number=week,
                                  ingredient_id=ingredient_id).delete()


def kruisje_eraf(jaar, week, ingredient_id):
    ShoppingListExclusion.query.filter_by(year=jaar, week_number=week,
                                          ingredient_id=ingredient_id).delete()


def zet_terug(jaar, week, ingredient_id):
    """Alles weer open. Alleen voor uit de voorraad halen: 'ik heb het toch niet
    in huis' spreekt een vinkje van voor de voorraad tegen."""
    vinkje_eraf(jaar, week, ingredient_id)
    kruisje_eraf(jaar, week, ingredient_id)


def sluit_af(jaar, week, ingredient_id):
    """Een week die geweest is blijft dicht, ook voor wat er later bij komt.

    Een nieuw vinkje krijgt de maandag van die week als datum, niet nu: anders
    verschijnt een regel uit augustus in het afgevinkt-blok van de laatste
    veertien dagen (zelfde reden als in migratie v21).
    """
    maandag = datetime.combine(date.fromisocalendar(jaar, week, 1),
                               datetime.min.time()).replace(hour=12)
    rij = _rij(ShoppingCheck, jaar, week, ingredient_id, checked_at=maandag)
    _schrijf(rij, ALLES)


def groei_mee(jaar, week, ingredient_id, eenheid, extra, nodig_oud):
    """Recept bewerken: het al afgehandelde deel groeit naar rato mee.

    Rutger, 4 okt 2026: gekocht is gekocht, ook als hij een gepland recept
    groter maakt. Volledig afgehandeld: niets open. Half: alleen de helft van
    het extra open, want het nog niet gekochte deel volgt het nieuwe recept.
    Samen nooit meer dan het extra, ook als er na inkorten meer afgehandeld
    is dan nodig.
    """
    if extra <= EPS or nodig_oud <= EPS:
        return
    rijen = [r for r in (
        ShoppingCheck.query.filter_by(year=jaar, week_number=week,
                                      ingredient_id=ingredient_id).first(),
        ShoppingListExclusion.query.filter_by(year=jaar, week_number=week,
                                              ingredient_id=ingredient_id).first(),
    ) if r is not None and lees(r) is not ALLES]
    delen = [lees(r).get(eenheid, 0) for r in rijen]
    totaal = sum(delen)
    if totaal <= EPS:
        return
    erbij = extra * min(1.0, totaal / nodig_oud)
    for rij, deel in zip(rijen, delen):
        per = lees(rij)
        per[eenheid] = deel + erbij * deel / totaal
        _schrijf(rij, per)
```

- [ ] **Step 5: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py`
Expected: 7 passed. Daarna de volledige suite: 576 + 7 passed (de oude rekenkant leest de nieuwe kolom nog niet; rijen zonder getal gedragen zich als voorheen).

- [ ] **Step 6: Commit**

```bash
git add weekmenu/models.py weekmenu/migrations.py weekmenu/services/afgehandeld.py tests/test_afgevinkt_blijft_afgevinkt.py
git commit -m "Vinkjes en kruisjes kunnen een hoeveelheid onthouden (v23)

Nog zonder gebruik door de lijst: dit is de opslag en de rekenregel per
rij. Een rij zonder getal betekent 'alles', zoals rijen van voor v23."
```

---

### Task 3: De lijst rekent met hoeveelheden

**Files:**
- Modify: `weekmenu/services/shopping.py` (vervang `_build_shopping_dict`, `lopende_weken`, `build_combined_shopping_list`)
- Modify: `tests/test_combined_shopping.py:150-151`, `tests/test_toevoeg_gebaren.py:64-69` (gebruik `week_nodig`)
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`

**Interfaces:**
- Consumes: `afgehandeld.lees`, `ALLES`, `EPS`
- Produces (in `weekmenu/services/shopping.py`):
  - `omrekening() -> tuple(conversions, preferred_units, pantry_ids)`
  - `bijdrage_van_regel(ri, serves, people_count, omr) -> tuple(ingredient_id, eenheid, hoeveelheid)`
  - `week_nodig(jaar, week, omr=None) -> tuple(nodig: dict[(ing, eenheid)] -> float, receptdeel: dict, bronnen: dict[ing] -> set[str])`
  - `build_combined_shopping_list(today=None) -> dict` met sleutels `open`, `checked` (rijen met `soort` = `'afgevinkt'|'weggehaald'`), `open_per_week` (`{ing: {(j, w): {eenheid: open}}}`), `weeks_by_ingredient` (`{ing: [(j, w)]}` = weken waarin iets open staat), `afgevinkt_weken`, `weggehaald_weken` (`{ing: [(j, w)]}`, laatste 14 dagen), `quick_add` (met `year`, `week`)
  - `lopende_weken(today=None) -> set[(j, w)]`

- [ ] **Step 1: Failing tests** (toevoegen aan `tests/test_afgevinkt_blijft_afgevinkt.py`)

```python
from weekmenu.models import (CustomShoppingIngredient, Ingredient, MenuItem,
                             QuickAddItem, Recipe, RecipeIngredient)
from weekmenu.services.shopping import build_combined_shopping_list, lopende_weken

JAAR, WEEK = date.today().isocalendar()[0], date.today().isocalendar()[1]


def _ing(naam):
    ing = Ingredient.query.filter_by(name=naam).first()
    if not ing:
        ing = Ingredient(name=naam, display_name=naam, category='overig')
        db.session.add(ing)
        db.session.flush()
    return ing


def _recept(naam, regels, serves=2):
    r = Recipe(name=naam, serves=serves)
    db.session.add(r)
    db.session.flush()
    for ing_naam, hoeveel, eenheid in regels:
        db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=_ing(ing_naam).id,
                                        amount=hoeveel, unit=eenheid))
    db.session.commit()
    return r


def _plan(r, personen, dag=1, jaar=JAAR, week=WEEK):
    db.session.add(MenuItem(day_of_week=dag, meal_type='diner', recipe_id=r.id,
                            people_count=personen, week_number=week, year=jaar))
    db.session.commit()


def _open(naam):
    ing = _ing(naam)
    return sum(x['amount'] for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == ing.id)


def _chili():
    return _recept('Chili', [('kidneybonen', 1, 'blik'), ('rundergehakt', 200, 'g')])


def test_rekenregel_open_is_nodig_min_afgevinkt_min_weggehaald(app):
    r = _chili()
    _plan(r, 2)
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.haal_weg(JAAR, WEEK, _ing('rundergehakt').id, {'g': 200})
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=12, year=JAAR, week_number=WEEK))
    db.session.commit()
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_een_eenheid_die_niet_meer_bestaat_verbergt_niets(app):
    ui = _ing('ui')
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=ui.id, amount=2, unit='stuks'))
    db.session.commit()
    afgehandeld.vink_af(JAAR, WEEK, ui.id, {'stuks': 2})
    CustomShoppingIngredient.query.delete()
    db.session.commit()
    _plan(_recept('Soep', [('ui', 100, 'g')], serves=2), 2)
    assert _open('ui') == 100


def test_drie_derden_afvinken_laat_geen_ruis_open(app):
    r = _recept('Taart', [('bloem', 1, 'kg')], serves=3)
    _plan(r, 3)
    for _ in range(3):
        afgehandeld.vink_af(JAAR, WEEK, _ing('bloem').id, {'kg': 1 / 3})
    db.session.commit()
    assert _open('bloem') == 0
    assert not [x for x in build_combined_shopping_list()['open']
                if x['ingredient_id'] == _ing('bloem').id]


def test_een_oude_rij_zonder_getal_dekt_alles_zoals_voorheen(app):
    r = _chili()
    _plan(r, 2)
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK,
                                 ingredient_id=_ing('kidneybonen').id))
    db.session.add(ShoppingListExclusion(year=JAAR, week_number=WEEK,
                                         ingredient_id=_ing('rundergehakt').id))
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=_ing('rundergehakt').id,
                                            amount=100, unit='g'))
    db.session.commit()
    assert _open('kidneybonen') == 0
    assert _open('rundergehakt') == 100   # een oud kruisje verborg nooit losse items


def test_afgevinkt_blok_toont_wat_er_de_laatste_14_dagen_afgevinkt_is(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    _plan(r, 14)
    db.session.add(ShoppingCheck(year=2026, week_number=13,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 3, 23, 12)))
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 7})
    db.session.commit()
    blok = [x for x in build_combined_shopping_list()['checked']
            if x['ingredient_id'] == _ing('kidneybonen').id]
    assert [(x['soort'], x['amount']) for x in blok] == [('afgevinkt', 7)]


def test_een_week_met_alleen_weggehaalde_regels_loopt_niet_meer(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    afgehandeld.haal_weg(2026, 13, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.vink_af(2026, 13, _ing('rundergehakt').id, {'g': 200})
    db.session.commit()
    assert (2026, 13) not in lopende_weken()
```
(Voeg `from datetime import datetime` toe bovenaan.)

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py`
Expected: de rekenregeltest geeft 13 kidneybonen (oude regel), het afgevinkt-blok mist `soort`.

- [ ] **Step 3: Rekenkant herschrijven** (`weekmenu/services/shopping.py`, alles boven `send_dict_to_ah`)

```python
import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import requests
from weekmenu.extensions import db
from weekmenu.models import (
    MenuItem, QuickAddItem, CustomShoppingIngredient,
    Ingredient, IngredientUnitConversion, PantryIngredient,
    ShoppingCheck, ShoppingListExclusion, ShoppingListOverride,
)
from weekmenu.constants import _UNIT_BUY_ONE
from weekmenu.services.afgehandeld import ALLES, EPS, lees
from weekmenu.services.units import (
    _norm_unit, _calc_multiplier, _convert_unit_for_agg, _calc_ah_qty, format_amount,
)
from weekmenu.services.ah import ah_get_access_token

log = logging.getLogger(__name__)
_al_gemeld = set()


def omrekening():
    """Wat elke weekberekening nodig heeft; een keer ophalen per lijst."""
    conversions = {(c.ingredient_id, c.from_unit): (c.to_unit, c.factor)
                   for c in IngredientUnitConversion.query.all()}
    preferred_units = {i.id: i.preferred_unit for i in
                       Ingredient.query.filter(Ingredient.preferred_unit.isnot(None)).all()}
    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    return conversions, preferred_units, pantry_ids


def bijdrage_van_regel(ri, serves, people_count, omr):
    """(ingredient, eenheid, hoeveelheid) van één receptregel voor zoveel personen."""
    conversions, preferred_units, _ = omr
    eenheid, hoeveel = _convert_unit_for_agg(
        ri.ingredient_id, _norm_unit(ri.unit),
        ri.amount * _calc_multiplier(serves, people_count),
        conversions, preferred_units)
    return ri.ingredient_id, eenheid, hoeveel


def _voeg_samen_per_ingredient(per_sleutel):
    """Gewichts- en volume-eenheden van één ingredient tot één regel, zoals altijd."""
    per_ing = defaultdict(list)
    for (ing_id, eenheid), hoeveel in per_sleutel.items():
        per_ing[ing_id].append((eenheid, hoeveel))
    uit = {}
    for ing_id, regels in per_ing.items():
        if len(regels) > 1 and all(u in _UNIT_BUY_ONE for u, _ in regels):
            beste, _ = max(regels, key=lambda r: r[1])
            uit[(ing_id, beste)] = sum(h for _, h in regels)
        else:
            for eenheid, hoeveel in regels:
                uit[(ing_id, eenheid)] = hoeveel
    return uit


def week_nodig(jaar, week, omr=None):
    """Wat een week vraagt, per (ingredient, eenheid), na voorraad en omrekening.

    Geeft (nodig, receptdeel, bronnen). Het receptdeel is nodig zonder losse
    items: een kruisje van voor v23 verborg alleen dat deel (BUG 4 FIX).
    Afgevinkt en weggehaald gaan er hier nog niet af; dat doet _week_stand.
    """
    omr = omr or omrekening()
    conversions, preferred_units, pantry_ids = omr
    recept = defaultdict(float)
    bronnen = defaultdict(set)

    def tel(item):
        if not item.recipe:
            return
        for ri in item.recipe.ingredients:
            if ri.ingredient_id in pantry_ids:
                continue
            ing, eenheid, hoeveel = bijdrage_van_regel(
                ri, item.recipe.serves, item.people_count, omr)
            recept[(ing, eenheid)] += hoeveel
            bronnen[ing].add(item.recipe.name)

    for mi in MenuItem.query.filter_by(week_number=week, year=jaar).all():
        if not mi.skip_shopping_list:
            tel(mi)
    for qi in QuickAddItem.query.filter_by(week_number=week, year=jaar).all():
        tel(qi)

    alles = defaultdict(float, recept)
    for ci in CustomShoppingIngredient.query.filter_by(week_number=week, year=jaar).all():
        eenheid, hoeveel = _convert_unit_for_agg(
            ci.ingredient_id, _norm_unit(ci.unit), ci.amount, conversions, preferred_units)
        alles[(ci.ingredient_id, eenheid)] += hoeveel

    return _voeg_samen_per_ingredient(alles), _voeg_samen_per_ingredient(recept), bronnen


def _doeleenheid(ing_id, eenheid, hoeveel, nodig_ing, omr):
    if eenheid in nodig_ing:
        return eenheid, hoeveel
    conversions, preferred_units, _ = omr
    naar, omgerekend = _convert_unit_for_agg(ing_id, eenheid, hoeveel,
                                             conversions, preferred_units)
    if naar in nodig_ing:
        return naar, omgerekend
    gewicht = [u for u in nodig_ing if u in _UNIT_BUY_ONE]
    if eenheid in _UNIT_BUY_ONE and len(gewicht) == 1:
        return gewicht[0], hoeveel
    return None


def _gedekt(jaar, week, ing_id, nodig_ing, per, bij_alles, omr):
    """Hoeveel van nodig_ing (per eenheid) een vinkje of kruisje dekt.

    Een eenheid die niet meer te plaatsen is telt niet mee: liever een regel
    die je nog eens afvinkt dan een regel die stil verdwijnt.
    """
    if per is ALLES:
        return {u: min(nodig_ing[u], bij_alles.get(u, 0)) for u in nodig_ing}
    gedekt = dict.fromkeys(nodig_ing, 0.0)
    for eenheid, hoeveel in per.items():
        doel = _doeleenheid(ing_id, eenheid, hoeveel, nodig_ing, omr)
        if doel is None:
            sleutel = (jaar, week, ing_id, eenheid)
            if nodig_ing and sleutel not in _al_gemeld:
                _al_gemeld.add(sleutel)
                log.warning('Afgehandeld in %s telt niet mee voor de lijst: %s %s (nodig: %s)',
                            sleutel[:3], hoeveel, eenheid, sorted(nodig_ing))
            continue
        gedekt[doel[0]] += doel[1]
    return {u: min(nodig_ing[u], gedekt[u]) for u in nodig_ing}


def _afhandeling(weken):
    sleutels = [(y, w) for (y, w) in weken]
    if not sleutels:
        return {}, {}, {}

    def per_sleutel(model):
        return {(r.year, r.week_number, r.ingredient_id): r for r in model.query.filter(
            db.tuple_(model.year, model.week_number).in_(sleutels)).all()}

    overrides = {k: r.qty for k, r in per_sleutel(ShoppingListOverride).items()}
    return per_sleutel(ShoppingCheck), per_sleutel(ShoppingListExclusion), overrides


def _week_stand(jaar, week, omr, checks, excls):
    """Per ingredient per eenheid (open, afgevinkt, weggehaald) in één week."""
    nodig, receptdeel, bronnen = week_nodig(jaar, week, omr)
    per_ing, recept_ing = defaultdict(dict), defaultdict(dict)
    for (ing, u), h in nodig.items():
        per_ing[ing][u] = h
    for (ing, u), h in receptdeel.items():
        recept_ing[ing][u] = h
    stand = {}
    for ing, nodig_ing in per_ing.items():
        afg = _gedekt(jaar, week, ing, nodig_ing, lees(checks.get((jaar, week, ing))),
                      nodig_ing, omr)
        rest = {u: nodig_ing[u] - afg[u] for u in nodig_ing}
        weg = _gedekt(jaar, week, ing, rest, lees(excls.get((jaar, week, ing))),
                      recept_ing.get(ing, {}), omr)
        stand[ing] = {u: (max(0.0, rest[u] - weg[u]), afg[u], weg[u]) for u in nodig_ing}
    return stand, bronnen


def window_weeks():
    """Alle weken waarvoor iets gepland staat; welke daarvan nog iets open
    hebben, rekent build_combined_shopping_list uit."""
    weken = set()
    for model in (MenuItem, QuickAddItem, CustomShoppingIngredient):
        for y, w in db.session.query(model.year, model.week_number).distinct():
            weken.add((y, w))
    return sorted(weken)


def lopende_weken(today=None):
    """De weken waar een zijdelingse wijziging nog in mag doorwerken.

    Een week loopt als hij niet achter ons ligt, of als er nog iets open staat.
    Wat afgevinkt of weggehaald is telt als klaar. De kalender beantwoordt hier
    alleen de vraag 'ligt deze week achter ons'.
    """
    iso = (today or date.today()).isocalendar()
    nu = (iso[0], iso[1])
    weken = window_weeks()
    omr = omrekening()
    checks, excls, _ = _afhandeling(weken)
    lopend = set()
    for wk in weken:
        if wk >= nu:
            lopend.add(wk)
            continue
        stand, _ = _week_stand(wk[0], wk[1], omr, checks, excls)
        if any(o > EPS for per in stand.values() for (o, _, _) in per.values()):
            lopend.add(wk)
    return lopend
```

`_row_base` blijft zoals het is. Daarna:

```python
def build_combined_shopping_list(today=None):
    """De boodschappenlijst over alle weken: open = nodig - afgevinkt - weggehaald.

    Het afgevinkt-blok toont wat er de laatste veertien dagen is afgevinkt of
    weggehaald, met de hoeveelheid van dat moment — niet de som van alle weken
    ooit (kidneybonen stond er als 9 blik: week 13 + 33 + 40).
    """
    grens = datetime.combine(today or date.today(), time.min) - timedelta(days=14)
    weken = window_weeks()
    omr = omrekening()
    checks, excls, overrides = _afhandeling(weken)
    ingredienten = {}

    def ingredient(ing_id):
        if ing_id not in ingredienten:
            ingredienten[ing_id] = db.session.get(Ingredient, ing_id)
        return ingredienten[ing_id]

    open_agg, blok = {}, {}
    open_per_week = defaultdict(dict)
    afgevinkt_weken, weggehaald_weken = defaultdict(list), defaultdict(list)
    for (y, w) in weken:
        stand, bronnen = _week_stand(y, w, omr, checks, excls)
        for ing_id, per_eenheid in stand.items():
            ing = ingredient(ing_id)
            if not ing:
                continue
            check, excl = checks.get((y, w, ing_id)), excls.get((y, w, ing_id))
            vers_vinkje = bool(check and check.checked_at and check.checked_at >= grens)
            vers_kruisje = bool(excl and excl.weggehaald_op and excl.weggehaald_op >= grens)
            for eenheid, (open_, afg, weg) in per_eenheid.items():
                if open_ > EPS:
                    open_per_week[ing_id].setdefault((y, w), {})[eenheid] = open_
                    rij = open_agg.setdefault((ing_id, eenheid),
                                              {'amount': 0.0, 'qty': 0, 'bronnen': set()})
                    rij['amount'] += open_
                    rij['qty'] += overrides.get((y, w, ing_id)) or _calc_ah_qty(ing, open_, eenheid)
                    rij['bronnen'] |= bronnen.get(ing_id, set())
                for soort, vers, deel, rij_db in (('afgevinkt', vers_vinkje, afg, check),
                                                  ('weggehaald', vers_kruisje, weg, excl)):
                    if not vers or deel <= EPS:
                        continue
                    b = blok.setdefault((ing_id, eenheid, soort),
                                        {'amount': 0.0, 'bronnen': set(), 'via_ah': False,
                                         'checked_at': None})
                    b['amount'] += deel
                    b['bronnen'] |= bronnen.get(ing_id, set())
                    moment = rij_db.checked_at if soort == 'afgevinkt' else rij_db.weggehaald_op
                    b['checked_at'] = max(filter(None, (b['checked_at'], moment)))
                    b['via_ah'] = b['via_ah'] or (soort == 'afgevinkt' and bool(rij_db.via_ah))
            if vers_vinkje:
                afgevinkt_weken[ing_id].append((y, w))
            if vers_kruisje:
                weggehaald_weken[ing_id].append((y, w))

    open_rows = []
    for (ing_id, eenheid), r in open_agg.items():
        row = _row_base(ingredient(ing_id), eenheid, r['amount'], r['bronnen'])
        row['qty'] = r['qty']
        row['default_qty'] = _calc_ah_qty(ingredient(ing_id), r['amount'], eenheid)
        open_rows.append(row)

    checked_rows = []
    for (ing_id, eenheid, soort), b in blok.items():
        row = _row_base(ingredient(ing_id), eenheid, b['amount'], b['bronnen'])
        row.update(soort=soort, via_ah=b['via_ah'], checked_at=b['checked_at'])
        checked_rows.append(row)

    quick_add = [{'id': qi.id, 'recipe_id': qi.recipe_id, 'recipe_name': qi.recipe.name,
                  'people_count': qi.people_count, 'year': qi.year, 'week': qi.week_number}
                 for qi in QuickAddItem.query.filter(
                     db.tuple_(QuickAddItem.year, QuickAddItem.week_number).in_(weken)).all()
                 if qi.recipe] if weken else []

    return {'open': open_rows, 'checked': checked_rows,
            'open_per_week': dict(open_per_week),
            'weeks_by_ingredient': {i: sorted(wk) for i, wk in open_per_week.items()},
            'afgevinkt_weken': dict(afgevinkt_weken),
            'weggehaald_weken': dict(weggehaald_weken),
            'quick_add': quick_add}
```

Verwijder `_build_shopping_dict`. In `tests/test_combined_shopping.py` wordt `send_dict_to_ah(_build_shopping_dict(2026, 28), {})` → `send_dict_to_ah(week_nodig(2026, 28)[0], {})` (import aanpassen); in `tests/test_toevoeg_gebaren.py::_sluit` wordt `_build_shopping_dict(jaar, week)` → `week_nodig(jaar, week)[0]`.

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py tests/test_combined_shopping.py tests/test_voorbije_weken.py`
Expected: allemaal groen. Daarna de volledige suite: tests die nog op `zet_terug_op_de_lijst` leunen mogen hier nog groen zijn (de gebaren wissen rijen nog); rood alleen als het om weergave gaat — die repareer je hier.

- [ ] **Step 5: Commit**

```bash
git add weekmenu/services/shopping.py tests
git commit -m "Boodschappenlijst rekent: nodig min afgevinkt min weggehaald

Per week en per eenheid. Het afgevinkt-blok toont wat er de laatste
veertien dagen is afgevinkt of weggehaald, niet meer de som van alle weken
ooit (kidneybonen stond er als 9 blik). Een eenheid die niet meer te
plaatsen is verbergt niets."
```

---

### Task 4: Afvinken, ✕ en terugzetten op /boodschappen

**Files:**
- Modify: `weekmenu/routes/shopping.py` (`_set_checks` → `_vink_af`, `boodschappen_check`, `boodschappen_remove`, `boodschappen_check_all`, `boodschappen_send_to_ah`, nieuwe route `boodschappen_terugzetten`, `boodschappen()` paginadata)
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`, aanpassen `tests/test_combined_shopping.py::test_remove_endpoint_removes_custom_item`

**Interfaces:**
- Consumes: `build_combined_shopping_list()` sleutels uit Taak 3; `afgehandeld.vink_af/haal_weg/vinkje_eraf/kruisje_eraf`
- Produces: `POST /api/boodschappen/item/<id>/terugzetten` → `{'status': 'success'}` of 404

- [ ] **Step 1: Failing tests**

```python
from weekmenu.models import ShoppingListOverride


def test_afvinken_legt_de_open_hoeveelheid_vast_en_wist_de_aantal_override(app, client):
    r = _chili()
    _plan(r, 2)
    kb = _ing('kidneybonen')
    db.session.add(ShoppingListOverride(year=JAAR, week_number=WEEK, ingredient_id=kb.id, qty=3))
    db.session.commit()
    assert client.post(f'/api/boodschappen/item/{kb.id}/check', json={'checked': True}).status_code == 200
    assert afgehandeld.lees(ShoppingCheck.query.filter_by(ingredient_id=kb.id).one()) == {'blik': 1}
    assert ShoppingListOverride.query.count() == 0
    _plan(r, 12, dag=6)
    assert _open('kidneybonen') == 6


def test_weghalen_dekt_ook_een_los_item_zonder_het_te_verwijderen(app, client):
    ui = _ing('ui')
    pad = f'/api/shopping-list/{JAAR}/{WEEK}/add-item'
    client.post(pad, json={'ingredient_id': ui.id, 'amount': 2, 'unit': 'stuks'})
    client.post(f'/api/boodschappen/item/{ui.id}/remove')
    assert _open('ui') == 0
    client.post(pad, json={'ingredient_id': ui.id, 'amount': 1, 'unit': 'stuks'})
    assert _open('ui') == 1


def test_vinkje_uitzetten_opent_alleen_de_weken_van_de_laatste_14_dagen(app, client):
    # Op de live-data opende dit week 13, 18 en 33 mee: 9 + 1 blik i.p.v. 7.
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    db.session.add(ShoppingCheck(year=2026, week_number=13,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 3, 23, 12)))
    _plan(r, 14)
    db.session.commit()
    kb = _ing('kidneybonen').id
    client.post(f'/api/boodschappen/item/{kb}/check', json={'checked': True})
    assert _open('kidneybonen') == 0
    assert client.post(f'/api/boodschappen/item/{kb}/check', json={'checked': False}).status_code == 200
    assert _open('kidneybonen') == 7


def test_terugzetten_haalt_alleen_het_kruisje_weg(app, client):
    r = _chili()
    _plan(r, 2)
    gehakt = _ing('rundergehakt').id
    client.post(f'/api/boodschappen/item/{gehakt}/remove')
    blok = build_combined_shopping_list()['checked']
    assert [(x['soort'], x['amount']) for x in blok if x['ingredient_id'] == gehakt] == [('weggehaald', 200)]
    assert client.post(f'/api/boodschappen/item/{gehakt}/terugzetten').status_code == 200
    assert _open('rundergehakt') == 200
    assert client.post(f'/api/boodschappen/item/{gehakt}/terugzetten').status_code == 404
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py -k "afvinken_legt or weghalen_dekt or uitzetten or terugzetten"`
Expected: FAIL (oude `_set_checks` schrijft rijen zonder getal; terugzetten bestaat niet).

- [ ] **Step 3: Implementatie** (`weekmenu/routes/shopping.py`)

Import: `from weekmenu.services import afgehandeld`; `ShoppingCheck` en `ShoppingListExclusion` zijn hier niet meer nodig.

```python
def _vink_af(ingredient_id, data, via_ah=False):
    """Vink af wat er van dit ingredient open staat; geeft de weken terug.

    De aantal-override van die week hoort bij wat nu gekocht is en vervalt:
    anders bepaalt hij straks het aantal voor iets wat er later bij komt.
    """
    weken = data['open_per_week'].get(ingredient_id, {})
    for (y, w), per_eenheid in weken.items():
        afgehandeld.vink_af(y, w, ingredient_id, per_eenheid, via_ah=via_ah)
        ShoppingListOverride.query.filter_by(
            year=y, week_number=w, ingredient_id=ingredient_id).delete()
    return list(weken)


@bp.route('/api/boodschappen/item/<int:ingredient_id>/check', methods=['POST'])
def boodschappen_check(ingredient_id):
    body = request.get_json(silent=True) or {}
    data = build_combined_shopping_list()
    if body.get('checked', True):
        row = next((r for r in data['open'] if r['ingredient_id'] == ingredient_id), None)
        weken = _vink_af(ingredient_id, data)
        if not weken:
            return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
        db.session.commit()
        if row:
            _log_handmatig(row, weken)
        return jsonify({'status': 'success'})
    # Uitzetten in het afgevinkt-blok: alleen de weken die het blok toont.
    weken = data['afgevinkt_weken'].get(ingredient_id, [])
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w) in weken:
        afgehandeld.vinkje_eraf(y, w, ingredient_id)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/item/<int:ingredient_id>/remove', methods=['POST'])
def boodschappen_remove(ingredient_id):
    """✕: wat nu open staat hoeft niet gekocht te worden. Losse items blijven
    bestaan; het getal dekt ze, en wat er later bij komt staat gewoon open."""
    weken = build_combined_shopping_list()['open_per_week'].get(ingredient_id, {})
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w), per_eenheid in weken.items():
        afgehandeld.haal_weg(y, w, ingredient_id, per_eenheid)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/item/<int:ingredient_id>/terugzetten', methods=['POST'])
def boodschappen_terugzetten(ingredient_id):
    """Een weggehaalde regel terug op de lijst; alleen de weken die het blok toont."""
    weken = build_combined_shopping_list()['weggehaald_weken'].get(ingredient_id, [])
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w) in weken:
        afgehandeld.kruisje_eraf(y, w, ingredient_id)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/check-all', methods=['POST'])
def boodschappen_check_all():
    data = build_combined_shopping_list()
    per_ingredient = {}
    for row in data['open']:
        per_ingredient.setdefault(row['ingredient_id'], row)
    per_regel = [(row, _vink_af(ing_id, data)) for ing_id, row in per_ingredient.items()]
    db.session.commit()
    for row, weken in per_regel:
        if weken:
            _log_handmatig(row, weken)
    return jsonify({'status': 'success', 'checked': len(data['open'])})
```
In `boodschappen_send_to_ah`: `_set_checks(ing_id, True, via_ah=True, data=data, commit=False)` → `_vink_af(ing_id, data, via_ah=True)`. Verwijder `_set_checks`. In `boodschappen()` geef `quick_add` ook als JSON mee aan het template (`losse_recepten_json = json.dumps(data['quick_add'])`) voor Taak 9.

In `tests/test_combined_shopping.py::test_remove_endpoint_removes_custom_item`: hernoem naar `test_weghalen_haalt_een_los_item_van_de_lijst` en controleer alleen dat de regel niet meer open staat (de rij in `CustomShoppingIngredient` blijft bewust bestaan).

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py tests/test_combined_shopping.py tests/test_bestel_log.py tests/test_review_fixes.py`
Expected: groen. Let op `test_alles_afvinken_bouwt_de_lijst_een_keer_en_vinkt_alles_af`: nog steeds één keer bouwen.

- [ ] **Step 5: Commit**

```bash
git add weekmenu/routes/shopping.py tests
git commit -m "Afvinken en wegklikken leggen de open hoeveelheid vast

Een vinkje uitzetten opent alleen de weken uit het afgevinkt-blok; op de
live-data opende het ook week 13, 18 en 33 (kidneybonen 9 + 1 blik).
Weggehaalde regels zijn terug te zetten."
```

---

### Task 5: Toevoegen zet alleen het nieuwe erop, en "zelfde maaltijd?" aan de serverkant

**Files:**
- Modify: `weekmenu/services/menu.py` (`plan_recipe`, `update_week_menu`, `stem_af_op_de_week`; `zet_terug_op_de_lijst` en `houd_de_week_afgerond` worden dunne verwijzingen naar `afgehandeld`)
- Modify: `weekmenu/routes/menu.py` (`update_menu`, `planner_plan`)
- Modify: `weekmenu/routes/shopping.py` (`boodschappen_extra_add`, `add_shopping_item`)
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`; herschrijf `tests/test_opnieuw_plannen.py`

**Interfaces:**
- Produces: `plan_recipe(recipe_id, day, meal_type, week, year, people_count, ingredient_ids, neem_over=())`, `update_week_menu(week, year, menu_data, neem_over=())`; request-veld `neem_los_recept_over: [int]` op `/update_menu` en `/api/planner/plan`; request-veld `erbij: bool` op `/api/boodschappen/extra`.

- [ ] **Step 1: Failing tests**

```python
from weekmenu.services.menu import plan_recipe, update_week_menu


def test_chili_week_los_recept_erbij_geeft_alleen_de_nieuwe_hoeveelheid(app, client):
    r = _chili()
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')      # dinsdag gekocht
    assert client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 12}).status_code == 200
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_plannen_met_uitgevinkt_ingredient_haalt_alleen_dat_receptdeel_weg(app):
    r = _chili()
    _plan(r, 2)
    gehakt_ri = next(ri for ri in r.ingredients if ri.ingredient.name == 'rundergehakt')
    andere = [ri.id for ri in r.ingredients if ri.id != gehakt_ri.id]
    plan_recipe(r.id, 6, 'diner', WEEK, JAAR, 12, andere)
    assert _open('rundergehakt') == 200     # dinsdag nog nodig, zondag 'heb ik al'


def test_personen_erbij_zet_alleen_het_verschil_erop(app, client):
    r = _chili()
    menu = lambda p: [{'day': 1, 'meals': {'diner': {'recipe_id': r.id, 'people_count': p}}}]
    update_week_menu(WEEK, JAAR, menu(2))
    client.post('/api/boodschappen/check-all')
    update_week_menu(WEEK, JAAR, menu(4))
    assert _open('kidneybonen') == 1
    update_week_menu(WEEK, JAAR, menu(2))
    assert _open('kidneybonen') == 0


def test_zelfde_maaltijd_neemt_het_losse_recept_over(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    resp = client.post('/update_menu', json={
        'week': WEEK, 'year': JAAR, 'neem_los_recept_over': [qid],
        'menu': [{'day': 6, 'meals': {'diner': {'recipe_id': r.id, 'people_count': 12}}}]})
    assert resp.status_code == 200
    assert QuickAddItem.query.count() == 0
    assert _open('kidneybonen') == 6


def test_zelfde_maaltijd_via_de_receptenplanner(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    ids = [ri.id for ri in r.ingredients]
    client.post('/api/planner/plan', json={'recipe_id': r.id, 'day': 6, 'meal_type': 'diner',
                                           'week': WEEK, 'year': JAAR, 'people_count': 12,
                                           'ingredient_ids': ids, 'neem_los_recept_over': [qid]})
    assert QuickAddItem.query.count() == 0
    assert _open('kidneybonen') == 6


def test_een_los_recept_uit_een_andere_week_wordt_nooit_overgenomen(app, client):
    r = _chili()
    qi = QuickAddItem(recipe_id=r.id, people_count=12, year=JAAR, week_number=WEEK)
    db.session.add(qi)
    db.session.commit()
    andere_week = WEEK + 1 if WEEK < 52 else 1
    client.post('/update_menu', json={
        'week': andere_week, 'year': JAAR, 'neem_los_recept_over': [qi.id],
        'menu': [{'day': 6, 'meals': {'diner': {'recipe_id': r.id, 'people_count': 12}}}]})
    assert QuickAddItem.query.count() == 1


def test_plus_recept_erbij_maakt_een_tweede_los_recept(app, client):
    r = _chili()
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4, 'erbij': True})
    assert QuickAddItem.query.count() == 2
    assert _open('kidneybonen') == 8


def test_gekocht_blijft_in_huis_als_het_losse_recept_weg_en_terug_komt(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    client.post('/api/boodschappen/check-all')
    client.delete(f'/api/boodschappen/extra/{qid}')
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    assert _open('kidneybonen') == 0
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py`
Expected: FAIL (oude terugzetregel: 7 blik en 1600 g; `neem_los_recept_over` onbekend).

- [ ] **Step 3: Implementatie**

`weekmenu/services/menu.py` (bovenaan `from weekmenu.services import afgehandeld`):
```python
def stem_af_op_de_week(year, week, ingredient_id, lopende_weken):
    """Uit de voorraad halen: in een lopende week weer helemaal open ('ik heb
    het toch niet in huis'), in een week die geweest is dicht."""
    if (year, week) in lopende_weken:
        afgehandeld.zet_terug(year, week, ingredient_id)
    else:
        afgehandeld.sluit_af(year, week, ingredient_id)


def _neem_over(neem_over, week, year):
    """'Zelfde maaltijd': het losse recept gaat op in het weekmenu. Alleen een
    los recept uit dezelfde week; een id uit een andere week wordt genegeerd."""
    ids = [int(i) for i in neem_over or ()]
    if ids:
        QuickAddItem.query.filter(QuickAddItem.id.in_(ids),
                                  QuickAddItem.year == year,
                                  QuickAddItem.week_number == week).delete(
                                      synchronize_session=False)
```
Verwijder `zet_terug_op_de_lijst` en `houd_de_week_afgerond`. De enige andere gebruiker is `routes/recipes.py::_laat_de_geplande_weken_kloppen`: vervang daar in deze taak al `houd_de_week_afgerond(jaar, week, ri.ingredient_id)` door `afgehandeld.sluit_af(jaar, week, ri.ingredient_id)` (import `from weekmenu.services import afgehandeld`), anders breekt de suite tot Taak 6. `plan_recipe` krijgt `neem_over=()`; de lus over `recipe.ingredients` wordt:
```python
    omr = omrekening()
    for ri in recipe.ingredients:
        if ri.id not in ingredient_ids:
            # 'Heb ik al': alleen het deel van dít recept, niet de hele week.
            ing, eenheid, hoeveel = bijdrage_van_regel(ri, recipe.serves, people_count, omr)
            afgehandeld.haal_weg(year, week, ing, {eenheid: hoeveel})
    _neem_over(neem_over, week, year)
    db.session.commit()
```
(`from weekmenu.services.shopping import bijdrage_van_regel, omrekening`; `QuickAddItem` aan de model-import toevoegen.) `update_week_menu(week, year, menu_data, neem_over=())`: verwijder `old_positions`-vergelijking voor de status en de `zet_terug_op_de_lijst`-lus; usage_count/last_used blijft voor recepten die er nieuw bij komen; roep `_neem_over(neem_over, week, year)` aan vóór de commit. Docstring: "Opslaan zet nooit iets terug: wat er bij komt staat vanzelf open, wat al afgevinkt is blijft dat."

`weekmenu/routes/menu.py`: `update_week_menu(data['week'], data['year'], data['menu'], data.get('neem_los_recept_over') or [])`; in `planner_plan` `plan_recipe(..., ingredient_ids, data.get('neem_los_recept_over') or [])`.

`weekmenu/routes/shopping.py::boodschappen_extra_add`:
```python
    iso = date.today().isocalendar()
    personen = body.get('people_count') or recipe.serves or 4
    # 'Zelfde maaltijd' (de client vroeg het) past het aantal personen aan;
    # 'komt erbij' maakt een tweede los recept.
    qi = None if body.get('erbij') else QuickAddItem.query.filter_by(
        recipe_id=recipe.id, year=iso[0], week_number=iso[1]).first()
    if qi:
        qi.people_count = personen
    else:
        qi = QuickAddItem(recipe_id=recipe.id, people_count=personen,
                          year=iso[0], week_number=iso[1])
        db.session.add(qi)
    db.session.commit()
    return jsonify({'status': 'success', 'id': qi.id})
```
`add_shopping_item`: verwijder `zet_terug_op_de_lijst(year, week, ingredient_id)` en de import.

Herschrijf `tests/test_opnieuw_plannen.py`: verwijder de tests die het oude terugzetten vastleggen (`test_nieuw_recept_via_weekmenu_maakt_afgevinkt_ingredient_weer_open`, `test_plan_recipe_maakt_afgevinkt_en_uitgesloten_ingredient_weer_open`, `test_ander_aantal_personen_zet_afgevinkt_recept_terug_op_de_lijst`, `test_los_recept_toevoegen_zet_afgevinkt_ingredient_weer_open`, `test_los_recept_toevoegen_haalt_de_uitsluiting_van_zijn_ingredient_weg`, `test_afvinken_en_opnieuw_toevoegen_is_gewoon_een_rondje`, `test_weggehaalde_regel_komt_terug_door_het_recept_opnieuw_toe_te_voegen`) — hun nieuwe tegenhangers staan hierboven. `test_handmatig_item_opnieuw_toevoegen_na_afvinken_staat_weer_open` blijft, met `row['amount'] == 2` (alleen het nieuwe). De module-docstring beschrijft de nieuwe regel. Pas de docstring van `tests/test_toevoeg_gebaren.py` aan.

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider`
Expected: groen, behalve eventueel bewerken/samenvoegen (Taak 6 en 7).

- [ ] **Step 5: Commit**

```bash
git add weekmenu tests
git commit -m "Toevoegen zet alleen het nieuwe op de lijst

Plannen, + Recept, + Los item en week opslaan wissen niets meer. In week
40 gaf chili voor 12 naast gekochte chili voor 2 nog 7 blik kidneybonen
en 1600 g gehakt; nu 6 blik en 1200 g. Een los recept kan opgaan in het
weekmenu ('zelfde maaltijd'), alleen binnen dezelfde week."
```

---

### Task 6: Recept bewerken — gekocht is gekocht

**Files:**
- Modify: `weekmenu/services/shopping.py` (`weken_van_recept`, `momentopname`)
- Modify: `weekmenu/routes/recipes.py` (`edit_recipe`, `_lees_ingredient_rijen`, `_laat_de_geplande_weken_kloppen`)
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`

**Interfaces:**
- Produces: `weken_van_recept(recipe) -> set[(j, w)]`; `momentopname(recipe) -> {'ingredienten': set[int], 'nodig': {(j, w): dict[(ing, eenheid)] -> float}}`

- [ ] **Step 1: Failing tests** (helper `_post_edit` uit `tests/test_toevoeg_gebaren.py` overnemen, met eenheid per regel)

```python
def _bewerk(client, r, regels):
    return client.post(f'/recipe/{r.id}/edit', data={
        'name': r.name, 'page': '', 'serves': str(r.serves), 'cookbook': '', 'url': '',
        'instructions': '', 'ingredient[]': [n for n, _, _ in regels],
        'ingredient_id[]': ['' for _ in regels], 'amount[]': [str(h) for _, h, _ in regels],
        'unit[]': [u for _, _, u in regels], 'category[]': ['overig' for _ in regels],
        'preparation[]': ['' for _ in regels], 'pantry_flag[]': ['0' for _ in regels]})


def test_meer_van_een_gekocht_ingredient_zet_niets_op_de_lijst(app, client):
    r = _recept('Patatje', [('aardappelen', 1000, 'g')])
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')
    _bewerk(client, r, [('aardappelen', 1500, 'g')])
    assert _open('aardappelen') == 0


def test_half_gekocht_groeit_alleen_het_open_deel_mee(app, client):
    r = _chili()
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')
    _plan(r, 12, dag=6)
    _bewerk(client, r, [('kidneybonen', 1.5, 'blik'), ('rundergehakt', 200, 'g')])
    assert _open('kidneybonen') == 9


def test_een_nieuw_ingredient_verschijnt_ook_als_een_ander_recept_het_al_kocht(app, client):
    soep = _recept('Soep', [('ui', 1, 'stuks')])
    chili = _chili()
    _plan(soep, 2)
    _plan(chili, 2, dag=3)
    client.post('/api/boodschappen/check-all')
    _bewerk(client, chili, [('kidneybonen', 1, 'blik'), ('rundergehakt', 200, 'g'),
                            ('ui', 1, 'stuks')])
    assert _open('ui') == 1
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py -k "gekocht or half or nieuw_ingredient"`
Expected: de eerste twee FAIL (extra komt open), de derde PASS (lopende week wordt overgeslagen).

- [ ] **Step 3: Implementatie**

`weekmenu/services/shopping.py`:
```python
def weken_van_recept(recipe):
    """De weken waarin dit recept boodschappen levert."""
    weken = {(mi.year, mi.week_number) for mi in
             MenuItem.query.filter_by(recipe_id=recipe.id).all() if not mi.skip_shopping_list}
    weken |= {(qi.year, qi.week_number) for qi in
              QuickAddItem.query.filter_by(recipe_id=recipe.id).all()}
    return weken


def momentopname(recipe):
    """Wat de weken van dit recept nodig hadden, vlak voor een bewerking."""
    omr = omrekening()
    return {'ingredienten': {ri.ingredient_id for ri in recipe.ingredients},
            'nodig': {wk: week_nodig(wk[0], wk[1], omr)[0] for wk in weken_van_recept(recipe)}}
```
`weekmenu/routes/recipes.py`: in `edit_recipe`, naast `nog_open = lopende_weken()`: `voor = momentopname(recipe)` (vóór het verwijderen van de regels); `_lees_ingredient_rijen(recipe, nog_open, voor)` geeft `voor` door aan `_laat_de_geplande_weken_kloppen(recipe, nog_open, voor)`:
```python
def _laat_de_geplande_weken_kloppen(recipe, nog_open=None, voor=None):
    """Een gewijzigd recept zet niets extra op de lijst van wat al gekocht is.

    Rutger, 4 okt 2026: 'alleen ingrediënten toevoegen als ik iets op het menu
    plan', en gekocht is gekocht, ook als hij het recept groter maakt. In een
    lopende week groeit het al afgehandelde deel daarom naar rato mee; een
    ingredient dat nieuw in het recept komt staat gewoon open. Een week die
    geweest is gaat dicht.
    """
    weken = weken_van_recept(recipe)
    if not weken:
        return
    if nog_open is None:
        nog_open = lopende_weken()
    omr = omrekening()
    for wk in weken:
        if wk not in nog_open:
            for ri in recipe.ingredients:
                afgehandeld.sluit_af(wk[0], wk[1], ri.ingredient_id)
            continue
        if voor is None:
            continue
        oud = voor['nodig'].get(wk, {})
        for (ing, eenheid), hoeveel in week_nodig(wk[0], wk[1], omr)[0].items():
            if ing in voor['ingredienten']:
                afgehandeld.groei_mee(wk[0], wk[1], ing, eenheid,
                                      hoeveel - oud.get((ing, eenheid), 0),
                                      oud.get((ing, eenheid), 0))
    db.session.commit()
```
(Imports: `from weekmenu.services import afgehandeld`; `from weekmenu.services.shopping import lopende_weken, momentopname, omrekening, week_nodig, weken_van_recept`.)

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py tests/test_toevoeg_gebaren.py`
Expected: groen, inclusief `test_recept_bewerken_laat_een_afgeronde_week_dicht` en de voorraadtests.

- [ ] **Step 5: Commit**

```bash
git add weekmenu tests
git commit -m "Recept bewerken: gekocht is gekocht, ook bij meer

Het al afgehandelde deel groeit naar rato mee; een nieuw ingredient staat
gewoon open. Half gekochte chili met 50% meer bonen: dinsdag blijft
gekocht, de chili voor 12 gaat van 6 naar 9 blik."
```

---

### Task 7: Varianten samenvoegen telt vinkjes op

**Files:**
- Modify: `weekmenu/services/ingredienten.py` (`voeg_samen`, `_wis_weekbesluiten`)
- Modify: `tests/test_ingredient_varianten.py:812-825`
- Test: `tests/test_ingredient_varianten.py`

**Interfaces:**
- Consumes: `afgehandeld.lees/ALLES`, `shopping.week_nodig`

- [ ] **Step 1: Failing test aanpassen**

`test_het_vinkje_van_de_winnaar_vervalt_als_de_verliezer_nog_open_stond` wordt:
```python
def test_het_vinkje_van_de_winnaar_blijft_en_alleen_het_deel_van_de_verliezer_staat_open(app):
    """Gekocht is gekocht: het vinkje van de winnaar blijft; het deel van de
    verliezer dat nog open stond, staat na het samenvoegen open."""
    winnaar, verliezer = _knoflookpaar()
    _twee_recepten_in_het_menu(winnaar, verliezer)
    jaar, week = _week_van(VANDAAG)
    db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=winnaar.id))
    db.session.commit()
    nodig_winnaar = sum(week_nodig(jaar, week)[0][k] for k in week_nodig(jaar, week)[0]
                        if k[0] == winnaar.id)

    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingCheck.query.count() == 1
    rij = next(x for x in build_combined_shopping_list(today=VANDAAG)['open']
               if x['name'] == 'Knoflook')
    totaal = sum(week_nodig(jaar, week)[0].values())
    assert round(rij['amount'], 6) == round(totaal - nodig_winnaar, 6)
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_ingredient_varianten.py -k "vinkje or afvinkje"`
Expected: FAIL op de aangepaste test (vinkje van de winnaar wordt nu weggegooid).

- [ ] **Step 3: Implementatie**

In `voeg_samen`, direct na `_bevries_eenheden(...)` + `db.session.flush()` en vóór `_verhuis_receptregels`:
```python
        # Vinkjes zonder getal ('alles') eerst omzetten naar wat er die week
        # nodig was, zolang verliezer en winnaar nog apart te tellen zijn.
        _maak_vinkjes_concreet((verliezer_id, winnaar_id))
```
```python
def _maak_vinkjes_concreet(ingredient_ids):
    from weekmenu.services.afgehandeld import ALLES, lees
    from weekmenu.services.shopping import omrekening, week_nodig
    omr = omrekening()
    for rij in ShoppingCheck.query.filter(ShoppingCheck.ingredient_id.in_(ingredient_ids)).all():
        if lees(rij) is ALLES:
            nodig = week_nodig(rij.year, rij.week_number, omr)[0]
            rij.hoeveelheden = json.dumps({u: h for (i, u), h in nodig.items()
                                           if i == rij.ingredient_id})
```
`_wis_weekbesluiten` wordt (✕ en overrides van de verliezer gaan weg zoals nu; vinkjes zijn een feit en worden opgeteld; een leeg vinkje is een overblijfsel):
```python
def _wis_weekbesluiten(verliezer_id, winnaar_id):
    """Besluiten gaan over een regel, vinkjes over wat er in de kar ligt.

    Een ✕ of een aantal van de verliezer gaat weg met zijn regel: 'Bosui deze
    week niet nodig' is geen 'Lente-Ui deze week niet nodig', en weggooien laat
    hooguit iets terugkomen dat je al weggeklikt had — dát zie je. Een vinkje
    is een feit: dit ligt al in de kar. Het telt dus op bij dat van de winnaar,
    per eenheid; zo blijft gekocht gekocht en staat alleen het deel open dat
    nog niemand afvinkte.
    """
    for model in _WEEKBESLUITEN:
        model.query.filter_by(ingredient_id=verliezer_id).delete()
    for rij in ShoppingCheck.query.filter_by(ingredient_id=verliezer_id).all():
        per = lees(rij)
        if not per:
            db.session.delete(rij)
            continue
        doel = ShoppingCheck.query.filter_by(year=rij.year, week_number=rij.week_number,
                                             ingredient_id=winnaar_id).first()
        if doel is None:
            rij.ingredient_id = winnaar_id
            continue
        som = dict(lees(doel))
        for eenheid, hoeveel in per.items():
            som[eenheid] = som.get(eenheid, 0) + hoeveel
        doel.hoeveelheden = json.dumps(som)
        doel.checked_at = max(doel.checked_at, rij.checked_at)
        doel.via_ah = bool(doel.via_ah) or bool(rij.via_ah)
        db.session.delete(rij)
```
De aanroep wordt `_wis_weekbesluiten(verliezer_id, winnaar_id)`; `weken_verliezer`/`weken_winnaar` blijven alleen als ze elders in `voeg_samen` nodig zijn (anders weg). Imports: `json`, `from weekmenu.services.afgehandeld import lees`.

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_ingredient_varianten.py tests/test_voorbije_weken.py`
Expected: groen.

- [ ] **Step 5: Commit**

```bash
git add weekmenu/services/ingredienten.py tests/test_ingredient_varianten.py
git commit -m "Samenvoegen telt vinkjes op in plaats van ze weg te gooien

Gekocht is gekocht: het vinkje van de winnaar blijft, en alleen het deel
van de verliezer dat nog open stond verschijnt. Dat vervangt de drie
gevallen die nodig waren zolang een vinkje geen getal had."
```

---

### Task 8: Bestaande vinkjes eenmalig vullen

**Files:**
- Modify: `weekmenu/services/afgehandeld.py` (`vul_hoeveelheden_aan`)
- Modify: `weekmenu/__init__.py` (aanroep na `migrate_db()`)
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py`

**Interfaces:**
- Produces: `vul_hoeveelheden_aan() -> int` (aantal gevulde rijen; 0 zonder vlag)

- [ ] **Step 1: Failing tests**

```python
from weekmenu.models import Settings


def _vlag():
    db.session.add(Settings(key='afgehandeld_vullen', value='1'))
    db.session.commit()


def test_vullen_laat_de_lijst_gelijk_en_toevoegen_zet_daarna_alleen_het_nieuwe_erop(app):
    r = _chili()
    _plan(r, 2)
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK, ingredient_id=_ing('kidneybonen').id))
    db.session.add(ShoppingListExclusion(year=JAAR, week_number=WEEK, ingredient_id=_ing('rundergehakt').id))
    db.session.commit()
    _vlag()
    voor = build_combined_shopping_list()['open']

    assert afgehandeld.vul_hoeveelheden_aan() == 2

    assert build_combined_shopping_list()['open'] == voor
    assert Settings.query.filter_by(key='afgehandeld_vullen').first() is None
    _plan(r, 12, dag=6)
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_vullen_zonder_vlag_doet_niets(app):
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK, ingredient_id=1))
    db.session.commit()
    assert afgehandeld.vul_hoeveelheden_aan() == 0
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES


def test_een_afgesloten_week_verschijnt_na_vullen_niet_in_het_afgevinkt_blok(app):
    r = _chili()
    _plan(r, 2, week=32, jaar=2026)
    db.session.add(ShoppingCheck(year=2026, week_number=32, ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 8, 3, 12)))
    db.session.commit()
    _vlag()
    afgehandeld.vul_hoeveelheden_aan()
    assert not build_combined_shopping_list()['checked']
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py -k vullen`
Expected: FAIL met `AttributeError: ... 'vul_hoeveelheden_aan'`.

- [ ] **Step 3: Implementatie** (`weekmenu/services/afgehandeld.py`)

```python
def vul_hoeveelheden_aan():
    """Eenmalig na v23: elke rij zonder getal krijgt wat er toen nodig was.

    Een rij van voor v23 betekende 'alles' en blijft dat doen tot hij gevuld is:
    de lijst ziet er na het vullen precies zo uit als ervoor. Pas daarna zet een
    toevoeging alleen het nieuwe erop. Een vinkje dekt nodig, een kruisje het
    receptdeel (losse items verborg het nooit). Een rij voor iets wat die week
    niet (meer) nodig is krijgt {}.
    """
    from weekmenu.models import Settings
    from weekmenu.services.shopping import omrekening, week_nodig
    vlag = Settings.query.filter_by(key='afgehandeld_vullen').first()
    if vlag is None:
        return 0
    omr, cache, gevuld = omrekening(), {}, 0
    for model, deel in ((ShoppingCheck, 0), (ShoppingListExclusion, 1)):
        for rij in model.query.filter(model.hoeveelheden.is_(None)).all():
            wk = (rij.year, rij.week_number)
            if wk not in cache:
                cache[wk] = week_nodig(wk[0], wk[1], omr)
            bron = cache[wk][deel]
            _schrijf(rij, {u: h for (i, u), h in bron.items() if i == rij.ingredient_id})
            gevuld += 1
    db.session.delete(vlag)
    db.session.commit()
    return gevuld
```
In `weekmenu/__init__.py`, in `create_app()` na `migrate_db()`:
```python
        # v23 voegde getallen toe aan vinkjes en kruisjes; bestaande rijen
        # krijgen eenmalig wat er toen nodig was (zie services/afgehandeld.py).
        from weekmenu.services.afgehandeld import vul_hoeveelheden_aan
        vul_hoeveelheden_aan()
```

- [ ] **Step 4: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider`
Expected: alles groen.

- [ ] **Step 5: Meten op een kopie van de live-database**

```bash
S=/pool/claude-tmp/claude-1000/-pool-apps-weekmenu/b046cd89-d5de-4d29-b9b0-fb58bd0fcff5/scratchpad
python3 -c "import sqlite3; s=sqlite3.connect('file:/pool/apps/weekmenu/live/data/weekmenu.db?mode=ro', uri=True); d=sqlite3.connect('$S/v23.db'); s.backup(d)"
```
Daarna met `$S/lijst.py` de open lijst bouwen met `main` op een kopie en met deze branch op een kopie (die migreert en vult bij het opstarten). Verwacht: open lijst identiek; afgevinkt-blok alleen nog de laatste 14 dagen; `repro_chili.py` geeft 6 blik en 1200 g.

- [ ] **Step 6: Commit**

```bash
git add weekmenu/services/afgehandeld.py weekmenu/__init__.py tests
git commit -m "Bestaande vinkjes eenmalig vullen met wat er toen nodig was

De lijst ziet er na de overstap hetzelfde uit; pas daarna zet een
toevoeging alleen het nieuwe erop. Gemeten op een kopie van de
live-database: open lijst gelijk, chili-week 6 blik en 1200 g."
```

---

### Task 9: Het scherm — afgevinkt-blok en "zelfde maaltijd?"

**Files:**
- Create: `static/js/zelfde-maaltijd.js`
- Modify: `templates/boodschappen.html` (afgevinkt-blok, scripts, page-data `losseRecepten`), `static/js/boodschappen.js` (`terugzetten`, `addExtra`)
- Modify: `weekmenu/routes/menu.py` (`week_menu`: losse recepten van die week; `receptenplanner`-config), `templates/week_menu.html`, `static/js/week_menu.js`
- Modify: `templates/receptenplanner.html`, `static/js/receptenplanner.js`
- Test: `tests/test_afgevinkt_blijft_afgevinkt.py` (paginadata), browser

- [ ] **Step 1: Failing test voor de paginadata**

```python
def test_de_pagina_geeft_de_losse_recepten_van_die_week_mee(app, client):
    r = _chili()
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    for pad in (f'/week/{JAAR}/{WEEK}', '/boodschappen', '/receptenplanner'):
        html = client.get(pad).get_data(as_text=True)
        assert '"recipe_id": %d' % r.id in html, pad
        assert 'zelfde-maaltijd.js' in html, pad


def test_het_afgevinkt_blok_toont_weggehaald_met_een_terugzetknop(app, client):
    r = _chili()
    _plan(r, 2)
    client.post(f'/api/boodschappen/item/{_ing("rundergehakt").id}/remove')
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'weggehaald' in html and 'terugzetten(' in html
```

- [ ] **Step 2: Run, verwacht FAIL**

Run: `python3 -m pytest -q -p no:cacheprovider tests/test_afgevinkt_blijft_afgevinkt.py -k "pagina or terugzetknop"`
Expected: FAIL.

- [ ] **Step 3: `static/js/zelfde-maaltijd.js`**

```javascript
// Vraag of een recept dat al als los recept op de lijst staat dezelfde maaltijd
// is. Rutger koos (4 okt 2026) voor even vragen: stil overnemen laat een extra
// set wegvallen, stil optellen gaf in week 40 de chili dubbel.
// Geeft een Promise: 'zelfde', 'erbij', of null (Escape/achtergrond = erbij).
function vraagZelfdeMaaltijd(recept, personen) {
    return new Promise(resolve => {
        const achter = document.createElement('div');
        achter.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4';
        achter.innerHTML = `
            <div role="dialog" aria-modal="true" aria-labelledby="zm-titel"
                 class="w-full max-w-sm rounded-lg bg-white p-5 shadow-lg">
                <h2 id="zm-titel" class="text-lg font-bold text-[#2C2C2C]">Is dit dezelfde maaltijd?</h2>
                <p class="mt-2 text-sm text-[#6B6B6B]"></p>
                <div class="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
                    <button data-keuze="erbij" class="rounded border border-[#E8E4DC] px-4 py-2 text-sm">Nee, komt erbij</button>
                    <button data-keuze="zelfde" class="rounded bg-[#2C2C2C] px-4 py-2 text-sm text-white">Ja, zelfde maaltijd</button>
                </div>
            </div>`;
        achter.querySelector('p').textContent =
            `${recept} staat al als los recept voor ${personen} personen op je boodschappenlijst.`;
        const klaar = keuze => {
            document.removeEventListener('keydown', toets);
            achter.remove();
            resolve(keuze);
        };
        const toets = e => { if (e.key === 'Escape') klaar(null); };
        achter.addEventListener('click', e => {
            if (e.target === achter) klaar(null);
            const knop = e.target.closest('[data-keuze]');
            if (knop) klaar(knop.dataset.keuze);
        });
        document.addEventListener('keydown', toets);
        document.body.appendChild(achter);
        achter.querySelector('[data-keuze="zelfde"]').focus();
    });
}

// Het losse recept van deze week voor dit recept, of undefined.
function losRecept(losseRecepten, recipeId, jaar, week) {
    return (losseRecepten || []).find(q =>
        q.recipe_id === Number(recipeId) && q.year === jaar && q.week === week);
}
```

- [ ] **Step 4: Aansluiten op de drie schermen**

`templates/boodschappen.html`: page-data krijgt `"losseRecepten": {{ losse_recepten_json | safe }}`; `<script src="{{ url_for('static', filename='js/zelfde-maaltijd.js') }}"></script>` vóór `boodschappen.js`. Het afgevinkt-blok:
```html
{% for item in checked_items %}
<div class="flex items-center gap-2 py-2 border-b border-[#E8E4DC]">
    {% if item.soort == 'afgevinkt' %}
    <input type="checkbox" checked class="cursor-pointer shrink-0"
           onchange="checkItem({{ item.ingredient_id }}, this.checked)">
    {% endif %}
    <span class="text-sm line-through text-[#9CA3AF]">
        {{ item.amount_display }}{% if item.unit %} {{ item.unit }}{% endif %} {{ item.name }}
        {% if item.recipes %}· {{ item.recipes | join(', ') }}{% endif %}
    </span>
    {% if item.soort == 'weggehaald' %}
    <span class="bg-[#F3F0EA] text-[#6B6B6B] rounded-full px-2 text-xs">weggehaald</span>
    <button onclick="terugzetten({{ item.ingredient_id }})"
            class="ml-auto text-xs underline text-[#2C2C2C]">Terugzetten</button>
    {% elif item.via_ah %}
    <span class="bg-green-100 text-green-800 rounded-full px-2 text-xs">via AH</span>
    {% endif %}
</div>
{% endfor %}
```
`static/js/boodschappen.js`:
```javascript
async function terugzetten(ingredientId) {
    const resp = await fetch(`/api/boodschappen/item/${ingredientId}/terugzetten`, { method: 'POST' });
    if (resp.ok) location.reload();
}
```
In `addExtra()`, na het bepalen van `recipeId` en `people`:
```javascript
    let erbij = false;
    const los = losRecept(_pageData.losseRecepten, recipeId, _pageData.year, _pageData.week);
    if (los) {
        const naam = RECIPES.find(r => r.id === recipeId)?.name || 'Dit recept';
        erbij = (await vraagZelfdeMaaltijd(naam, los.people_count)) !== 'zelfde';
    }
```
en `body: JSON.stringify({ recipe_id: recipeId, people_count: people, erbij })`.

`weekmenu/routes/menu.py::week_menu`: geef `losse_recepten` mee (QuickAddItems van die week: `[{'id', 'recipe_id', 'people_count', 'year', 'week'}]`); `templates/week_menu.html` page-data krijgt `"losseRecepten": {{ losse_recepten | tojson }}` en het script `zelfde-maaltijd.js` vóór `week_menu.js`. In `static/js/week_menu.js`:
```javascript
const teOvernemen = new Set();

// Een recept in een vak gezet: staat het al als los recept op de lijst, vraag dan.
async function vraagBijLosRecept(recipeId, naam) {
    const los = losRecept(_pageData.losseRecepten, recipeId, _pageData.year, _pageData.week);
    if (!los || teOvernemen.has(los.id)) return;
    if ((await vraagZelfdeMaaltijd(naam, los.people_count)) === 'zelfde') teOvernemen.add(los.id);
}
```
In beide plekken waar een vak een recept krijgt (de klik op `.recipe-option` en de `.meal-select-btn`), vóór `debouncedUpdate()`: `await vraagBijLosRecept(recipeId, recipeName)` (maak de handlers `async`). In `updateMenu` gaat `neem_los_recept_over: [...teOvernemen]` mee in de body; na `response.ok`: haal die ids uit `_pageData.losseRecepten` en `teOvernemen.clear()`.

`templates/receptenplanner.html`: `planner-config` krijgt `'losse_recepten': losse_recepten` (alle QuickAddItems van lopende weken, zelfde vorm) en het script `zelfde-maaltijd.js`. In `static/js/receptenplanner.js`, vóór de `fetch('/api/planner/plan', …)`:
```javascript
  const los = losRecept(_plannerCfg.losse_recepten, active.id, payload.year, payload.week);
  if (los && (await vraagZelfdeMaaltijd(active.name, los.people_count)) === 'zelfde') {
    payload.neem_los_recept_over = [los.id];
  }
```

- [ ] **Step 5: Run, verwacht PASS**

Run: `python3 -m pytest -q -p no:cacheprovider`
Expected: alles groen.

- [ ] **Step 6: Browsercontrole op dev** (vereist een werkende browser: Chrome-extensie of de systeembibliotheken voor de headless Chromium)

Dev herbouwen (`docker compose -p weekmenu-dev -f docker-compose.dev.yml up -d --build weekmenu-dev`), dan op `http://localhost:5002`, op 390 px én desktopbreedte, met screenshots en console:
1. Recept plannen, alles afvinken, "+ Recept" hetzelfde recept → venster verschijnt; "Nee, komt erbij" → tweede los recept; "Ja" → aantal aangepast.
2. Weekmenu: los recept van deze week in een vak zetten → venster; "Ja" → het losse recept verdwijnt van /boodschappen, lijst niet dubbel.
3. Receptenplanner: zelfde via de popup.
4. ✕ op een regel → staat in het afgevinkt-blok als "weggehaald"; "Terugzetten" → terug op de lijst.
5. Console zonder fouten; venster sluit met Escape en de achtergrond.

- [ ] **Step 7: Commit**

```bash
git add static templates weekmenu tests
git commit -m "Scherm: weggehaalde regels terugzetten, en vragen bij een los recept

Het afgevinkt-blok toont ook wat je wegklikte, met een knop om het terug
te zetten. Kies je een recept dat al als los recept op de lijst staat,
dan vraagt het weekmenu, de receptenplanner en + Recept of het dezelfde
maaltijd is."
```

---

### Task 10: Versie, documentatie, afronding

**Files:**
- Modify: `weekmenu/__init__.py` (`__version__ = '0.9.0-beta'`)
- Modify: `CLAUDE.md` (v1..v23; `services/afgehandeld.py` in de lijst; `services/shopping.py`-regel; versie)

- [ ] **Step 1: Versie en CLAUDE.md bijwerken**

CLAUDE.md: `migrations.py   # v1..v23`, `22 versies` → `23 versies`, `0.8.2-beta` → `0.9.0-beta`, en onder "Services die de kern dragen":
`- services/afgehandeld.py: wat er per week per ingredient al afgevinkt of weggehaald is, als hoeveelheid (NULL = alles). De lijst rekent open = nodig − afgevinkt − weggehaald; toevoegen raakt dit nooit aan.`

- [ ] **Step 2: Volledige suite + meting**

Run: `python3 -m pytest -q -p no:cacheprovider` → alles groen.
Run de meting uit Taak 8 Step 5 opnieuw op een verse kopie van de live-database.

- [ ] **Step 3: Commit**

```bash
git add weekmenu/__init__.py CLAUDE.md
git commit -m "Versie 0.9.0-beta: afgevinkt blijft afgevinkt"
```

- [ ] **Step 4: Live alleen na Rutgers akkoord**

Back-up van de live-database in de scratchpad (sha256), `main` bijwerken met deze branch, live herbouwen, dan versie, schema 23, logs, `vul_hoeveelheden_aan` in de opstartlog, `/boodschappen` op live controleren.
