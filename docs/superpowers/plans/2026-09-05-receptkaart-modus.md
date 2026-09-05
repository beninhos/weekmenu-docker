# Receptkaart-modus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Twee gescande pagina's van een maaltijdbox-kaart worden één concept, met de ingrediëntentabel als bron van de hoeveelheden en elke afwijking zichtbaar op de nakijkkaart.

**Architecture:** De batch krijgt een modus-vlag (`DumpJob.mode`). In kaartmodus houdt `lees_paginas_met_annotaties` de Vision-annotaties vast; `services/tabel.py` reconstrueert de tabelrijen uit de woordcoördinaten; `services/kaart.py` paart de pagina's, bouwt de modelinvoer en controleert het antwoord tegen de tabel; `services/dump.py` knoopt het aan de bestaande pijplijn (ankerknip, `_markeer_twijfels`, drafts). Merkspecifieke herkenning zit alleen in `services/kaartsignaturen.py`.

**Tech Stack:** Python 3.12 / Flask / SQLAlchemy / SQLite, Google Cloud Vision (`fullTextAnnotation` met `boundingBox.vertices`), Gemini via `google.genai`, pytest, vanilla JS in Jinja-templates.

**Spec:** `docs/superpowers/specs/2026-09-05-receptkaart-modus-design.md`

## Global Constraints

- Geen co-author in commits (vaste regel van Rutger).
- Tests groen vóór elke commit: `python3 -m pytest tests/ -q` (nu 240 passed, 1 skipped zonder opencv).
- Elke taak eerst de falende test, dan de code (TDD). Verwachte uitkomsten in tests zijn de waarheid van de kaart; nooit de verwachting aanpassen aan de uitvoer.
- Geen live Vision- of Gemini-aanroepen in tests; mocken zoals in `tests/test_dump_retry.py` (`patch('weekmenu.services.dump.lees_paginas')`, `patch('google.genai.Client')`).
- Vision laat nulwaarden weg in JSON: een vertex zonder `x` betekent `x = 0`.
- Meerdere hoeveelheidkolommen worden herkend en geweigerd, nooit geraden.
- Een paar dat niet klopt levert geen concept op, wél een melding met paginanummers; de rest van de batch gaat door.
- Bestaande tests voor boekmodus mogen niet van gedrag veranderen (`tests/test_ankers.py`, `tests/test_dump_retry.py`, `tests/test_ocr_twijfel.py`, `tests/test_import_vertrouwen.py`).
- Commit-boodschappen in het Nederlands, in de stijl van `git log`: één regel wat, daarna waarom.

---

## Voortgang

- Taak 4 (signaturen) — **klaar**, f8ae7d3. Afwijking: `voorkant` is `\bHELLO[\s\S]{0,80}?FRESH\b`, hoofdlettergevoelig, omdat de OCR de titel tussen HELLO en FRESH zet.
- Taak 5 + 6 (tabel) — **klaar, go/no-go gehaald**, 015b993: 15/15 rijen op de echte kaart. Het algoritme wijkt af van de plantekst hieronder (die is niet bijgewerkt; `weekmenu/services/tabel.py` en `tests/test_tabel.py` zijn de waarheid): banden op overlap met de bandkern (gemiddeld midden ± halve mediaanhoogte, `_BAND_FACTOR = 0.2`); een band valt in *segmenten* bij elk groot gat, een rij is 'letters | korte cel met getal'; **twee passen** — eerst grof de hoeveelheidkolom (x met de meeste rijen, `_KOLOM_FACTOR = 2.5`), dan alleen de strook tot die kolom opnieuw in banden, want de stapkolommen ernaast hebben een eigen regelhoogte; meerdere kolommen = ≥ 3 rijen met rechts van de cel nóg een korte cel met getal. Interface ongewijzigd: `tabelrijen(annotation) -> (rijen, reden)`.
- Taak 1–3, 7–14 — nog te doen, in die volgorde (1–3 hebben geen afhankelijkheid op 4–6).

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid |
|---|---|
| `weekmenu/migrations.py` | `_migrate_v16`: vier nieuwe kolommen |
| `weekmenu/models.py` | `DumpJob.mode`, `Recipe.prep_time`, `RecipeDraft.prep_time`, `RecipeDraft.back_image_path` |
| `weekmenu/routes/recipes.py`, `templates/new_recipe.html`, `templates/edit_recipe.html`, `templates/_recipe_detail_modal.html` | bereidingstijd in formulier en weergave |
| `weekmenu/routes/dump.py`, `templates/dump.html` | modus-keuze bij upload; `prep_time`, achterkant en voorraad op de nakijkkaart |
| `weekmenu/services/kaartsignaturen.py` (nieuw) | per merk: voorkant, voorraadkop, bereidingstijd, benodigdheden |
| `weekmenu/services/tabel.py` (nieuw) | woordboxen → rijen → cellen → `tabelrijen(annotation)` |
| `weekmenu/services/ocr.py` | `lees_paginas_met_annotaties` |
| `weekmenu/services/kaart.py` (nieuw) | paren, modelinvoer, tabelregels strippen, controle tegen de tabel, benodigdheden |
| `weekmenu/services/dump.py` | `_KAART_PROMPT`, `standaard_pagina`, `_verwerk_kaarten`, vangnet, drafts met `prep_time`/`back_image_path` |
| `tests/test_prep_time.py`, `tests/test_kaartsignaturen.py`, `tests/test_tabel.py`, `tests/test_kaart.py`, `tests/test_kaart_pijplijn.py`, `tests/fixtures/hellofresh_achterkant.json` | tests en fixture |
| `/pool/apps/weekmenu-cloudvision/data/benchmark-import/proef2/acceptatie_kaart.py` (buiten de repo, gitignored) | meetlat |

---

### Task 1: Migratie en modelvelden

**Files:**
- Modify: `weekmenu/migrations.py` (na `_migrate_v15`, en in `migrate_db`)
- Modify: `weekmenu/models.py` (`Recipe`, `DumpJob`, `RecipeDraft`)
- Test: `tests/test_prep_time.py`

**Interfaces:**
- Produces: `DumpJob.mode` (String(10), default `'boek'`), `Recipe.prep_time` (Integer, nullable), `RecipeDraft.prep_time` (Integer, nullable), `RecipeDraft.back_image_path` (String(200), nullable); `_migrate_v16(conn)`.

- [ ] **Step 1: Schrijf de falende tests**

```python
# tests/test_prep_time.py
"""Bereidingstijd bestaat als veld, en de kaartmodus heeft zijn kolommen."""
from sqlalchemy import create_engine, text

from weekmenu.extensions import db
from weekmenu.models import DumpJob, Recipe, RecipeDraft


def test_migratie_v16_voegt_kolommen_toe_aan_oude_tabellen():
    from weekmenu.migrations import _migrate_v16
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(text('CREATE TABLE dump_job (id VARCHAR(36) PRIMARY KEY, status VARCHAR(20))'))
        conn.execute(text('CREATE TABLE recipe (id INTEGER PRIMARY KEY, name VARCHAR(100))'))
        conn.execute(text('CREATE TABLE recipe_draft (id INTEGER PRIMARY KEY, name VARCHAR(100))'))
        conn.execute(text("INSERT INTO dump_job (id, status) VALUES ('j', 'done')"))
        _migrate_v16(conn)
        _migrate_v16(conn)  # idempotent
        kolommen = {t: [r[1] for r in conn.execute(text(f'PRAGMA table_info({t})')).fetchall()]
                    for t in ('dump_job', 'recipe', 'recipe_draft')}
        assert 'mode' in kolommen['dump_job']
        assert 'prep_time' in kolommen['recipe']
        assert 'prep_time' in kolommen['recipe_draft']
        assert 'back_image_path' in kolommen['recipe_draft']
        assert conn.execute(text("SELECT mode FROM dump_job WHERE id = 'j'")).scalar() == 'boek'


def test_modelvelden_bestaan(app):
    db.session.add(DumpJob(id='k', status='done', mode='kaart'))
    r = Recipe(name='Kaart', prep_time=40)
    db.session.add(r)
    db.session.flush()
    d = RecipeDraft(job_id='k', name='Kaart', prep_time=40, back_image_path='static/uploads/x.jpg')
    db.session.add(d)
    db.session.commit()
    assert DumpJob.query.get('k').mode == 'kaart'
    db.session.add(DumpJob(id='l', status='done'))
    db.session.commit()
    assert DumpJob.query.get('l').mode == 'boek'
    assert Recipe.query.get(r.id).prep_time == 40
    assert RecipeDraft.query.get(d.id).back_image_path == 'static/uploads/x.jpg'
```

- [ ] **Step 2: Draai de tests, zie ze falen**

Run: `python3 -m pytest tests/test_prep_time.py -q`
Expected: FAIL — `ImportError: cannot import name '_migrate_v16'` en `TypeError: 'mode' is an invalid keyword argument`.

- [ ] **Step 3: Migratie schrijven**

In `weekmenu/migrations.py`, direct na `_migrate_v15`:

```python
def _migrate_v16(conn):
    """Receptkaart-modus en bereidingstijd.

    `dump_job.mode` zegt of een batch kookboekpagina's ('boek') of
    receptkaarten ('kaart', twee pagina's per recept) bevat; de vlag staat op
    de job omdat een retry in een achtergrondthread draait zonder request.
    `prep_time` wordt al jaren aan het model gevraagd maar bestond nergens.
    `back_image_path` is de achterkant van een kaart, alleen voor de
    nakijkkaart: daar staan de hoeveelheden die je wilt controleren.
    """
    for tabel, kolommen in [
        ('dump_job', [('mode', "VARCHAR(10) DEFAULT 'boek'")]),
        ('recipe', [('prep_time', 'INTEGER')]),
        ('recipe_draft', [('prep_time', 'INTEGER'), ('back_image_path', 'VARCHAR(200)')]),
    ]:
        cols = [row[1] for row in conn.execute(text(f'PRAGMA table_info({tabel})')).fetchall()]
        for col, col_def in kolommen:
            if col not in cols:
                try:
                    conn.execute(text(f'ALTER TABLE {tabel} ADD COLUMN {col} {col_def}'))
                except OperationalError:
                    pass
```

In `migrate_db`: na `if current < 15: _migrate_v15(conn)` toevoegen:

```python
        if current < 16:
            _migrate_v16(conn)
```

en `target = 15` wordt `target = 16`.

- [ ] **Step 4: Modelvelden**

In `weekmenu/models.py`:

- `Recipe`: na `instructions = db.Column(db.Text, nullable=True)`:
  ```python
      prep_time = db.Column(db.Integer, nullable=True)  # bereidingstijd in minuten
  ```
- `DumpJob`: na `warning = db.Column(db.Text, nullable=True)`:
  ```python
      # 'boek' (één pagina = één recept) of 'kaart' (twee pagina's = één recept).
      mode = db.Column(db.String(10), nullable=False, default='boek')
  ```
- `RecipeDraft`: na `original_image_path = ...`:
  ```python
      back_image_path = db.Column(db.String(200), nullable=True)  # achterkant van een kaart
      prep_time = db.Column(db.Integer, nullable=True)
  ```

- [ ] **Step 5: Tests groen**

Run: `python3 -m pytest tests/test_prep_time.py tests/ -q`
Expected: alle groen, 2 nieuwe.

- [ ] **Step 6: Commit**

```bash
git add weekmenu/migrations.py weekmenu/models.py tests/test_prep_time.py
git commit -m "Kolommen voor receptkaart-modus en bereidingstijd

dump_job.mode, recipe.prep_time, recipe_draft.prep_time en
recipe_draft.back_image_path, via een idempotente migratie (v16)."
```

---

### Task 2: Bereidingstijd in formulier, weergave en concept

**Files:**
- Modify: `weekmenu/routes/recipes.py` (`serialize_recipe`, POST nieuw recept rond regel 326, POST bewerken rond regel 405)
- Modify: `weekmenu/routes/dump.py` (`serialize_draft`, `dump_draft_accept`)
- Modify: `templates/new_recipe.html`, `templates/edit_recipe.html`, `templates/_recipe_detail_modal.html`
- Test: `tests/test_prep_time.py` (uitbreiden)

**Interfaces:**
- Consumes: Task 1.
- Produces: formulierveld `prep_time` (minuten, leeg = None); `serialize_recipe(...)['prep_time']`; `serialize_draft(...)['prep_time']`; accepteren kopieert `RecipeDraft.prep_time` naar `Recipe.prep_time`.

- [ ] **Step 1: Falende tests**

Voeg toe aan `tests/test_prep_time.py`:

```python
import json


def test_nieuw_recept_bewaart_bereidingstijd(app, client):
    resp = client.post('/recipe/new', data={'name': 'Snel', 'serves': '2', 'page': '',
                                            'prep_time': '40'})
    assert resp.status_code == 302
    assert Recipe.query.filter_by(name='Snel').first().prep_time == 40


def test_lege_of_onzinnige_bereidingstijd_wordt_none(app, client):
    client.post('/recipe/new', data={'name': 'Leeg', 'serves': '', 'page': '', 'prep_time': ''})
    client.post('/recipe/new', data={'name': 'Tekst', 'serves': '', 'page': '', 'prep_time': 'lang'})
    assert Recipe.query.filter_by(name='Leeg').first().prep_time is None
    assert Recipe.query.filter_by(name='Tekst').first().prep_time is None


def test_bewerken_wijzigt_bereidingstijd(app, client):
    r = Recipe(name='Oud', prep_time=10)
    db.session.add(r)
    db.session.commit()
    client.post(f'/recipe/{r.id}/edit', data={'name': 'Oud', 'serves': '', 'page': '',
                                               'prep_time': '25'})
    assert Recipe.query.get(r.id).prep_time == 25


def test_accepteren_neemt_bereidingstijd_over(app, client):
    db.session.add(DumpJob(id='p', status='done'))
    d = RecipeDraft(job_id='p', name='Kaart', prep_time=35, instructions='Stap 1.',
                    ingredients_json=json.dumps([{'name': 'ui', 'amount': 1, 'unit': 'stuks'}]))
    db.session.add(d)
    db.session.commit()
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})
    assert resp.status_code == 200
    assert Recipe.query.get(resp.get_json()['recipe_id']).prep_time == 35


def test_serialize_draft_en_recipe_geven_prep_time(app, client):
    from weekmenu.routes.dump import serialize_draft
    from weekmenu.routes.recipes import serialize_recipe
    db.session.add(DumpJob(id='q', status='done'))
    d = RecipeDraft(job_id='q', name='K', prep_time=15, back_image_path='static/uploads/b.jpg')
    r = Recipe(name='R', prep_time=20)
    db.session.add_all([d, r])
    db.session.commit()
    assert serialize_draft(d)['prep_time'] == 15
    assert serialize_draft(d)['back_image_path'] == 'static/uploads/b.jpg'
    assert serialize_recipe(r)['prep_time'] == 20
```

- [ ] **Step 2: Zie ze falen**

Run: `python3 -m pytest tests/test_prep_time.py -q`
Expected: 5 FAIL (`prep_time` blijft None, KeyError op `'prep_time'`).

- [ ] **Step 3: Routes**

`weekmenu/routes/recipes.py`:

- Helper bovenin (na de imports):
  ```python
  def _minuten(waarde):
      """Bereidingstijd uit het formulier: heel getal, anders None."""
      waarde = (waarde or '').strip()
      return int(waarde) if waarde.isdigit() else None
  ```
- `serialize_recipe`: voeg `'prep_time': r.prep_time,` toe naast `'serves'`.
- POST nieuw recept: in `Recipe(...)` toevoegen `prep_time=_minuten(request.form.get('prep_time')),`.
- POST bewerken: na `recipe.serves = ...` toevoegen `recipe.prep_time = _minuten(request.form.get('prep_time'))`.

`weekmenu/routes/dump.py`:

- `serialize_draft`: toevoegen `'prep_time': d.prep_time,` en `'back_image_path': d.back_image_path,`.
- `dump_draft_accept`: in `Recipe(...)` toevoegen `prep_time=d.prep_time,`.

- [ ] **Step 4: Templates**

`templates/new_recipe.html`, direct na het `<div>` van "Standaard aantal personen":

```html
        <div>
            <label class="block text-sm font-semibold text-[#2C2C2C]">Bereidingstijd (min.)</label>
            <input type="number" name="prep_time" id="fieldPrepTime" min="1" max="600"
                   class="mt-1 block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
```

Op de drie plekken in `new_recipe.html` waar `if (data.serves) document.getElementById('fieldServes').value = data.serves;` staat (foto-import, link-import, concept-prefill), direct daaronder:

```js
        if (data.prep_time) document.getElementById('fieldPrepTime').value = data.prep_time;
```

`templates/edit_recipe.html`, na het serves-veld:

```html
        <div>
            <label class="block text-sm font-semibold text-[#2C2C2C]">Bereidingstijd (min.)</label>
            <input type="number" name="prep_time" value="{{ recipe.prep_time or '' }}" min="1" max="600"
                   class="mt-1 block w-full rounded-md border-[#D4CEC4] shadow-sm">
        </div>
```

`templates/_recipe_detail_modal.html`, naast `<span id="dp-serves" ...>`:

```html
      <span id="dp-prep-time" class="bg-[#F5F2ED] text-[#8B4513] rounded-full px-2 py-0.5 text-xs font-medium hidden"></span>
```

En in het JS dat `dp-serves` vult (zoek `dp-serves` in dezelfde template of in `static/js/`): daaronder

```js
const pt = document.getElementById('dp-prep-time');
pt.textContent = r.prep_time ? `⏱ ${r.prep_time} min` : '';
pt.classList.toggle('hidden', !r.prep_time);
```

- [ ] **Step 5: Tests groen**

Run: `python3 -m pytest tests/ -q`
Expected: alle groen.

- [ ] **Step 6: Commit**

```bash
git add weekmenu/routes/recipes.py weekmenu/routes/dump.py templates/new_recipe.html templates/edit_recipe.html templates/_recipe_detail_modal.html tests/test_prep_time.py
git commit -m "Bereidingstijd als veld op recept en concept

Het model gaf prep_time al terug bij foto- en linkimport, maar er was
nergens een plek om hem te bewaren."
```

---

### Task 3: Modus-vlag door de upload heen

**Files:**
- Modify: `weekmenu/services/dump.py` (`start_dump_job`)
- Modify: `weekmenu/routes/dump.py` (`dump_upload`, `dump_share`)
- Modify: `templates/dump.html` (keuze naast `cookbookSelect`, `startUpload`)
- Test: `tests/test_kaart_pijplijn.py` (nieuw)

**Interfaces:**
- Produces: `start_dump_job(files, mode='boek') -> job_id`; `DumpJob.mode` gezet; `<select id="scanMode">` met waarden `boek`/`kaart`; formulierveld `mode` op `/dump/upload`.

- [ ] **Step 1: Falende test**

```python
# tests/test_kaart_pijplijn.py
"""Receptkaart-modus: van upload tot concept."""
import io
import json
from unittest.mock import patch

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft


def _upload(client, mode=None):
    data = {'files': (io.BytesIO(b'\xff\xd8\xff'), 'a.jpg', 'image/jpeg')}
    if mode:
        data['mode'] = mode
    with patch('weekmenu.services.dump._start_thread'):
        return client.post('/dump/upload', data=data, content_type='multipart/form-data')


def test_upload_zonder_modus_is_boek(app, client):
    resp = _upload(client)
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'boek'


def test_upload_met_kaartmodus_zet_vlag_op_de_job(app, client):
    resp = _upload(client, 'kaart')
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'kaart'


def test_onbekende_modus_wordt_boek(app, client):
    resp = _upload(client, 'iets')
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'boek'
```

- [ ] **Step 2: Zie falen**

Run: `python3 -m pytest tests/test_kaart_pijplijn.py -q`
Expected: `test_upload_zonder_modus_is_boek` en `test_onbekende_modus_wordt_boek` PASS (de kolom bestaat al met default `'boek'`), `test_upload_met_kaartmodus_zet_vlag_op_de_job` FAIL op `'boek' != 'kaart'` — de route geeft `mode` nog niet door.

- [ ] **Step 3: Service en routes**

`weekmenu/services/dump.py`, `start_dump_job`:

```python
def start_dump_job(files, mode='boek'):
    """Sla uploads op, maak een DumpJob en start de verwerkingsthread. Returns job_id.

    `mode` is 'boek' (één pagina = één recept) of 'kaart' (twee pagina's =
    één recept). Alles anders wordt 'boek': liever een batch te veel als
    kookboek dan een stil verkeerde koppeling.
    """
    ...
    job = DumpJob(id=job_id, status='processing', mode='kaart' if mode == 'kaart' else 'boek')
```

`weekmenu/routes/dump.py`:

```python
@bp.route('/dump/upload', methods=['POST'])
def dump_upload():
    files = request.files.getlist('files')
    try:
        job_id = start_dump_job(files, mode=request.form.get('mode', 'boek'))
    ...

def dump_share():
    files = request.files.getlist('files')
    try:
        start_dump_job(files, mode=request.form.get('mode', 'boek'))
```

- [ ] **Step 4: Template**

`templates/dump.html`, in dezelfde regel als de kookboekkeuze (zoek `id="cookbookSelect"`), erna:

```html
        <label class="text-sm ml-4">Soort scan:</label>
        <select id="scanMode" class="border border-[#E8E4DC] rounded px-2 py-1 text-sm">
            <option value="boek">kookboekpagina's</option>
            <option value="kaart">receptkaarten — 2 pagina's per recept</option>
        </select>
```

In `startUpload`, na `Array.from(files).forEach(f => fd.append('files', f));`:

```js
    fd.append('mode', document.getElementById('scanMode').value);
```

- [ ] **Step 5: Tests groen, commit**

Run: `python3 -m pytest tests/ -q` → groen.

```bash
git add weekmenu/services/dump.py weekmenu/routes/dump.py templates/dump.html tests/test_kaart_pijplijn.py
git commit -m "Soort scan kiezen bij het uploaden: kookboek of receptkaarten

De vlag staat op de job, niet in het request: een retry draait in een
achtergrondthread en moet dezelfde keuze zien."
```

---

### Task 4: Merksignaturen

**Files:**
- Create: `weekmenu/services/kaartsignaturen.py`
- Test: `tests/test_kaartsignaturen.py`

**Interfaces:**
- Produces: `is_voorkant(tekst) -> bool`, `is_voorraadkop(regel) -> bool`, `is_benodigdheden_kop(regel) -> bool`, `bereidingstijd(tekst) -> int | None`. Allemaal merkloos bruikbaar: zonder treffer `False`/`None`.

- [ ] **Step 1: Falende test**

```python
# tests/test_kaartsignaturen.py
from weekmenu.services.kaartsignaturen import (bereidingstijd, is_benodigdheden_kop,
                                               is_voorkant, is_voorraadkop)


def test_hellofresh_voorkant():
    assert is_voorkant('HELLO Patatje oorlog met hamburger\nFRESH\nmet zelfgemaakte pindasaus')
    assert is_voorkant('HELLOFRESH\nKip tikka')
    assert not is_voorkant('Ingrediënten voor 2 personen\nHalfkruimige aardappelen')
    assert not is_voorkant('')


def test_voorraadkop_en_benodigdheden():
    assert is_voorraadkop('Zelf toevoegen')
    assert is_voorraadkop('  zelf toevoegen ')
    assert not is_voorraadkop('Zelf toevoegen aan de salade: 1 ui')
    assert is_benodigdheden_kop('Benodigdheden')
    assert not is_benodigdheden_kop('Benodigdheden voor de saus zijn simpel.')


def test_bereidingstijd():
    assert bereidingstijd('Bereidingstijd:40 min. (totaal voor 2 personen)') == 40
    assert bereidingstijd('Bereidingstijd: 25 minuten') == 25
    assert bereidingstijd('Kooktijd onbekend') is None
    assert bereidingstijd(None) is None
```

- [ ] **Step 2: Zie falen** — `ModuleNotFoundError`.

- [ ] **Step 3: Implementatie**

```python
# weekmenu/services/kaartsignaturen.py
"""Wat een receptkaart per merk verraadt.

Alles wat merkspecifiek is aan de kaartmodus staat hier, in één lijst; de
rest (paren, tabelrijen uit geometrie, controle tegen de tabel, ankers over
twee pagina's) is merkloos. Een nieuw merk is een nieuw dict, geen nieuwe
code. Zonder treffer werken alle aanroepers gewoon door: geen bevestiging
van een voorkant, geen voorraadblok, geen bereidingstijd.
"""
import re

MERKEN = [
    {
        'naam': 'HelloFresh',
        'voorkant': re.compile(r'HELLO\s*FRESH', re.IGNORECASE),
        'voorraadkop': re.compile(r'^\s*zelf toevoegen\s*$', re.IGNORECASE),
        'benodigdheden': re.compile(r'^\s*benodigdheden\s*$', re.IGNORECASE),
        'bereidingstijd': re.compile(r'bereidingstijd\s*:?\s*(\d+)\s*min', re.IGNORECASE),
    },
]


def is_voorkant(tekst):
    """Bevat de paginatekst een merklogo dat alleen op de voorkant staat?"""
    return any(m['voorkant'].search(tekst or '') for m in MERKEN)


def is_voorraadkop(regel):
    return any(m['voorraadkop'].match(regel or '') for m in MERKEN)


def is_benodigdheden_kop(regel):
    return any(m['benodigdheden'].match(regel or '') for m in MERKEN)


def bereidingstijd(tekst):
    """Minuten uit 'Bereidingstijd: 40 min.', of None."""
    for m in MERKEN:
        treffer = m['bereidingstijd'].search(tekst or '')
        if treffer:
            return int(treffer.group(1))
    return None
```

- [ ] **Step 4: Groen en commit**

```bash
git add weekmenu/services/kaartsignaturen.py tests/test_kaartsignaturen.py
git commit -m "Merksignaturen voor receptkaarten in één bestand

Alleen wat per merk verschilt staat hier; de kaartmodus zelf is merkloos."
```

---

### Task 5: Woordboxen, rijen en cellen uit de Vision-geometrie

**Files:**
- Create: `weekmenu/services/tabel.py`
- Test: `tests/test_tabel.py`

**Interfaces:**
- Produces: `woordboxen(annotation) -> list[dict]` met sleutels `tekst, x0, x1, y0, y1`; `_rijen(boxen) -> list[list[box]]` (op y gegroepeerd, binnen een rij op x gesorteerd); `_cellen(rij) -> (links: str, rechts: str, gat: float)`; constante `_GAT_FACTOR = 1.5`.

- [ ] **Step 1: Falende tests**

```python
# tests/test_tabel.py
"""Tabelrijen uit de woordcoördinaten van Vision."""
from weekmenu.services.tabel import _cellen, _rijen, woordboxen


def _woord(tekst, x0, y0, breedte=None, hoogte=30):
    breedte = breedte or 14 * len(tekst)
    return {'symbols': [{'text': t} for t in tekst],
            'boundingBox': {'vertices': [{'x': x0, 'y': y0}, {'x': x0 + breedte, 'y': y0},
                                         {'x': x0 + breedte, 'y': y0 + hoogte}, {'x': x0, 'y': y0 + hoogte}]}}


def _annotatie(woorden):
    return {'pages': [{'blocks': [{'paragraphs': [{'words': woorden}]}]}]}


def test_woordboxen_vullen_ontbrekende_nul_aan():
    # Vision laat x=0 of y=0 weg in de JSON.
    w = {'symbols': [{'text': 'A'}],
         'boundingBox': {'vertices': [{'y': 10}, {'x': 20, 'y': 10}, {'x': 20, 'y': 40}, {'y': 40}]}}
    box = woordboxen(_annotatie([w]))[0]
    assert (box['x0'], box['x1'], box['y0'], box['y1']) == (0, 20, 10, 40)
    assert box['tekst'] == 'A'


def test_woorden_zonder_box_worden_overgeslagen():
    assert woordboxen(_annotatie([{'symbols': [{'text': 'x'}]}])) == []


def test_rijen_groeperen_op_y_ook_uit_verschillende_paragrafen():
    # De naam en de hoeveelheid staan in de OCR in verschillende paragrafen,
    # maar op dezelfde hoogte: dat is de hele reden voor deze module.
    ann = {'pages': [{'blocks': [{'paragraphs': [
        {'words': [_woord('Sperziebonen', 100, 500), _woord('Kokosmelk', 100, 560)]},
        {'words': [_woord('200', 600, 503), _woord('g', 660, 503), _woord('100', 600, 562), _woord('ml', 660, 562)]},
    ]}]}]}
    rijen = _rijen(woordboxen(ann))
    assert [[w['tekst'] for w in r] for r in rijen] == [['Sperziebonen', '200', 'g'], ['Kokosmelk', '100', 'ml']]


def test_cellen_splitsen_op_het_grootste_gat():
    rij = sorted(woordboxen(_annotatie([_woord('Halfkruimige', 100, 500), _woord('aardappelen', 280, 500),
                                        _woord('500', 600, 500), _woord('g', 660, 500)])),
                 key=lambda w: w['x0'])
    links, rechts, gat = _cellen(rij)
    assert (links, rechts) == ('Halfkruimige aardappelen', '500 g')
    assert gat > 100


def test_regel_zonder_kolomgrens_heeft_lege_rechtercel():
    rij = sorted(woordboxen(_annotatie([_woord('Verwarm', 100, 500), _woord('de', 220, 500),
                                        _woord('oven', 270, 500)])), key=lambda w: w['x0'])
    links, rechts, gat = _cellen(rij)
    assert links == 'Verwarm de oven' and rechts == ''
```

- [ ] **Step 2: Zie falen** — `ModuleNotFoundError`.

- [ ] **Step 3: Implementatie**

```python
# weekmenu/services/tabel.py
"""Ingrediëntentabel van een receptkaart uit de woordcoördinaten van Vision.

In de platte OCR-tekst valt zo'n tabel uit elkaar: eerst een blok namen, dan
een blok hoeveelheden, met stapnummers ertussen en de laatste hoeveelheden
pas na de kop 'Voedingswaarden'. Het model maakte daar op de ene kaart die
we hadden 14 van de 15 rijen goed van — maar een hoeveelheid aan de
verkeerde naam is in de tekst niet te zien. Geometrisch is de tabel wél
intact: naam en hoeveelheid staan op dezelfde hoogte. Deze module leest de
rijen dus uit de boxen die Vision toch al meegeeft, en geeft het model
schone regels 'naam | hoeveelheid'.

Alles hier is merkloos: rijen zijn woorden op één hoogte, een kolomgrens is
het grootste horizontale gat, en de tabel is het langste blok rijen waarvan
de rechtercel op een hoeveelheid lijkt.
"""
import re

# Een kolomgrens is een gat van minstens zoveel maal de woordhoogte; kleiner
# is gewone spatiëring tussen woorden.
_GAT_FACTOR = 1.5


def woordboxen(annotation):
    """Alle woorden van een fullTextAnnotation als {tekst, x0, x1, y0, y1}.

    Vision laat nulwaarden weg in de JSON: een vertex {'y': 837} betekent
    x = 0. Woorden zonder vier hoekpunten worden overgeslagen.
    """
    boxen = []
    for page in annotation.get('pages') or []:
        for block in page.get('blocks') or []:
            for paragraph in block.get('paragraphs') or []:
                for word in paragraph.get('words') or []:
                    vertices = (word.get('boundingBox') or {}).get('vertices') or []
                    tekst = ''.join(s.get('text', '') for s in word.get('symbols') or [])
                    if len(vertices) != 4 or not tekst:
                        continue
                    xs = [v.get('x', 0) for v in vertices]
                    ys = [v.get('y', 0) for v in vertices]
                    boxen.append({'tekst': tekst, 'x0': min(xs), 'x1': max(xs),
                                  'y0': min(ys), 'y1': max(ys)})
    return boxen


def _rijen(boxen):
    """Woorden gegroepeerd op hoogte; per rij gesorteerd op x.

    Een woord hoort bij de lopende rij als zijn verticale middelpunt binnen
    de band van die rij valt. Dat verdraagt een lichte scheefstand: de band
    groeit mee met elk toegevoegd woord.
    """
    rijen, huidige = [], []
    for w in sorted(boxen, key=lambda b: (b['y0'] + b['y1']) / 2):
        mid = (w['y0'] + w['y1']) / 2
        if huidige and min(b['y0'] for b in huidige) <= mid <= max(b['y1'] for b in huidige):
            huidige.append(w)
        else:
            if huidige:
                rijen.append(sorted(huidige, key=lambda b: b['x0']))
            huidige = [w]
    if huidige:
        rijen.append(sorted(huidige, key=lambda b: b['x0']))
    return rijen


def _splits(rij):
    """(linkerwoorden, rechterwoorden, gat): splitsing op het grootste gat.

    Is het grootste gat kleiner dan _GAT_FACTOR maal de woordhoogte, dan is
    het gewone lopende tekst en zijn de rechterwoorden leeg.
    """
    if len(rij) < 2:
        return list(rij), [], 0.0
    hoogte = sum(w['y1'] - w['y0'] for w in rij) / len(rij)
    gat, plek = max((rij[i + 1]['x0'] - rij[i]['x1'], i) for i in range(len(rij) - 1))
    if gat < _GAT_FACTOR * hoogte:
        return list(rij), [], float(gat)
    return rij[:plek + 1], rij[plek + 1:], float(gat)


def _tekst(woorden):
    return ' '.join(w['tekst'] for w in woorden)


def _cellen(rij):
    """(linkertekst, rechtertekst, gat), zie _splits."""
    links, rechts, gat = _splits(rij)
    return _tekst(links), _tekst(rechts), gat
```

- [ ] **Step 4: Groen en commit**

Run: `python3 -m pytest tests/test_tabel.py -q` → 5 passed.

```bash
git add weekmenu/services/tabel.py tests/test_tabel.py
git commit -m "Woorden van Vision tot rijen en cellen op hun coördinaten

Naam en hoeveelheid van een kaarttabel staan in de OCR-tekst in
verschillende paragrafen, maar wel op dezelfde hoogte."
```

---

### Task 6: `tabelrijen` — de tabel vinden, opschonen, en weigeren bij meerdere kolommen (go/no-go)

Dit is de toets waar het ontwerp op leunt. Slaagt de test op de echte kaart niet met redelijke drempels, stop dan en meld het (spec: "Terugval"); pas de verwachte rijen nooit aan.

**Files:**
- Modify: `weekmenu/services/tabel.py`
- Create: `tests/fixtures/hellofresh_achterkant.json` (via script hieronder)
- Test: `tests/test_tabel.py`

**Interfaces:**
- Consumes: Task 4 (`is_voorraadkop`), Task 5.
- Produces: `tabelrijen(annotation) -> (rijen, reden)`: `rijen` is een lijst `{'naam': str, 'hoeveelheid': str, 'blok': 'kaart'|'voorraad', 'y': int}` of `None`; `reden` is `None` bij succes, anders `'geen tabel'` of `'meerdere kolommen'`. `_HOEVEELHEID` (regex op een rechtercel).

- [ ] **Step 1: Fixture maken uit de benchmark-cache**

Eenmalig script (niet in de repo bewaren; wél de uitvoer):

```bash
python3 - <<'EOF'
import json
full = json.load(open('/pool/apps/weekmenu-cloudvision/data/benchmark-import/ocrtekst/8f4d4064.full.json'))
ann = full[1]['fullTextAnnotation']          # pagina 2 = achterkant
klein = {'pages': [{'blocks': [{'paragraphs': [{'words': [
    {'symbols': [{'text': s.get('text', '')} for s in w.get('symbols') or []],
     'boundingBox': w.get('boundingBox')}
    for w in par.get('words') or []]} for par in b.get('paragraphs') or []]} for b in p.get('blocks') or []]}
    for p in ann['pages']]}
json.dump(klein, open('tests/fixtures/hellofresh_achterkant.json', 'w'), ensure_ascii=False)
print('woorden:', sum(len(par['words']) for p in klein['pages'] for b in p['blocks'] for par in b['paragraphs']))
EOF
```

Expected: `woorden: 660`, bestand ≈ 80 KB.

- [ ] **Step 2: Falende tests**

Voeg toe aan `tests/test_tabel.py`:

```python
import json
import os

from weekmenu.services.tabel import tabelrijen

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'hellofresh_achterkant.json')


def test_tabelrijen_op_de_echte_hellofresh_achterkant():
    """De waarheid van de kaart (week 50 | 2020). Verwachting nooit aanpassen aan de uitvoer."""
    rijen, reden = tabelrijen(json.load(open(FIXTURE)))
    assert reden is None
    assert [(r['naam'], r['hoeveelheid'], r['blok']) for r in rijen] == [
        ('Halfkruimige aardappelen', '500 g', 'kaart'),
        ('Sperziebonen', '200 g', 'kaart'),
        ('Pindakaas', '2 kuipje', 'kaart'),
        ('Kokosmelk', '100 ml', 'kaart'),
        ('Gekruide runderburger', '2 st', 'kaart'),
        ('Komkommer', '1 st', 'kaart'),
        ('Ui', '1 st', 'kaart'),
        ('Mayonaise', '40 g', 'kaart'),
        ('Ketjap', '1 el', 'voorraad'),
        ('Olijfolie', '1 el', 'voorraad'),
        ('Zonnebloemolie', '½ el', 'voorraad'),
        ('Wittewijnazijn', '2 tl', 'voorraad'),
        ('Mosterd', '1 tl', 'voorraad'),
        ('Extra vierge olijfolie', 'naar smaak', 'voorraad'),
        ('Peper en zout', 'naar smaak', 'voorraad'),
    ]


def _tabel_annotatie(regels, x_naam=100, x_hoev=600, start_y=100, stap=60):
    """regels: lijst (naam, hoeveelheid|None). Een None-hoeveelheid is een losse regel."""
    woorden, y = [], start_y
    for naam, hoev in regels:
        x = x_naam
        for t in naam.split():
            woorden.append(_woord(t, x, y)); x += 14 * len(t) + 14
        if hoev is not None:
            x = x_hoev
            for t in hoev.split():
                woorden.append(_woord(t, x, y)); x += 14 * len(t) + 14
        y += stap
    return _annotatie(woorden)


def test_stapnummer_tussen_de_rijen_telt_niet_mee():
    ann = _tabel_annotatie([('Ui', '1 st'), ('3', None), ('Prei', '2 st'), ('Feta', '100 g')])
    rijen, reden = tabelrijen(ann)
    assert reden is None
    assert [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_allergeencodes_en_sterretjes_gaan_van_de_naam():
    ann = _tabel_annotatie([('Pindakaas 5) 21) 22)', '2 kuipje'), ('Mayonaise* 3)', '40 g'), ('Ui', '1 st')])
    rijen, _ = tabelrijen(ann)
    assert [r['naam'] for r in rijen] == ['Pindakaas', 'Mayonaise', 'Ui']


def test_naam_over_twee_regels_wordt_een_rij():
    ann = _tabel_annotatie([('Halfkruimige', None), ('aardappelen', '500 g'), ('Ui', '1 st'), ('Prei', '2 st')])
    rijen, _ = tabelrijen(ann)
    assert (rijen[0]['naam'], rijen[0]['hoeveelheid']) == ('Halfkruimige aardappelen', '500 g')


def test_dubbel_breukteken_in_de_cel_wordt_een():
    ann = _tabel_annotatie([('Zonnebloemolie', '½½⁄2 el'), ('Ui', '1 st'), ('Prei', '2 st')])
    rijen, _ = tabelrijen(ann)
    assert rijen[0]['hoeveelheid'] == '½ el'


def test_voorraadkop_zet_blok_en_is_zelf_geen_rij():
    ann = _tabel_annotatie([('Ui', '1 st'), ('Prei', '2 st'), ('Feta', '100 g'),
                            ('Zelf toevoegen', None), ('Olijfolie', '1 el')])
    rijen, _ = tabelrijen(ann)
    assert [(r['naam'], r['blok']) for r in rijen] == [
        ('Ui', 'kaart'), ('Prei', 'kaart'), ('Feta', 'kaart'), ('Olijfolie', 'voorraad')]


def test_minder_dan_drie_rijen_is_geen_tabel():
    assert tabelrijen(_tabel_annotatie([('Ui', '1 st'), ('Prei', '2 st')])) == (None, 'geen tabel')
    assert tabelrijen({}) == (None, 'geen tabel')


def test_meerdere_hoeveelheidkolommen_worden_geweigerd():
    # 2p en 4p naast elkaar: rechtercellen op twee x-posities.
    woorden = []
    for i, (naam, a, b) in enumerate([('Ui', '1 st', '2 st'), ('Prei', '2 st', '4 st'), ('Feta', '100 g', '200 g')]):
        y = 100 + 60 * i
        woorden += [_woord(naam, 100, y), _woord(a.split()[0], 600, y), _woord(a.split()[1], 660, y),
                    _woord(b.split()[0], 900, y), _woord(b.split()[1], 960, y)]
    assert tabelrijen(_annotatie(woorden)) == (None, 'meerdere kolommen')
```

- [ ] **Step 3: Zie falen** — `ImportError: cannot import name 'tabelrijen'`.

- [ ] **Step 4: Implementatie**

Toevoegen aan `weekmenu/services/tabel.py`:

```python
from weekmenu.services.kaartsignaturen import is_voorraadkop

_FRACTIES = '½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞'
# Een rechtercel is een hoeveelheid als hij met een cijfer of breuk begint,
# of 'naar smaak' is. Meer hoeft niet: de linkercel doet de rest.
_HOEVEELHEID = re.compile(rf'^(\d|[{_FRACTIES}]|naar smaak)', re.IGNORECASE)
_MIN_RIJEN = 3


def _schoon_naam(naam):
    """Allergeencodes ('5) 21) 22)'), sterretjes en losse cijfers aan het eind eraf."""
    naam = re.sub(r'(\s*\d+\))+\s*$', '', naam)
    naam = naam.replace('*', '').strip()
    return re.sub(r'\s+', ' ', naam)


def _schoon_hoeveelheid(cel):
    """OCR-artefacten rond een breukteken: '½½⁄2 el' is '½ el'."""
    cel = re.sub(rf'([{_FRACTIES}])\1+', r'\1', cel)
    cel = re.sub(rf'([{_FRACTIES}])[⁄/]?\d(?!\d)', r'\1', cel)
    return re.sub(r'\s+', ' ', cel).strip()


def tabelrijen(annotation):
    """De ingrediëntentabel van een kaart: ([{naam, hoeveelheid, blok, y}], None),
    of (None, reden) met reden 'geen tabel' of 'meerdere kolommen'.

    De tabel is het langste blok opeenvolgende rijen waarvan de rechtercel
    op een hoeveelheid lijkt. Rijen zonder letters links (stapnummers) tellen
    niet mee en breken het blok niet. Een rij met letters links en niets
    rechts, gevolgd door een rij mét hoeveelheid, is een naam over twee
    regels — tenzij het een voorraadkop is, dan wisselt het blok.
    """
    rijen = [_cellen(r) + (r[0]['y0'],) for r in _rijen(woordboxen(annotation))]

    # Kandidaat per rij: (naam, hoeveelheid, y) of None; koppen en losse
    # regels krijgen een markering zodat het blok ze kan overslaan.
    beste, huidig = [], []
    for links, rechts, _gat, y in rijen:
        heeft_letters = re.search(r'[^\W\d_]', links) is not None
        if rechts and _HOEVEELHEID.match(rechts) and heeft_letters:
            huidig.append(('rij', links, rechts, y))
        elif not heeft_letters:
            continue                                   # stapnummer, paginanummer
        elif is_voorraadkop(links):
            huidig.append(('kop', links, '', y))
        elif not rechts and huidig:
            huidig.append(('los', links, '', y))       # mogelijk eerste helft van een naam
        else:
            if _telt(huidig) > _telt(beste):
                beste = huidig
            huidig = []
    if _telt(huidig) > _telt(beste):
        beste = huidig
    if _telt(beste) < _MIN_RIJEN:
        return None, 'geen tabel'

    uit, blok, prefix = [], 'kaart', ''
    for soort, links, rechts, y in beste:
        if soort == 'kop':
            blok, prefix = 'voorraad', ''
        elif soort == 'los':
            prefix = (prefix + ' ' + links).strip()
        else:
            naam = _schoon_naam((prefix + ' ' + links).strip())
            prefix = ''
            uit.append({'naam': naam, 'hoeveelheid': _schoon_hoeveelheid(rechts), 'blok': blok, 'y': y})

    if _meerdere_kolommen(annotation, uit):
        return None, 'meerdere kolommen'
    return uit, None


def _telt(kandidaten):
    return sum(1 for k in kandidaten if k[0] == 'rij')


def _meerdere_kolommen(annotation, rijen):
    """Staan er rechts van de hoeveelheden nóg hoeveelheden (2p | 4p)?

    Per tabelrij: woorden rechts van de eerste hoeveelheidcel die zelf ook
    op een hoeveelheid lijken. Drie of meer zulke rijen is een tweede kolom.
    """
    ys = {r['y'] for r in rijen}
    tweede = 0
    for rij in _rijen(woordboxen(annotation)):
        if rij[0]['y0'] not in ys:
            continue
        _links, rechts, _gat = _splits(rij)
        # De rechtercel zelf nog eens splitsen: zit daar óók een kolomgrens
        # in, met rechts daarvan weer een hoeveelheid? Dan is het 2p | 4p.
        _r_links, r_rechts, _ = _splits(rechts)
        if r_rechts and _HOEVEELHEID.match(_tekst(r_rechts)):
            tweede += 1
    return tweede >= _MIN_RIJEN
```

- [ ] **Step 5: Draai de tests; bij falen op de echte kaart eerst kijken, dan drempels**

Run: `python3 -m pytest tests/test_tabel.py -q -x`

Faalt alleen `test_tabelrijen_op_de_echte_hellofresh_achterkant`: print de rijen (`python3 -c "..."` met `tabelrijen` op de fixture) en beoordeel of het aan `_GAT_FACTOR`, de y-band of `_HOEVEELHEID` ligt. Toegestaan: `_GAT_FACTOR` tussen 1,0 en 3,0; de y-band-regel in `_rijen`. Niet toegestaan: de verwachte lijst aanpassen. Lukt het niet binnen die ruimte: STOP, commit wat groen is met de echte-kaart-test gemarkeerd `@pytest.mark.xfail(strict=True, reason='rij-reconstructie faalt op de echte kaart, zie spec Terugval')`, en meld het aan Rutger. De rest van het plan gaat dan niet door zonder ontwerpbesluit.

- [ ] **Step 6: Groen en commit**

```bash
git add weekmenu/services/tabel.py tests/test_tabel.py tests/fixtures/hellofresh_achterkant.json
git commit -m "Ingrediëntentabel van een kaart uit de Vision-coördinaten

Het langste blok rijen met een hoeveelheid rechts; stapnummers tellen niet
mee, allergeencodes gaan van de naam, en een tweede hoeveelheidkolom wordt
geweigerd in plaats van geraden. Getoetst op de echte HelloFresh-achterkant."
```

---

### Task 7: `lees_paginas_met_annotaties`

**Files:**
- Modify: `weekmenu/services/ocr.py` (`lees_paginas`)
- Test: `tests/test_ocr_twijfel.py`

**Interfaces:**
- Produces: `lees_paginas_met_annotaties(images, language='nl') -> (texts, twijfels, annotaties)`; `annotaties[i]` is het `fullTextAnnotation`-dict van pagina i+1 (`{}` bij een fout). `lees_paginas` blijft `(texts, twijfels)` teruggeven.

- [ ] **Step 1: Falende test**

Toevoegen aan `tests/test_ocr_twijfel.py`:

```python
from unittest.mock import patch


def test_lees_paginas_met_annotaties_houdt_de_annotatie_vast(app):
    from weekmenu.services.ocr import lees_paginas, lees_paginas_met_annotaties
    ann = _annotatie([[('2', [0.49]), ('theelepel', [0.98] * 9)]])
    ann['text'] = '2 theelepel'
    responses = [{'fullTextAnnotation': ann}, {'error': {'message': 'kapot'}}]
    with patch('weekmenu.services.ocr._get_vision_api_key', return_value='x'), \
         patch('weekmenu.services.ocr._annotate', return_value=responses):
        texts, twijfels, annotaties = lees_paginas_met_annotaties([b'a', b'b'])
        assert texts == ['2 theelepel', '']
        assert twijfels[0][0]['cijfer'] == '2' and twijfels[1] == []
        assert annotaties[0] is ann and annotaties[1] == {}
        assert lees_paginas([b'a', b'b']) == (texts, twijfels)
```

- [ ] **Step 2: Zie falen** — `ImportError`.

- [ ] **Step 3: Implementatie**

In `weekmenu/services/ocr.py` wordt `lees_paginas` een wrapper:

```python
def lees_paginas(images, language='nl'):
    """Lees JPEG-pagina's uit; geeft (teksten, twijfels) terug, beide per pagina."""
    texts, twijfels, _ = lees_paginas_met_annotaties(images, language)
    return texts, twijfels


def lees_paginas_met_annotaties(images, language='nl'):
    """Als lees_paginas, plus de fullTextAnnotation per pagina ({} bij een fout).

    De kaartmodus leest de ingrediëntentabel uit de woordcoördinaten, en die
    zitten alleen in de annotatie. Boekmodus gooit hem weg zoals altijd.
    """
    (bestaande body van lees_paginas, met daarnaast `annotaties = []`;
     bij een fout `annotaties.append({})`, anders `annotaties.append(annotation)`;
     return texts, twijfels, annotaties)
```

Verplaats de docstring-tekst over lege pagina's en twijfels mee naar de nieuwe functie.

- [ ] **Step 4: Groen en commit**

```bash
git add weekmenu/services/ocr.py tests/test_ocr_twijfel.py
git commit -m "Vision-annotaties vasthouden voor de kaartmodus

De tabel komt uit de woordcoördinaten, en die zitten alleen in de
annotatie die lees_paginas tot nu toe weggooide."
```

---

### Task 8: Paren en controle

**Files:**
- Create: `weekmenu/services/kaart.py`
- Test: `tests/test_kaart.py`

**Interfaces:**
- Consumes: `tabelrijen` (Task 6), `is_voorkant` (Task 4).
- Produces: `paren(texts, annotaties) -> (paren, meldingen)`; elk paar is `{'voor': int, 'achter': int, 'rijen': list}` (1-gebaseerde paginanummers). Meldingen zijn strings.

- [ ] **Step 1: Falende tests**

```python
# tests/test_kaart.py
"""Receptkaart: paren, modelinvoer, controle tegen de tabel."""
from unittest.mock import patch

from weekmenu.services.kaart import paren

RIJEN = [{'naam': 'Ui', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 1},
         {'naam': 'Prei', 'hoeveelheid': '2 st', 'blok': 'kaart', 'y': 2},
         {'naam': 'Olijfolie', 'hoeveelheid': '1 el', 'blok': 'voorraad', 'y': 3}]


def _tabel_op(paginas):
    """Patch tabelrijen: pagina's in `paginas` hebben een tabel, de rest niet."""
    def nep(annotation):
        return (RIJEN, None) if annotation.get('p') in paginas else (None, 'geen tabel')
    return patch('weekmenu.services.kaart.tabelrijen', side_effect=nep)


def _ann(n):
    return [{'p': i} for i in range(1, n + 1)]


def test_paren_op_volgorde_voor_dan_achter():
    with _tabel_op({2, 4}):
        uit, meldingen = paren(['HELLO FRESH kaart 1', 'tabel', 'HELLO FRESH kaart 2', 'tabel'], _ann(4))
    assert [(p['voor'], p['achter']) for p in uit] == [(1, 2), (3, 4)]
    assert uit[0]['rijen'] == RIJEN and meldingen == []


def test_achterkant_eerst_is_ook_goed():
    with _tabel_op({1}):
        uit, meldingen = paren(['tabel', 'HELLO FRESH'], _ann(2))
    assert [(p['voor'], p['achter']) for p in uit] == [(2, 1)] and meldingen == []


def test_twee_tabellen_in_een_paar_wordt_gemeld_en_overgeslagen():
    with _tabel_op({1, 2, 4}):
        uit, meldingen = paren(['t', 't', 'HELLO FRESH', 't'], _ann(4))
    assert [(p['voor'], p['achter']) for p in uit] == [(3, 4)]
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: op beide staat een ingrediëntentabel."]


def test_geen_tabel_in_een_paar_wordt_gemeld():
    with _tabel_op(set()):
        uit, meldingen = paren(['HELLO FRESH', 'x'], _ann(2))
    assert uit == []
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: op geen van beide staat een ingrediëntentabel."]


def test_meerdere_kolommen_wordt_met_reden_gemeld():
    with patch('weekmenu.services.kaart.tabelrijen', return_value=(None, 'meerdere kolommen')):
        uit, meldingen = paren(['HELLO FRESH', 'x'], _ann(2))
    assert uit == []
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: de tabel heeft meerdere hoeveelheidkolommen, dat kan de app nog niet."]


def test_oneven_laatste_pagina_wordt_gemeld():
    with _tabel_op({2}):
        uit, meldingen = paren(['HELLO FRESH', 't', 'HELLO FRESH'], _ann(3))
    assert [(p['voor'], p['achter']) for p in uit] == [(1, 2)]
    assert meldingen == ['Pagina 3 heeft geen tegenhanger en is overgeslagen.']
```

- [ ] **Step 2: Zie falen** — `ModuleNotFoundError`.

- [ ] **Step 3: Implementatie**

```python
# weekmenu/services/kaart.py
"""Receptkaart-modus: twee pagina's zijn één recept, en de tabel is leidend.

Merkloos: een achterkant is de pagina waarop een ingrediëntentabel wordt
gevonden (services/tabel.py), een voorkant is de andere. Een merklogo telt
alleen als bevestiging. Een paar dat niet klopt levert geen concept op maar
wél een melding met paginanummers: een half recept is erger dan geen.
"""
import re

from weekmenu.services.kaartsignaturen import (bereidingstijd, is_benodigdheden_kop,
                                               is_voorkant)
from weekmenu.services.tabel import tabelrijen
from weekmenu.services.units import _norm_unit, _parse_amount

_REDEN = {
    'meerdere kolommen': 'de tabel heeft meerdere hoeveelheidkolommen, dat kan de app nog niet',
}


def paren(texts, annotaties):
    """Pagina's op volgorde tot paren (voor, achter); geeft (paren, meldingen)."""
    uit, meldingen = [], []
    for i in range(0, len(texts) - 1, 2):
        a, b = i + 1, i + 2
        tabellen = {n: tabelrijen(annotaties[n - 1] or {}) for n in (a, b)}
        met_tabel = [n for n in (a, b) if tabellen[n][0] is not None]
        if len(met_tabel) == 1:
            achter = met_tabel[0]
            uit.append({'voor': a if achter == b else b, 'achter': achter,
                        'rijen': tabellen[achter][0]})
            continue
        if len(met_tabel) == 2:
            waarom = 'op beide staat een ingrediëntentabel'
        else:
            redenen = {tabellen[n][1] for n in (a, b)} - {'geen tabel', None}
            waarom = (_REDEN[redenen.pop()] if redenen
                      else 'op geen van beide staat een ingrediëntentabel')
        meldingen.append(f"Pagina's {a} en {b} zijn niet als één kaart te lezen: {waarom}.")
    if len(texts) % 2:
        meldingen.append(f'Pagina {len(texts)} heeft geen tegenhanger en is overgeslagen.')
    return uit, meldingen
```

(`is_voorkant`, `bereidingstijd`, `is_benodigdheden_kop`, `_norm_unit`, `_parse_amount` worden in Task 9–10 gebruikt; de imports mogen nu al staan.)

- [ ] **Step 4: Groen en commit**

```bash
git add weekmenu/services/kaart.py tests/test_kaart.py
git commit -m "Kaartpagina's paren op volgorde, met de tabel als bewijs

Een achterkant is de pagina met de tabel; een paar zonder of met twee
tabellen wordt gemeld en overgeslagen, de rest van de batch gaat door."
```

---

### Task 9: Modelinvoer, tabelregels strippen, benodigdheden

**Files:**
- Modify: `weekmenu/services/kaart.py`
- Test: `tests/test_kaart.py`

**Interfaces:**
- Produces: `kaart_invoer(voortekst, achtertekst, rijen, voor, achter) -> str`; `zonder_tabelregels(achtertekst, rijen) -> str`; `benodigdheden(tekst) -> str | None`.

- [ ] **Step 1: Falende tests**

```python
from weekmenu.services.kaart import benodigdheden, kaart_invoer, zonder_tabelregels

ACHTER = ('Benodigdheden\nPan met deksel, koekenpan,\nsteelpan, saladekom\n'
          'Ingrediënten voor 2 personen\nUi\nPrei\n1 st\n2 st\nZelf toevoegen\nOlijfolie\n1 el\n'
          'Snijd de ui\nBak de prei 5 minuten.\n')


def test_zonder_tabelregels_haalt_alleen_celregels_weg():
    uit = zonder_tabelregels(ACHTER, RIJEN)
    assert 'Ui\n' not in uit and '1 st' not in uit and 'Olijfolie' not in uit
    assert 'Snijd de ui' in uit and 'Bak de prei 5 minuten.' in uit
    assert 'Ingrediënten voor 2 personen' in uit   # de kop blijft: daar staat 'yields'


def test_kaart_invoer_heeft_drie_blokken_in_deze_volgorde():
    uit = kaart_invoer('HELLO FRESH\nPrei-ui', ACHTER, RIJEN, 1, 2)
    assert uit.index('--- Voorkant (pagina 1) ---') < uit.index('--- Ingrediënten (tabel) ---') \
        < uit.index('--- Achterkant (pagina 2) ---')
    assert 'Ui | 1 st\nPrei | 2 st\nOlijfolie | 1 el' in uit
    assert 'Snijd de ui' in uit


def test_benodigdheden_onder_de_kop_tot_de_regel_zonder_komma_aan_het_eind():
    assert benodigdheden(ACHTER) == 'Pan met deksel, koekenpan, steelpan, saladekom'
    assert benodigdheden('Snijd de ui\n') is None
```

- [ ] **Step 2: Zie falen** — `ImportError`.

- [ ] **Step 3: Implementatie**

```python
def zonder_tabelregels(achtertekst, rijen):
    """Achterkant zonder de cellen van de tabel, zodat een anker er nooit op valt."""
    cellen = {c.strip().lower() for r in rijen for c in (r['naam'], r['hoeveelheid']) if c}
    return '\n'.join(regel for regel in achtertekst.split('\n')
                     if re.sub(r'\s+', ' ', regel).strip().lower() not in cellen)


def kaart_invoer(voortekst, achtertekst, rijen, voor, achter):
    """De tekst die het model krijgt: voorkant, schone tabelrijen, achterkant."""
    tabel = '\n'.join(f"{r['naam']} | {r['hoeveelheid']}" for r in rijen)
    return (f'--- Voorkant (pagina {voor}) ---\n{voortekst.strip()}\n\n'
            f'--- Ingrediënten (tabel) ---\n{tabel}\n\n'
            f'--- Achterkant (pagina {achter}) ---\n{zonder_tabelregels(achtertekst, rijen).strip()}')


def benodigdheden(tekst):
    """De regels onder de kop 'Benodigdheden', letterlijk, tot een regel die
    niet op een komma eindigt (hooguit vier regels). None zonder kop."""
    regels = (tekst or '').split('\n')
    for i, regel in enumerate(regels):
        if is_benodigdheden_kop(regel):
            uit = []
            for volgende in regels[i + 1:i + 5]:
                volgende = volgende.strip()
                if not volgende:
                    break
                uit.append(volgende)
                if not volgende.endswith(','):
                    break
            return ' '.join(uit) or None
    return None
```

- [ ] **Step 4: Groen en commit**

```bash
git add weekmenu/services/kaart.py tests/test_kaart.py
git commit -m "Modelinvoer voor een kaart: voorkant, schone tabelrijen, achterkant

De tabelcellen gaan uit de achterkanttekst zodat een anker er niet op
kan vallen; de benodigdheden komen letterlijk mee."
```

---

### Task 10: Controle tegen de tabel

**Files:**
- Modify: `weekmenu/services/kaart.py`
- Test: `tests/test_kaart.py`

**Interfaces:**
- Produces: `controleer_tegen_tabel(recipe, rijen, paginas) -> meldingen`. Muteert `recipe['ingredients']`: zet `check` bij afwijking, `kaart_voorraad: True` bij een voorraadrij. `paginas` is een string als `'3+4'`.

- [ ] **Step 1: Falende tests**

```python
from weekmenu.services.kaart import controleer_tegen_tabel


def _recept(*ingredienten):
    return {'name': 'X', 'ingredients': [dict(i) for i in ingredienten], 'meldingen': []}


def test_kloppende_hoeveelheid_krijgt_geen_check():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    meldingen = controleer_tegen_tabel(r, RIJEN, '1+2')
    assert meldingen == []
    assert all('check' not in i for i in r['ingredients'])
    assert r['ingredients'][2]['kaart_voorraad'] is True
    assert 'kaart_voorraad' not in r['ingredients'][0]


def test_afwijkende_hoeveelheid_krijgt_check_met_de_celtekst():
    r = _recept({'name': 'ui', 'amount': 10.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    controleer_tegen_tabel(r, RIJEN, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '1 st'"


def test_breuk_en_eenheid_worden_genormaliseerd_voor_de_vergelijking():
    rijen = [{'naam': 'Zonnebloemolie', 'hoeveelheid': '½ el', 'blok': 'voorraad', 'y': 1},
             {'naam': 'Peper en zout', 'hoeveelheid': 'naar smaak', 'blok': 'voorraad', 'y': 2},
             {'naam': 'Kip', 'hoeveelheid': '300 gram', 'blok': 'kaart', 'y': 3}]
    r = _recept({'name': 'zonnebloemolie', 'amount': 0.5, 'unit': 'el'},
                {'name': 'peper en zout', 'amount': None, 'unit': ''},
                {'name': 'kip', 'amount': 300.0, 'unit': 'g'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert all('check' not in i for i in r['ingredients'])


def test_ingredient_buiten_de_tabel_blijft_staan_met_check():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'}, {'name': 'snuf peper', 'amount': None, 'unit': ''})
    controleer_tegen_tabel(r, RIJEN, '1+2')
    assert r['ingredients'][3]['check'] == 'staat niet in de tabel'
    assert len(r['ingredients']) == 4


def test_ontbrekende_tabelrij_wordt_gemeld():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    meldingen = controleer_tegen_tabel(r, RIJEN, '3+4')
    assert meldingen == ["Pagina's 3+4 (X): tabelrij 'Prei | 2 st' ontbreekt in het concept."]
```

- [ ] **Step 2: Zie falen** — `ImportError`.

- [ ] **Step 3: Implementatie**

```python
def _woorden(tekst):
    return set(re.findall(r'[^\W\d_]{3,}', (tekst or '').lower()))


def _zelfde_hoeveelheid(ingredient, cel):
    """Komt amount+unit van het model overeen met de celtekst?

    'naar smaak' en een lege cel horen bij amount None. Verder: het getal
    via _parse_amount (breuken, komma's) en de eenheid via _norm_unit, zodat
    '300 gram' en 300 g hetzelfde zijn. Alleen als de cel een eenheid heeft
    wordt die vergeleken; '2' tegen 2 stuks is goed.
    """
    cel = (cel or '').strip()
    if not cel or cel.lower() == 'naar smaak':
        return ingredient.get('amount') in (None, '')
    delen = cel.split(' ', 1)
    getal = _parse_amount(delen[0])
    if getal is None or ingredient.get('amount') is None:
        return False
    if abs(float(ingredient['amount']) - getal) > 0.01:
        return False
    if len(delen) == 2:
        return _norm_unit(delen[1]) == _norm_unit(ingredient.get('unit'))
    return True


def controleer_tegen_tabel(recipe, rijen, paginas):
    """De tabel is leidend: elke afwijking wordt zichtbaar, niets wordt omgeschreven.

    Koppelt elk ingrediënt aan de tabelrij met de meeste gedeelde woorden
    (elke rij hooguit één keer). Afwijkende hoeveelheid → 'check' met de
    celtekst; geen rij → 'check' "staat niet in de tabel" (blijft staan);
    rij zonder ingrediënt → melding. Een voorraadrij markeert het ingrediënt
    als 'kaart_voorraad', zodat het formulier het vinkje al aanzet.
    """
    vrij = list(range(len(rijen)))
    for ing in recipe['ingredients']:
        naam = _woorden(ing.get('name'))
        beste, score = None, 0
        for i in vrij:
            s = len(naam & _woorden(rijen[i]['naam']))
            if s > score:
                beste, score = i, s
        if beste is None:
            ing['check'] = 'staat niet in de tabel'
            continue
        vrij.remove(beste)
        rij = rijen[beste]
        if not _zelfde_hoeveelheid(ing, rij['hoeveelheid']):
            ing['check'] = f"tabel zegt '{rij['hoeveelheid']}'"
        if rij['blok'] == 'voorraad':
            ing['kaart_voorraad'] = True
    return [f"Pagina's {paginas} ({recipe['name']}): tabelrij "
            f"'{rijen[i]['naam']} | {rijen[i]['hoeveelheid']}' ontbreekt in het concept."
            for i in vrij]
```

- [ ] **Step 4: Groen en commit**

```bash
git add weekmenu/services/kaart.py tests/test_kaart.py
git commit -m "Tabel is leidend: elke afwijking van het model wordt een check of melding

Hoeveelheid anders dan de cel, ingrediënt buiten de tabel, rij zonder
ingrediënt — alle drie zichtbaar, niets stil omgeschreven."
```

---

### Task 11: `standaard_pagina`, `_KAART_PROMPT` en twijfels op de achterkant

**Files:**
- Modify: `weekmenu/services/dump.py` (`parse_batch_response`, `_bereiding`, `_markeer_twijfels`, nieuwe `_KAART_PROMPT`)
- Test: `tests/test_kaart_pijplijn.py`, `tests/test_ocr_twijfel.py`

**Interfaces:**
- Produces: `parse_batch_response(text, page_texts=None, standaard_pagina=None)` — als `standaard_pagina` gezet is wordt `photo_page` van het model genegeerd; `_KAART_PROMPT` (str); `_markeer_twijfels` registreert een recept ook onder `recipe['back_page']`.

- [ ] **Step 1: Falende tests**

In `tests/test_kaart_pijplijn.py`:

```python
def test_standaard_pagina_overstemt_photo_page_van_het_model(app):
    from weekmenu.services.dump import parse_batch_response
    antwoord = json.dumps([{'title': 'K', 'yields': 2, 'photo_page': 7,
                            'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'}],
                            'steps': [{'start': 'Snijd de ui', 'end': 'in ringen.'}]}])
    recepten = parse_batch_response(antwoord, ['Snijd de ui in ringen.'], standaard_pagina=1)
    assert recepten[0]['photo_page'] == 1
    assert recepten[0]['instructions'] == 'Snijd de ui in ringen.'
    assert recepten[0]['meldingen'] == []


def test_kaartprompt_vraagt_een_recept_en_geen_photo_page():
    from weekmenu.services.dump import _KAART_PROMPT
    assert 'één recept' in _KAART_PROMPT and 'Ingrediënten (tabel)' in _KAART_PROMPT
    assert '"photo_page"' not in _KAART_PROMPT
    assert 'Gebruik ALLEEN deze eenheden' in _KAART_PROMPT   # de boekregels reizen mee
```

In `tests/test_ocr_twijfel.py`:

```python
def test_twijfel_op_de_achterkant_komt_op_het_kaartrecept():
    recipes = [{'photo_page': 1, 'back_page': 2, 'ingredients': [{'name': 'komkommer', 'amount': 1, 'unit': 'stuks'}]}]
    twijfels = [[], [{'regel': '12 komkommer', 'cijfer': '12', 'zekerheid': 0.31}]]
    _markeer_twijfels(recipes, twijfels)
    assert 'check' in recipes[0]['ingredients'][0]
```

- [ ] **Step 2: Zie falen** — `TypeError: unexpected keyword 'standaard_pagina'`, `ImportError` op `_KAART_PROMPT`, en de twijfeltest: geen `check`.

- [ ] **Step 3: Implementatie**

`parse_batch_response(text, page_texts=None, standaard_pagina=None)`: in de lus

```python
        photo_page = item.get('photo_page')
        photo_page = int(photo_page) if isinstance(photo_page, (int, float)) else None
        if standaard_pagina is not None:
            # Kaartmodus: het model kent maar één (samengevoegde) tekst en
            # mag geen paginanummer kiezen dat er niet is.
            photo_page = standaard_pagina
```

Docstring-regel erbij: "`standaard_pagina`: als gezet, wordt `photo_page` van het model genegeerd (kaartmodus: één samengevoegde tekst)."

`_markeer_twijfels`: de opbouw van `per_pagina` wordt

```python
    for r in recipes:
        for p in (r.get('photo_page'), r.get('back_page')):
            if p:
                per_pagina.setdefault(p, []).append(r)
```

`_KAART_PROMPT`, direct na `_BATCH_PROMPT`:

```python
# De kaartprompt deelt alle regels met de boekprompt (eenheden, breuken
# letterlijk, "volle", niets verzinnen, ankers) en verschilt alleen in de kop:
# één recept, de ingrediënten uitsluitend uit het tabelblok, geen photo_page.
_KAART_PROMPT = f"""Hieronder staat de uitgelezen tekst van ÉÉN receptkaart, in drie blokken:
de voorkant, de ingrediëntentabel als regels 'naam | hoeveelheid', en de achterkant.
Het is precies één recept. Geef ALLEEN geldige JSON terug, geen markdown: een lijst
met één object.

[
  {{
    "title": "Recept naam",
    "yields": 2,
    "ingredients": [
      {{"name": "halfkruimige aardappelen", "amount": "500", "unit": "g"}},
      {{"name": "zonnebloemolie", "amount": "½", "unit": "el"}}
    ],
    "steps": [
      {{"start": "Verwarm de oven voor", "end": "Schep halverwege om."}}
    ]
  }}
]

Regels voor de kaart:
- "ingredients": uitsluitend de regels uit het blok '--- Ingrediënten (tabel) ---', in
  die volgorde, één ingrediënt per regel. Vóór '|' staat de naam, erna de hoeveelheid
  met eenheid. 'naar smaak' of een lege hoeveelheid wordt amount null
- "yields": het getal uit 'voor N personen' als dat op de kaart staat, anders null
- Een bereidingsstap kan op de voorkant beginnen; de stapkoppen ('Frietjes maken')
  horen bij de stap die eronder staat
- Tips en weetjes zijn bereidingstekst en horen bij de stap waar ze onder staan

Regels:""" + _BATCH_PROMPT.split('Regels:', 1)[1]
```

- [ ] **Step 4: Groen en commit**

Run: `python3 -m pytest tests/ -q` → groen (de boekprompt is ongewijzigd; `tests/test_ankers.py` blijft groen).

```bash
git add weekmenu/services/dump.py tests/test_kaart_pijplijn.py tests/test_ocr_twijfel.py
git commit -m "Kaartprompt en één samengevoegde paginatekst voor de ankerknip

De kaartprompt deelt alle regels met de boekprompt en verschilt alleen in
de kop; photo_page van het model wordt in kaartmodus genegeerd."
```

---

### Task 12: `_verwerk_kaarten` en het vangnet in `_process`

**Files:**
- Modify: `weekmenu/services/dump.py` (`_process`, nieuwe `_verwerk_kaarten`, import `lees_paginas_met_annotaties`, drafts met `prep_time`/`back_image_path`)
- Modify: `weekmenu/routes/dump.py` (`serialize_draft`: `kaart_voorraad` → `in_pantry`)
- Test: `tests/test_kaart_pijplijn.py`

**Interfaces:**
- Consumes: alles hiervoor.
- Produces: in kaartmodus concepten met `source_page = voor`, `image_path` van de voorkant, `back_image_path` van de achterkant, `prep_time` uit de signatuur, ingrediënten met `check`/`kaart_voorraad`; batchmeldingen uit `paren`, `controleer_tegen_tabel` en de ankerknip; in boekmodus het vangnet.

- [ ] **Step 1: Falende tests**

```python
VOOR = 'HELLO Patatje oorlog\nFRESH\nBereidingstijd:40 min. (totaal voor 2 personen)\n'
ACHTER = ('Benodigdheden\nPan met deksel\nIngrediënten voor 2 personen\nUi\n1 st\nPrei\n2 st\nOlijfolie\n1 el\n'
          'Snijd de ui in ringen.\nBak de prei 5 minuten.\n')
RIJEN = [{'naam': 'Ui', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 1},
         {'naam': 'Prei', 'hoeveelheid': '2 st', 'blok': 'kaart', 'y': 2},
         {'naam': 'Olijfolie', 'hoeveelheid': '1 el', 'blok': 'voorraad', 'y': 3}]
ANTWOORD = json.dumps([{'title': 'Patatje oorlog', 'yields': 2,
                        'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'},
                                        {'name': 'prei', 'amount': '3', 'unit': 'stuks'},
                                        {'name': 'olijfolie', 'amount': '1', 'unit': 'el'}],
                        'steps': [{'start': 'Snijd de ui', 'end': '5 minuten.'}]}])


class _Antwoord:
    text = ANTWOORD
    candidates = []


def _draai(tmp_path, mode, texts, annotaties, tabel):
    job = DumpJob(id=f'job-{mode}', status='processing', mode=mode)
    db.session.add(job)
    db.session.commit()
    jobmap = tmp_path / 'job'
    jobmap.mkdir()
    twijfels = [[] for _ in texts]
    with patch('weekmenu.services.dump._get_gemini_api_key', return_value='x'), \
         patch('weekmenu.services.dump.lees_paginas_met_annotaties', return_value=(texts, twijfels, annotaties)), \
         patch('weekmenu.services.dump.lees_paginas', return_value=(texts, twijfels)), \
         patch('weekmenu.services.kaart.tabelrijen', side_effect=tabel), \
         patch('weekmenu.services.dump._pdf_page_jpegs', return_value=[b'a'] * len(texts)), \
         patch('weekmenu.services.dump._job_dir', return_value=str(jobmap)), \
         patch('weekmenu.services.dump._resolve_image', side_effect=lambda j, p, m: f'static/uploads/p{p}.jpg'), \
         patch('google.genai.Client') as client:
        (jobmap / '000.pdf').write_bytes(b'%PDF-')
        client.return_value.models.generate_content.return_value = _Antwoord()
        from weekmenu.services.dump import _process
        _process(job)
        db.session.commit()
        return job, client


def test_kaartmodus_maakt_een_concept_van_twee_paginas(app, tmp_path):
    job, client = _draai(tmp_path, 'kaart', [VOOR, ACHTER], [{'p': 1}, {'p': 2}],
                         lambda ann: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'))
    drafts = RecipeDraft.query.filter_by(job_id=job.id).all()
    assert len(drafts) == 1
    d = drafts[0]
    assert (d.name, d.serves, d.prep_time, d.source_page) == ('Patatje oorlog', 2, 40, 1)
    assert d.image_path == 'static/uploads/p1.jpg' and d.back_image_path == 'static/uploads/p2.jpg'
    assert d.instructions.startswith('Benodigdheden: Pan met deksel\n')
    assert 'Snijd de ui in ringen.' in d.instructions and 'Bak de prei 5 minuten.' in d.instructions
    ing = json.loads(d.ingredients_json)
    assert ing[1]['check'] == "tabel zegt '2 st'"
    assert ing[2]['kaart_voorraad'] is True
    assert client.return_value.models.generate_content.call_count == 1
    prompt = client.return_value.models.generate_content.call_args.kwargs['contents'][0]
    assert '--- Ingrediënten (tabel) ---\nUi | 1 st\nPrei | 2 st\nOlijfolie | 1 el' in prompt
    assert job.warning is None


def test_slecht_paar_wordt_gemeld_en_de_rest_gaat_door(app, tmp_path):
    job, client = _draai(tmp_path, 'kaart', [VOOR, ACHTER, VOOR, VOOR], [{'p': i} for i in (1, 2, 3, 4)],
                         lambda ann: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'))
    assert RecipeDraft.query.filter_by(job_id=job.id).count() == 1
    assert "Pagina's 3 en 4 zijn niet als één kaart te lezen" in job.warning
    assert '4 pagina' not in job.warning   # geen 'minder recepten dan pagina's'-melding: paren tellen


def test_boekmodus_waarschuwt_bij_kaarten(app, tmp_path):
    job, _ = _draai(tmp_path, 'boek', [VOOR, ACHTER, VOOR, ACHTER], [{}] * 4, lambda ann: (None, 'geen tabel'))
    assert "lijken receptkaarten" in job.warning and "Pagina's 1, 3" in job.warning


def test_serialize_draft_zet_kaart_voorraad_om_in_pantry(app, client):
    from weekmenu.routes.dump import serialize_draft
    db.session.add(DumpJob(id='s', status='done'))
    d = RecipeDraft(job_id='s', name='K', ingredients_json=json.dumps(
        [{'name': 'olijfolie', 'amount': 1, 'unit': 'el', 'kaart_voorraad': True}]))
    db.session.add(d)
    db.session.commit()
    assert serialize_draft(d)['ingredients'][0]['in_pantry'] is True
```

- [ ] **Step 2: Zie falen** — `AttributeError: module has no attribute 'lees_paginas_met_annotaties'` (nog niet geïmporteerd in dump.py), daarna 0 concepten.

- [ ] **Step 3: Implementatie in `dump.py`**

Imports:

```python
from weekmenu.services.kaart import (benodigdheden, controleer_tegen_tabel, kaart_invoer,
                                     paren, zonder_tabelregels)
from weekmenu.services.kaartsignaturen import bereidingstijd, is_voorkant
from weekmenu.services.ocr import (_clean_ocr_text, lees_paginas, lees_paginas_met_annotaties,
                                   pages_as_labelled_text)
```

In `_process`, vervang `texts, twijfels = lees_paginas(images)` door:

```python
    if job.mode == 'kaart':
        texts, twijfels, annotaties = lees_paginas_met_annotaties(images)
    else:
        texts, twijfels = lees_paginas(images)
        annotaties = None
```

Vervang het blok vanaf `client = _genai.Client(api_key=api_key)` tot en met `_markeer_twijfels(recipes, twijfels)` door:

```python
    client = _genai.Client(api_key=api_key)
    config = _gtypes.GenerateContentConfig(temperature=0)
    if job.mode == 'kaart':
        recipes, kaartmeldingen, verwacht = _verwerk_kaarten(texts, annotaties, client, config)
        meldingen += kaartmeldingen
    else:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[_BATCH_PROMPT + '\n\n' + pages_as_labelled_text(texts)],
            config=config)
        if _warn_if_truncated(response):
            meldingen.append('Het antwoord van Gemini was afgekapt; er kunnen recepten '
                             'ontbreken. Probeer het opnieuw of splits de batch.')
        recipes = parse_batch_response(response.text, [_clean_ocr_text(t) for t in texts])
        verwacht = len(images) - len(zonder_tekst)
        # Vangnet: kaarten in boekmodus leveren twee halve recepten per kaart op.
        kaarten = [n for n, t in enumerate(texts, 1) if is_voorkant(t)]
        if len(kaarten) >= 2:
            meldingen.append("Pagina's {} lijken receptkaarten. Kies 'receptkaarten' als soort "
                             "scan en probeer opnieuw.".format(', '.join(map(str, kaarten))))
    _markeer_twijfels(recipes, twijfels)
```

(De bestaande temperatuur-0-commentaarregels blijven boven `client = ...` staan.)

In de lus die meldingen per recept toevoegt, en de draft-aanmaak:

```python
    for r in recipes:
        for m in r.get('meldingen') or []:
            waar = f"Pagina {r['photo_page']}" if not r.get('back_page') \
                else f"Pagina's {r['photo_page']}+{r['back_page']}"
            meldingen.append(f"{waar} ({r['name']}): {m}. Controleer de bereiding tegen de foto.")
    ...
        db.session.add(RecipeDraft(
            job_id=job.id, name=r['name'],
            serves=r['serves'],
            prep_time=r.get('prep_time'),
            instructions=r['instructions'],
            ingredients_json=json.dumps(r['ingredients']),
            image_path=image_path,
            back_image_path=(_resolve_image(job.id, r['back_page'], page_map)
                             if r.get('back_page') else None),
            source_page=r['photo_page'], status='pending',
        ))
```

en de slotmelding gebruikt `verwacht`:

```python
    gemaakt = len(recipes) - overgeslagen
    if gemaakt < verwacht:
        meldingen.append(f'{len(images)} pagina\'s aangeleverd, {gemaakt} recept(en) '
                         f'herkend. Controleer of er niets ontbreekt.')
```

Nieuwe functie, na `_process`:

```python
def _verwerk_kaarten(texts, annotaties, client, config):
    """Kaartmodus: per paar één modelaanroep. Geeft (recipes, meldingen, aantal paren).

    Elk recept krijgt 'photo_page' (voorkant), 'back_page' (achterkant),
    'prep_time' uit de merksignatuur, benodigdheden vooraan in de bereiding,
    en de tabelcontrole (check/kaart_voorraad op de ingrediënten).
    """
    paren_lijst, meldingen = paren(texts, annotaties)
    recipes = []
    for paar in paren_lijst:
        voor, achter, rijen = paar['voor'], paar['achter'], paar['rijen']
        voortekst = _clean_ocr_text(texts[voor - 1])
        achtertekst = _clean_ocr_text(texts[achter - 1])
        gecombineerd = voortekst.strip() + '\n' + zonder_tabelregels(achtertekst, rijen).strip()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[_KAART_PROMPT + '\n\n' + kaart_invoer(voortekst, achtertekst, rijen, voor, achter)],
            config=config)
        waar = f"Pagina's {voor}+{achter}"
        if _warn_if_truncated(response):
            meldingen.append(f'{waar}: het antwoord van Gemini was afgekapt. Probeer het opnieuw.')
        gevonden = parse_batch_response(response.text, [gecombineerd], standaard_pagina=1)
        if not gevonden:
            meldingen.append(f'{waar}: het model gaf geen recept terug.')
            continue
        if len(gevonden) > 1:
            meldingen.append(f'{waar}: het model gaf {len(gevonden)} recepten voor één kaart; '
                             f'alleen het eerste is bewaard.')
        r = gevonden[0]
        r['photo_page'], r['back_page'] = voor, achter
        r['prep_time'] = bereidingstijd(voortekst) or bereidingstijd(achtertekst)
        nodig = benodigdheden(achtertekst)
        if nodig:
            r['instructions'] = f'Benodigdheden: {nodig}\n' + (r['instructions'] or '')
        meldingen += controleer_tegen_tabel(r, rijen, f'{voor}+{achter}')
        recipes.append(r)
    return recipes, meldingen, len(paren_lijst)
```

`weekmenu/routes/dump.py`, `serialize_draft`:

```python
    ingredienten = annotate_pantry_status(json.loads(d.ingredients_json or '[]'))
    for i in ingredienten:
        # De kaart zegt 'zelf toevoegen': vinkje alvast aan, tenzij de
        # voorraad het al wist.
        if i.get('kaart_voorraad') and not i.get('in_pantry'):
            i['in_pantry'] = True
    return {
        ...
        'ingredients': ingredienten,
```

- [ ] **Step 4: Groen**

Run: `python3 -m pytest tests/ -q` → groen. Let op `tests/test_dump_retry.py`: die patcht `lees_paginas` en draait in boekmodus; de vangnet-tekst mag daar niet vuren (hun teksten bevatten geen `HELLO FRESH`).

- [ ] **Step 5: Commit**

```bash
git add weekmenu/services/dump.py weekmenu/routes/dump.py tests/test_kaart_pijplijn.py
git commit -m "Kaartmodus in de pijplijn: paren, één aanroep per kaart, tabelcontrole

Voorkant wordt de foto, achterkant de nakijkfoto, bereidingstijd uit de
signatuur, benodigdheden vooraan. In boekmodus waarschuwt de app als de
pagina's eruitzien als kaarten."
```

---

### Task 13: Nakijkkaart: bereidingstijd, achterkant, controleer-melding

**Files:**
- Modify: `templates/dump.html` (`renderCard`)
- Test: handmatig in de browser (geen JS-testharnas in deze repo), zoals bij stap 2 van het vervolgplan: losse Flask-instance op een vrije poort, bereikbaar via het LAN-adres van de host (Claude-in-Chrome kan niet bij 127.0.0.1 van de sandbox).

- [ ] **Step 1: Template**

In `renderCard`, na de regel met `scan ${esc(d.source_page)}` de bereidingstijd en de achterkant toevoegen — vervang de `<p class="text-sm text-[#6B6B6B]">…</p>`-regel door:

```js
    const meta = [
        d.serves ? esc(d.serves) + ' personen' : '',
        d.prep_time ? '⏱ ' + esc(d.prep_time) + ' min' : '',
        d.source_page ? 'scan ' + esc(d.source_page) : '',
    ].filter(Boolean).join(' · ');
    const achterkant = imageUrl(esc(d.back_image_path));
```

en in de template-string:

```html
            <p class="text-sm text-[#6B6B6B]">${meta}${achterkant ? ` · <a href="${achterkant}" target="_blank" class="underline">achterkant</a>` : ''}</p>
```

- [ ] **Step 2: Browsercheck**

Seed een concept met `prep_time=40`, `back_image_path` naar een bestaand bestand in `static/uploads`, en een ingrediënt met `check: "tabel zegt '2 st'"` en één met `kaart_voorraad: true`. Controleer op `/dump`: "⏱ 40 min" staat er, de link "achterkant" opent de foto, de check-regel is oranje; klik "Aanpassen": het voorraad-vinkje staat aan bij het voorraad-item en de check-hint staat onder de naam.

- [ ] **Step 3: Tests en commit**

Run: `python3 -m pytest tests/ -q` → groen.

```bash
git add templates/dump.html
git commit -m "Nakijkkaart toont bereidingstijd en een link naar de achterkant

De hoeveelheden staan op de achterkant; die wil je naast de check zien."
```

---

### Task 14: Meetlat: 12 kaarten, 3 blind

Buiten de repo (`data/` is gitignored in weekmenu-cloudvision). Dit kost Vision-aanroepen (2 per kaart) en één Gemini-aanroep per kaart; Rutger heeft dat goedgekeurd in de ontwerpronde.

**Files:**
- Create: `/pool/apps/weekmenu-cloudvision/data/benchmark-import/proef2/acceptatie_kaart.py`
- Create: `/pool/apps/weekmenu-cloudvision/data/benchmark-import/ocrtekst/kaart-<nn>.full.json` (cache, via `proef2/vision_full.py`-patroon)
- Create: `/pool/apps/weekmenu-cloudvision/data/benchmark-import/proef2/kaart-waarheid.json` (per zichtbare kaart de tabelrijen zoals ze op de kaart staan, met de hand ingevoerd)

- [ ] **Step 1: Kaarten scannen en Vision cachen**

Rutger levert 12 kaarten als 24 pagina's (voor-, achterkant, op volgorde). Nummer ze `kaart-01` … `kaart-12`; `kaart-10`, `-11`, `-12` zijn blind: niet openen tot Step 4. Zit er een ander merk bij, dan hoort dat bij de blinde drie. Cache de Vision-antwoorden zoals `proef2/vision_full.py` dat doet (één `.full.json` per kaart met beide pagina's).

- [ ] **Step 2: Waarheid invoeren voor kaart 1–9**

`kaart-waarheid.json`: `{"kaart-01": {"rijen": [["Halfkruimige aardappelen", "500 g"], ...], "yields": 2, "prep_time": 40}, ...}` — overgetypt van de kaart, niet van de OCR.

- [ ] **Step 3: Script**

```python
"""Acceptatie kaartmodus. Gebruik: acceptatie_kaart.py <repo> [--blind]
Zonder --blind: kaart 1–9. Met --blind: kaart 10–12, één keer, niets bijstellen.
Per kaart: tabelrijen == waarheid; modelantwoord (uit cache, anders één aanroep)
door controleer_tegen_tabel; telt checks, meldingen, en of de bereiding letterlijk
uit de OCR komt (zelfde toets als herknip.py)."""
import json, os, sys
REPO = sys.argv[1]; sys.path.insert(0, REPO)
os.environ.setdefault('DATABASE_URL', 'sqlite://')
HERE = os.path.dirname(os.path.abspath(__file__)); BM = os.path.dirname(HERE)
BLIND = '--blind' in sys.argv
KAARTEN = [f'kaart-{n:02d}' for n in (range(10, 13) if BLIND else range(1, 10))]
from weekmenu import create_app
with create_app().app_context():
    from weekmenu.services.tabel import tabelrijen
    from weekmenu.services.kaart import paren, kaart_invoer, zonder_tabelregels, controleer_tegen_tabel
    from weekmenu.services.dump import _KAART_PROMPT, parse_batch_response, _get_gemini_api_key
    from weekmenu.services.ocr import _clean_ocr_text
    from weekmenu.services.ankers import normaliseer
    waarheid = json.load(open(f'{HERE}/kaart-waarheid.json')) if not BLIND else {}
    totaal_ok = 0
    for k in KAARTEN:
        full = json.load(open(f'{BM}/ocrtekst/{k}.full.json'))
        texts = [(r.get('fullTextAnnotation') or {}).get('text', '') for r in full]
        anns = [r.get('fullTextAnnotation') or {} for r in full]
        prs, meld = paren(texts, anns)
        if not prs:
            print(k, 'GEEN PAAR:', meld); continue
        p = prs[0]; rijen = p['rijen']
        cel = [[r['naam'], r['hoeveelheid']] for r in rijen]
        if not BLIND:
            ok = cel == waarheid[k]['rijen']; totaal_ok += ok
            print(k, 'tabel', 'OK' if ok else f'AFWIJKING {cel} != {waarheid[k]["rijen"]}')
        voor, achter = _clean_ocr_text(texts[p['voor']-1]), _clean_ocr_text(texts[p['achter']-1])
        cache = f'{HERE}/kaart-antwoord-{k}.json'
        if os.path.exists(cache):
            raw = json.load(open(cache))['raw']
        else:
            from google import genai; from google.genai import types
            resp = genai.Client(api_key=_get_gemini_api_key()).models.generate_content(
                model='gemini-2.5-flash', contents=[_KAART_PROMPT + '\n\n' + kaart_invoer(voor, achter, rijen, p['voor'], p['achter'])],
                config=types.GenerateContentConfig(temperature=0))
            raw = resp.text; json.dump({'raw': raw}, open(cache, 'w'), ensure_ascii=False)
        gecombineerd = voor.strip() + '\n' + zonder_tabelregels(achter, rijen).strip()
        r = parse_batch_response(raw, [gecombineerd], standaard_pagina=1)[0]
        meld += controleer_tegen_tabel(r, rijen, f"{p['voor']}+{p['achter']}")
        checks = [(i['name'], i['check']) for i in r['ingredients'] if i.get('check')]
        letterlijk = all(zin.strip() in normaliseer(gecombineerd).replace('\n', ' ')
                         for zin in r['instructions'].split('\n') if zin.strip() and not zin.startswith('Benodigdheden'))
        print(f"{k}: {len(rijen)} rijen, {len(r['ingredients'])} ingrediënten, checks {checks}, "
              f"meldingen {len(meld)}, bereiding letterlijk {letterlijk}, stappen {r['meldingen']}")
    if not BLIND:
        print(f'tabel gelijk aan waarheid: {totaal_ok}/{len(KAARTEN)}')
```

- [ ] **Step 4: Meten**

Run: `python3 proef2/acceptatie_kaart.py /pool/apps/weekmenu-planner`

Acceptatie (spec): tabel gelijk aan waarheid 9/9; per kaart 0 checks "staat niet in de tabel", 0 "tabelrij ontbreekt"; bereiding letterlijk op elke kaart. Wijkt het af: eerst kijken of het een kaartvariant is die het ontwerp niet kende (dan melden), pas daarna drempels — en nooit de waarheid aanpassen.

Dan één keer: `python3 proef2/acceptatie_kaart.py /pool/apps/weekmenu-planner --blind`. Uitkomst wordt gerapporteerd zoals hij is; bijstellen op de blinde kaarten is niet toegestaan.

- [ ] **Step 5: Vastleggen**

Uitslag in het geheugenbestand van het project (sectie "Stap 4") en in de spec onder "Testen" als gemeten stand: aantallen, welke kaarten afweken en waarom.

---

## Self-review

**Spec coverage:** modus + vlag (T3), vangnet (T12), paren + controle + oneven (T8, T12), tabel uit geometrie incl. nulwaarden, allergeencodes, twee-regelige naam, voorraadblok, meerdere kolommen (T5–T6), annotaties vasthouden (T7), signaturen (T4), prompt (T11), tabel-leidend-controle met de vier situaties (T10), ankers over beide pagina's via één samengevoegde tekst + `standaard_pagina` (T11–T12), benodigdheden en tips (T9, T12), voorraad → `in_pantry` (T12), bereidingstijd als veld met formulier en accept (T1–T2), `back_image_path` en nakijkkaart (T1, T12, T13), meldingen met paginanummers (T8, T12), meetlat met blinde kaarten (T14), terugval bij falende rij-reconstructie (T6 Step 5).

**Niet in het plan, bewust:** meldingen vertalen naar "pagina 1" óf "pagina 2" binnen een paar — het plan noemt beide nummers ("Pagina's 3+4"); dat noemt het paginanummer en is kleiner. Spec-regel "Meldingen noemen het paginanummer" is daarmee gedekt.

**Type consistency:** `tabelrijen -> (rijen | None, reden | None)` overal; rij-dict `{'naam', 'hoeveelheid', 'blok', 'y'}`; `paren -> (list[{'voor','achter','rijen'}], meldingen)`; `controleer_tegen_tabel(recipe, rijen, paginas: str) -> meldingen`; `parse_batch_response(text, page_texts, standaard_pagina)`; `_verwerk_kaarten(texts, annotaties, client, config) -> (recipes, meldingen, aantal_paren)`; recepten dragen `photo_page`, `back_page`, `prep_time`.
