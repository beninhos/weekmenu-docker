# Recepten-dump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch-import van recepten uit kookboekfoto's/PDF via één Gemini-call, met review-wachtrij op een nieuwe `/dump`-pagina en PWA share-target.

**Architecture:** Flask-app (app-factory in `weekmenu/__init__.py`, blueprints in `weekmenu/routes/`, services in `weekmenu/services/`). Nieuwe tabellen `DumpJob` en `RecipeDraft` (aangemaakt door bestaande `db.create_all()`), nieuwe service `weekmenu/services/dump.py` (Gemini-batchcall in achtergrondthread), nieuwe blueprint `weekmenu/routes/dump.py`, template `templates/dump.html`. Accept hergebruikt `_resolve_or_create_ingredient` en `_normalize_ri_unit`. Spec: `docs/superpowers/specs/2026-07-05-recipe-dump-design.md`.

**Tech Stack:** Flask 2.3 / SQLAlchemy 2, google-genai (`gemini-2.5-flash`, PDF als native `application/pdf`-part), pypdfium2 + Pillow (paginarender), Tailwind-classes zoals bestaande templates, pytest (nieuw, dev-only).

## Global Constraints

- Alles op de dev-omgeving testen: `docker-compose -f docker-compose.dev.yml up -d --build`, poort **5002**, db `weekmenu_dev.db`. Geen link vanaf de receptenpagina toevoegen.
- Gemini-model: `gemini-2.5-flash` (zelfde als bestaande import). API-key via `_get_gemini_api_key()` uit `weekmenu/services/gemini.py`.
- UI-teksten in het Nederlands; stijl/kleuren kopiëren uit bestaande templates (bijv. `new_recipe.html`): accent `#8B4513`, borders `#E8E4DC`, banaan-gif `/static/uploads/dancing-banana.gif`.
- Bestaande foto-import op `new_recipe` blijft ongewijzigd werken.
- Commits in het Nederlands, zonder Co-Authored-By/attributieregels (gebruikersvoorkeur).

---

### Task 1: Modellen + pytest-basis

**Files:**
- Modify: `weekmenu/models.py` (onderaan toevoegen)
- Create: `tests/conftest.py`, `tests/test_models.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `DumpJob(id: str uuid, status: str, error_message, created_at)`, `RecipeDraft(id, job_id, name, serves, instructions, ingredients_json, image_path, source_page, status, created_at)`. Status-waarden: job `processing|done|error`; draft `pending|accepted|rejected`.

- [ ] **Step 1: Schrijf failing test**

`tests/conftest.py`:
```python
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ['DATABASE_URL'] = 'sqlite://'  # in-memory

from weekmenu import create_app
from weekmenu.extensions import db as _db


@pytest.fixture()
def app(tmp_path):
    app = create_app()
    app.config['TESTING'] = True
    app.static_folder = str(tmp_path / 'static')
    os.makedirs(os.path.join(app.static_folder, 'uploads'), exist_ok=True)
    with app.app_context():
        yield app
        _db.session.rollback()


@pytest.fixture()
def client(app):
    return app.test_client()
```

`tests/test_models.py`:
```python
import json

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft


def test_dumpjob_and_draft_roundtrip(app):
    job = DumpJob(id='abc-123', status='processing')
    db.session.add(job)
    db.session.flush()

    draft = RecipeDraft(
        job_id='abc-123', name='Shakshuka', serves=4,
        instructions='Stap 1. Doe dingen.',
        ingredients_json=json.dumps([{'name': 'ei', 'amount': 3, 'unit': 'stuks', 'category': 'zuivel'}]),
        image_path=None, source_page=2, status='pending',
    )
    db.session.add(draft)
    db.session.flush()

    assert draft.id is not None
    assert draft.job.status == 'processing'
    assert job.drafts[0].name == 'Shakshuka'
```

- [ ] **Step 2: Run test, verwacht FAIL**

Run: `pip install pytest && python -m pytest tests/test_models.py -v` (lokaal, of in de dev-container: `docker compose -f docker-compose.dev.yml exec weekmenu-dev sh -c "pip install pytest && python -m pytest tests/ -v"`)
Expected: FAIL — `ImportError: cannot import name 'DumpJob'`

- [ ] **Step 3: Implementeer modellen**

Onderaan `weekmenu/models.py`:
```python
class DumpJob(db.Model):
    id = db.Column(db.String(36), primary_key=True)
    status = db.Column(db.String(20), nullable=False, default='processing')  # processing|done|error
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    drafts = db.relationship('RecipeDraft', backref='job', lazy=True, cascade='all, delete-orphan')


class RecipeDraft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('dump_job.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    serves = db.Column(db.Integer, nullable=True)
    instructions = db.Column(db.Text, nullable=True)
    ingredients_json = db.Column(db.Text, nullable=False, default='[]')
    image_path = db.Column(db.String(200), nullable=True)
    source_page = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending|accepted|rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
```

Controleer dat `from datetime import datetime` al bovenaan `models.py` staat; zo niet, toevoegen.

In `requirements.txt` toevoegen:
```
pypdfium2>=4.0.0
Pillow>=10.0.0
```
(pytest bewust niet in requirements.txt — dev-only.)

- [ ] **Step 4: Run test, verwacht PASS**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add weekmenu/models.py tests/ requirements.txt
git commit -m "Dump: DumpJob- en RecipeDraft-modellen + pytest-basis"
```

---

### Task 2: Dump-service — batchprompt, parsing, verwerkingsthread

**Files:**
- Create: `weekmenu/services/dump.py`
- Test: `tests/test_dump_service.py`

**Interfaces:**
- Consumes: `DumpJob`, `RecipeDraft` (Task 1); uit `weekmenu/services/gemini.py`: `_get_gemini_api_key`, `_sanitize_json`, `_build_gemini_ingredients`, `_UNITS_STR`.
- Produces:
  - `parse_batch_response(text: str) -> list[dict]` — elke dict: `{name, serves, instructions, ingredients (app-formaat via _build_gemini_ingredients), photo_page (int|None)}`. Raise `ValueError` bij onparsebare JSON; slaat recepten zonder naam over.
  - `start_dump_job(files) -> str` — slaat uploads op onder `static/uploads/dump/<job_id>/`, maakt DumpJob, start daemon-thread, geeft job_id terug. Raise `ValueError` bij lege/ongeldige invoer.
  - `process_dump_job(app, job_id)` — threadworker (leest bestanden uit de jobmap, dus retry-baar).
  - `retry_dump_job(job_id)` — verwijdert oude drafts, zet status terug op processing, start thread opnieuw.

- [ ] **Step 1: Schrijf failing tests voor parsing**

`tests/test_dump_service.py`:
```python
import json

import pytest

from weekmenu.services.dump import parse_batch_response


def test_parse_batch_response_two_recipes(app):
    payload = json.dumps([
        {"title": "Shakshuka", "yields": 4, "photo_page": 1,
         "ingredients": [{"name": "ei", "amount": 3, "unit": "stuks"}],
         "instructions": "Stap 1. Bak."},
        {"title": "Dal", "yields": 2, "photo_page": None,
         "ingredients": [{"name": "linzen", "amount": 200, "unit": "g"}],
         "instructions": "Stap 1. Kook."},
    ])
    recipes = parse_batch_response("```json\n" + payload + "\n```")
    assert len(recipes) == 2
    assert recipes[0]['name'] == 'Shakshuka'
    assert recipes[0]['photo_page'] == 1
    assert recipes[0]['ingredients'][0]['name'] == 'ei'
    assert 'category' in recipes[0]['ingredients'][0]
    assert recipes[1]['serves'] == 2


def test_parse_batch_response_skips_nameless_and_raises_on_garbage(app):
    recipes = parse_batch_response('[{"title": "", "ingredients": []}, {"title": "Soep", "ingredients": []}]')
    assert [r['name'] for r in recipes] == ['Soep']

    with pytest.raises(ValueError):
        parse_batch_response('dit is geen json')
```

- [ ] **Step 2: Run tests, verwacht FAIL**

Run: `python -m pytest tests/test_dump_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'weekmenu.services.dump'`

- [ ] **Step 3: Implementeer de service**

`weekmenu/services/dump.py`:
```python
import json
import os
import threading
import uuid

from flask import current_app

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft
from weekmenu.services.gemini import (
    _get_gemini_api_key, _sanitize_json, _build_gemini_ingredients, _UNITS_STR,
)

_ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/avif'}

_BATCH_PROMPT = f"""Dit zijn pagina's uit een kookboek (foto's en/of een PDF). Er kunnen MEERDERE recepten in staan.
Extraheer ALLE volledige recepten. Geef ALLEEN geldige JSON terug, geen markdown: een array van recepten.

[
  {{
    "title": "Recept naam",
    "yields": 4,
    "photo_page": 2,
    "ingredients": [
      {{"name": "bloem", "amount": 200, "unit": "g"}}
    ],
    "instructions": "Stap 1. ...\\nStap 2. ..."
  }}
]

Regels:
- Gebruik ALLEEN deze eenheden voor "unit": {_UNITS_STR}
- "amount" is een getal (int of float), of null als onbekend
- Converteer breuken naar decimalen: ½ → 0.5, ¼ → 0.25, "anderhalve" → 1.5
- "name" is de ingrediëntnaam zonder hoeveelheid of eenheid
- "instructions" als enkele string met stappen gescheiden door newlines
- Een recept dat over meerdere pagina's doorloopt is ÉÉN recept: combineer de pagina's
- "photo_page": het 1-gebaseerde paginanummer (over alle invoer heen, in volgorde) met de mooiste foto van het gerecht, of null als er geen gerechtfoto is
- Sla onvolledige fragmenten (alleen een inhoudsopgave, half recept zonder ingrediënten) over
- Als er helemaal geen recept te vinden is: []
"""


def parse_batch_response(text):
    """Parse het Gemini-batchantwoord naar een lijst receptdicts. Raises ValueError."""
    try:
        data = json.loads(_sanitize_json(text))
    except json.JSONDecodeError as e:
        raise ValueError(f'Onleesbaar antwoord van Gemini: {str(e)[:100]}')
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError('Onverwacht antwoordformaat van Gemini')

    recipes = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get('title') or '').strip()
        if not name:
            continue
        photo_page = item.get('photo_page')
        recipes.append({
            'name': name[:100],
            'serves': item.get('yields'),
            'instructions': item.get('instructions') or '',
            'ingredients': _build_gemini_ingredients(item.get('ingredients', [])),
            'photo_page': int(photo_page) if isinstance(photo_page, (int, float)) else None,
        })
    return recipes


def _job_dir(job_id):
    return os.path.join(current_app.static_folder, 'uploads', 'dump', job_id)


def start_dump_job(files):
    """Sla uploads op, maak een DumpJob en start de verwerkingsthread. Returns job_id."""
    saved = []
    job_id = str(uuid.uuid4())
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)

    for i, f in enumerate(files):
        if not f or not f.filename:
            continue
        ctype = f.content_type or ''
        if ctype == 'application/pdf':
            ext = '.pdf'
        elif ctype in _ALLOWED_IMAGE_TYPES:
            ext = {'image/jpeg': '.jpg', 'image/png': '.png',
                   'image/webp': '.webp', 'image/avif': '.avif'}[ctype]
        else:
            continue
        path = os.path.join(job_dir, f'{i:03d}{ext}')
        f.save(path)
        saved.append(path)

    if not saved:
        raise ValueError("Geen bruikbare bestanden (foto's of PDF) ontvangen")

    job = DumpJob(id=job_id, status='processing')
    db.session.add(job)
    db.session.commit()
    _start_thread(job_id)
    return job_id


def retry_dump_job(job_id):
    """Verwijder oude drafts, zet de job terug op processing en verwerk opnieuw."""
    job = DumpJob.query.get_or_404(job_id)
    RecipeDraft.query.filter_by(job_id=job_id).delete()
    job.status = 'processing'
    job.error_message = None
    db.session.commit()
    _start_thread(job_id)


def _start_thread(job_id):
    app = current_app._get_current_object()
    threading.Thread(target=process_dump_job, args=(app, job_id), daemon=True).start()


def process_dump_job(app, job_id):
    """Threadworker: één Gemini-call over alle bestanden in de jobmap, drafts opslaan."""
    with app.app_context():
        job = DumpJob.query.get(job_id)
        try:
            _process(job)
            job.status = 'done'
        except Exception as e:
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower() or 'RESOURCE_EXHAUSTED' in msg:
                msg = 'Gemini is even niet beschikbaar (rate limit). Probeer het over een minuut opnieuw.'
            job.status = 'error'
            job.error_message = msg[:500]
        db.session.commit()


def _process(job):
    from google import genai as _genai
    from google.genai import types as _gtypes

    api_key = _get_gemini_api_key()
    if not api_key:
        raise ValueError('Gemini API key niet geconfigureerd')

    job_dir = _job_dir(job.id)
    file_paths = sorted(
        os.path.join(job_dir, n) for n in os.listdir(job_dir)
        if not n.startswith('page_')  # eerder gerenderde PDF-pagina's overslaan bij retry
    )

    parts = []
    # page_map: 1-gebaseerd paginanummer → (bronpad, pdf_page_index|None)
    page_map = {}
    page_no = 0
    for path in file_paths:
        with open(path, 'rb') as fh:
            data = fh.read()
        if path.endswith('.pdf'):
            parts.append(_gtypes.Part.from_bytes(data=data, mime_type='application/pdf'))
            for pdf_idx in range(_pdf_page_count(path)):
                page_no += 1
                page_map[page_no] = (path, pdf_idx)
        else:
            mime = {'jpg': 'image/jpeg', 'png': 'image/png',
                    'webp': 'image/webp', 'avif': 'image/avif'}[path.rsplit('.', 1)[1]]
            parts.append(_gtypes.Part.from_bytes(data=data, mime_type=mime))
            page_no += 1
            page_map[page_no] = (path, None)

    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=[_BATCH_PROMPT] + parts)
    recipes = parse_batch_response(response.text)

    for idx, r in enumerate(recipes):
        image_path = _resolve_image(job.id, r['photo_page'], page_map)
        db.session.add(RecipeDraft(
            job_id=job.id, name=r['name'],
            serves=int(r['serves']) if r['serves'] else None,
            instructions=r['instructions'],
            ingredients_json=json.dumps(r['ingredients']),
            image_path=image_path, source_page=r['photo_page'], status='pending',
        ))


def _pdf_page_count(path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def _resolve_image(job_id, photo_page, page_map):
    """Kopieer de aangewezen foto of render de PDF-pagina naar static/uploads. Nooit een exception."""
    import hashlib
    import shutil
    try:
        if not photo_page or photo_page not in page_map:
            return None
        src, pdf_idx = page_map[photo_page]
        uploads = os.path.join(current_app.static_folder, 'uploads')
        os.makedirs(uploads, exist_ok=True)

        if pdf_idx is None:
            with open(src, 'rb') as fh:
                fname = hashlib.md5(fh.read()).hexdigest() + os.path.splitext(src)[1]
            shutil.copyfile(src, os.path.join(uploads, fname))
            return os.path.join('static/uploads', fname)

        import pypdfium2 as pdfium
        rendered = os.path.join(_job_dir(job_id), f'page_{pdf_idx}.jpg')
        pdf = pdfium.PdfDocument(src)
        try:
            pil = pdf[pdf_idx].render(scale=2.0).to_pil()
            pil.convert('RGB').save(rendered, 'JPEG', quality=85)
        finally:
            pdf.close()
        with open(rendered, 'rb') as fh:
            fname = hashlib.md5(fh.read()).hexdigest() + '.jpg'
        shutil.copyfile(rendered, os.path.join(uploads, fname))
        return os.path.join('static/uploads', fname)
    except Exception:
        current_app.logger.warning('Dump %s: afbeelding voor pagina %s mislukt', job_id, photo_page, exc_info=True)
        return None
```

- [ ] **Step 4: Run tests, verwacht PASS**

Run: `python -m pytest tests/ -v`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add weekmenu/services/dump.py tests/test_dump_service.py
git commit -m "Dump: batchprompt, antwoord-parsing en verwerkingsthread"
```

---

### Task 3: Dump-routes (upload, status, accept/reject, retry, share)

**Files:**
- Create: `weekmenu/routes/dump.py`
- Modify: `weekmenu/routes/__init__.py`
- Test: `tests/test_dump_routes.py`

**Interfaces:**
- Consumes: Task 1-modellen; Task 2 `start_dump_job`, `retry_dump_job`; uit `weekmenu/services/recipes.py`: `_resolve_or_create_ingredient`; uit `weekmenu/services/units.py`: `_normalize_ri_unit`.
- Produces routes:
  - `GET /dump` → template `dump.html` (Task 4) met `drafts` (alle pending), `jobs` (processing/error), `cookbooks`.
  - `POST /dump/upload` (multipart, veld `files`) → `{status, job_id}` of 400.
  - `POST /dump/share` (share-target, veld `files`) → redirect 303 naar `/dump`.
  - `GET /dump/status/<job_id>` → `{status, error_message, drafts: [serialize_draft…]}`.
  - `GET /dump/draft/<int:id>` → prefill-payload, zelfde vorm als `/recipe/from-photo`-succes: `{status:'success', draft_id, name, serves, instructions, ingredients, image_path, url: None}`.
  - `POST /dump/draft/<int:id>/accept` (JSON body `{cookbook_id}`) → maakt Recipe + RecipeIngredients, draft → `accepted`, response `{status:'success', recipe_id}`.
  - `POST /dump/draft/<int:id>/reject` → draft → `rejected`.
  - `POST /dump/job/<job_id>/retry` → herstart verwerking.

- [ ] **Step 1: Schrijf failing tests**

`tests/test_dump_routes.py`:
```python
import json

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft, Recipe


def _make_draft(app):
    job = DumpJob(id='job-1', status='done')
    draft = RecipeDraft(
        job_id='job-1', name='Dal', serves=2,
        instructions='Stap 1. Kook de linzen.',
        ingredients_json=json.dumps([
            {'name': 'rode linzen', 'amount': 200, 'unit': 'g', 'category': 'overig'},
            {'name': 'ui', 'amount': 1, 'unit': 'stuks', 'category': 'groente'},
        ]),
        status='pending',
    )
    db.session.add_all([job, draft])
    db.session.commit()
    return draft


def test_status_endpoint_lists_drafts(app, client):
    _make_draft(app)
    resp = client.get('/dump/status/job-1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'done'
    assert data['drafts'][0]['name'] == 'Dal'
    assert len(data['drafts'][0]['ingredients']) == 2


def test_accept_creates_recipe_and_marks_draft(app, client):
    draft = _make_draft(app)
    resp = client.post(f'/dump/draft/{draft.id}/accept', json={'cookbook_id': None})
    assert resp.status_code == 200
    recipe_id = resp.get_json()['recipe_id']

    recipe = db.session.get(Recipe, recipe_id)
    assert recipe.name == 'Dal'
    assert recipe.serves == 2
    assert len(recipe.ingredients) == 2
    assert db.session.get(RecipeDraft, draft.id).status == 'accepted'


def test_reject_marks_draft(app, client):
    draft = _make_draft(app)
    resp = client.post(f'/dump/draft/{draft.id}/reject')
    assert resp.status_code == 200
    assert db.session.get(RecipeDraft, draft.id).status == 'rejected'


def test_upload_without_files_is_400(app, client):
    resp = client.post('/dump/upload', data={})
    assert resp.status_code == 400


def test_draft_prefill_payload(app, client):
    draft = _make_draft(app)
    data = client.get(f'/dump/draft/{draft.id}').get_json()
    assert data['status'] == 'success'
    assert data['draft_id'] == draft.id
    assert data['name'] == 'Dal'
    assert data['ingredients'][1]['name'] == 'ui'
```

- [ ] **Step 2: Run tests, verwacht FAIL**

Run: `python -m pytest tests/test_dump_routes.py -v`
Expected: FAIL — 404's (blueprint bestaat niet)

- [ ] **Step 3: Implementeer routes**

`weekmenu/routes/dump.py`:
```python
import json

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from weekmenu.extensions import db
from weekmenu.models import Cookbook, DumpJob, Recipe, RecipeDraft, RecipeIngredient
from weekmenu.services.dump import retry_dump_job, start_dump_job
from weekmenu.services.recipes import _resolve_or_create_ingredient
from weekmenu.services.units import _normalize_ri_unit

bp = Blueprint('dump', __name__)


def serialize_draft(d):
    return {
        'id': d.id,
        'job_id': d.job_id,
        'name': d.name,
        'serves': d.serves,
        'instructions': d.instructions,
        'ingredients': json.loads(d.ingredients_json or '[]'),
        'image_path': d.image_path,
        'status': d.status,
    }


@bp.route('/dump')
def dump_page():
    drafts = RecipeDraft.query.filter_by(status='pending').order_by(RecipeDraft.created_at).all()
    jobs = DumpJob.query.filter(DumpJob.status.in_(['processing', 'error'])) \
                        .order_by(DumpJob.created_at.desc()).all()
    cookbooks = Cookbook.query.filter_by(is_archived=False).order_by(Cookbook.name).all()
    return render_template('dump.html',
                           drafts=[serialize_draft(d) for d in drafts],
                           jobs=[{'id': j.id, 'status': j.status, 'error_message': j.error_message} for j in jobs],
                           cookbooks=cookbooks)


@bp.route('/dump/upload', methods=['POST'])
def dump_upload():
    files = request.files.getlist('files')
    try:
        job_id = start_dump_job(files)
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    return jsonify({'status': 'success', 'job_id': job_id})


@bp.route('/dump/share', methods=['POST'])
def dump_share():
    """PWA share-target: bestanden delen vanaf de telefoon."""
    files = request.files.getlist('files')
    try:
        start_dump_job(files)
    except ValueError:
        pass  # lege share: gewoon naar de pagina
    return redirect(url_for('dump.dump_page'), code=303)


@bp.route('/dump/status/<job_id>')
def dump_status(job_id):
    job = DumpJob.query.get_or_404(job_id)
    drafts = RecipeDraft.query.filter_by(job_id=job_id, status='pending') \
                              .order_by(RecipeDraft.created_at).all()
    return jsonify({'status': job.status,
                    'error_message': job.error_message,
                    'drafts': [serialize_draft(d) for d in drafts]})


@bp.route('/dump/job/<job_id>/retry', methods=['POST'])
def dump_retry(job_id):
    retry_dump_job(job_id)
    return jsonify({'status': 'success'})


@bp.route('/dump/draft/<int:id>')
def dump_draft(id):
    d = RecipeDraft.query.get_or_404(id)
    payload = serialize_draft(d)
    payload.update({'status': 'success', 'draft_id': d.id, 'url': None})
    return jsonify(payload)


@bp.route('/dump/draft/<int:id>/accept', methods=['POST'])
def dump_draft_accept(id):
    d = RecipeDraft.query.get_or_404(id)
    body = request.get_json(silent=True) or {}
    cookbook_id = body.get('cookbook_id') or None

    recipe = Recipe(name=d.name, serves=d.serves, cookbook_id=cookbook_id,
                    page=d.source_page, image_path=d.image_path,
                    instructions=d.instructions or None)
    db.session.add(recipe)
    db.session.flush()

    for ing in json.loads(d.ingredients_json or '[]'):
        ingredient = _resolve_or_create_ingredient(ing.get('name', ''), ing.get('category'))
        if not ingredient:
            continue
        raw_amount = float(ing['amount']) if ing.get('amount') else 0
        norm_unit, norm_amount = _normalize_ri_unit(ingredient, ing.get('unit') or '', raw_amount)
        db.session.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ingredient.id,
                                        amount=norm_amount, unit=norm_unit))

    d.status = 'accepted'
    db.session.commit()
    return jsonify({'status': 'success', 'recipe_id': recipe.id})


@bp.route('/dump/draft/<int:id>/reject', methods=['POST'])
def dump_draft_reject(id):
    d = RecipeDraft.query.get_or_404(id)
    d.status = 'rejected'
    db.session.commit()
    return jsonify({'status': 'success'})
```

In `weekmenu/routes/__init__.py`: import toevoegen en `dump_bp` opnemen in de registratielijst:
```python
from weekmenu.routes.dump import bp as dump_bp
```
en in de lijst in `register_blueprints`: `..., pantry_bp, dump_bp]`.

Let op: `render_template('dump.html', ...)` bestaat pas na Task 4 — de route-tests raken `/dump` (GET) niet aan, dus dat is oké.

- [ ] **Step 4: Run tests, verwacht PASS**

Run: `python -m pytest tests/ -v`
Expected: alle tests PASS

- [ ] **Step 5: Commit**

```bash
git add weekmenu/routes/dump.py weekmenu/routes/__init__.py tests/test_dump_routes.py
git commit -m "Dump: routes voor upload, status, accept/reject en retry"
```

---

### Task 4: `/dump`-pagina (dropzone, polling, review-kaarten)

**Files:**
- Create: `templates/dump.html`

**Interfaces:**
- Consumes: Task 3-routes en context (`drafts`, `jobs`, `cookbooks`); base-template `templates/base.html` (block-namen overnemen uit bijv. `recipes.html` — controleer bij implementatie welke blocks base.html definieert en gebruik dezelfde).

- [ ] **Step 1: Bouw de template**

`templates/dump.html` (blocks aanpassen aan wat `base.html` daadwerkelijk gebruikt):
```html
{% extends "base.html" %}
{% block content %}
<div class="max-w-3xl mx-auto space-y-6">
    <h1 class="text-2xl font-bold">Recepten-dump</h1>
    <p class="text-sm text-[#6B6B6B]">Gooi hier foto's van kookboekpagina's of een PDF in.
       De recepten worden automatisch herkend en verschijnen hieronder ter controle.</p>

    <!-- Dropzone -->
    <div id="dropzone"
         class="border-2 border-dashed border-[#E8E4DC] rounded-lg p-8 text-center cursor-pointer hover:border-[#8B4513] transition-colors">
        <input type="file" id="fileInput" class="hidden" multiple
               accept="image/*,application/pdf" onchange="startUpload(this.files)">
        <p class="font-medium">Sleep foto's of een PDF hierheen</p>
        <p class="text-sm text-[#6B6B6B] mt-1">of klik om te kiezen</p>
    </div>

    <!-- Job-status -->
    <div id="jobStatus" class="hidden text-sm flex items-center gap-2">
        <img id="jobBanana" src="/static/uploads/dancing-banana.gif" class="h-10 hidden">
        <span id="jobStatusText"></span>
        <button id="retryBtn" class="hidden underline text-[#8B4513]" onclick="retryJob()">Opnieuw proberen</button>
    </div>

    <!-- Kookboek-keuze voor de hele batch -->
    <div class="flex items-center gap-3">
        <label class="text-sm font-medium">Kookboek voor opgeslagen recepten:</label>
        <select id="cookbookSelect" class="border border-[#E8E4DC] rounded px-2 py-1 text-sm">
            <option value="">— Geen —</option>
            {% for cb in cookbooks %}
            <option value="{{ cb.id }}">{{ cb.name }}</option>
            {% endfor %}
        </select>
    </div>

    <!-- Draft-kaarten -->
    <div id="draftList" class="space-y-4"></div>
</div>

<script>
const initialDrafts = {{ drafts | tojson }};
const initialJobs = {{ jobs | tojson }};
let activeJobId = null;
let pollTimer = null;

/* ── Dropzone ── */
const dz = document.getElementById('dropzone');
dz.onclick = () => document.getElementById('fileInput').click();
dz.ondragover = e => { e.preventDefault(); dz.classList.add('border-[#8B4513]'); };
dz.ondragleave = () => dz.classList.remove('border-[#8B4513]');
dz.ondrop = e => { e.preventDefault(); dz.classList.remove('border-[#8B4513]'); startUpload(e.dataTransfer.files); };

async function startUpload(files) {
    if (!files || files.length === 0) return;
    const fd = new FormData();
    Array.from(files).forEach(f => fd.append('files', f));
    setJobStatus('Uploaden...', true);
    try {
        const resp = await fetch('/dump/upload', { method: 'POST', body: fd });
        const data = await resp.json();
        if (data.status !== 'success') { setJobError(data.message); return; }
        activeJobId = data.job_id;
        setJobStatus('Recepten worden herkend...', true);
        pollTimer = setInterval(pollJob, 2500);
    } catch (err) {
        setJobError(err.message);
    }
}

async function pollJob() {
    const resp = await fetch(`/dump/status/${activeJobId}`);
    const data = await resp.json();
    if (data.status === 'processing') return;
    clearInterval(pollTimer);
    if (data.status === 'error') { setJobError(data.error_message); return; }
    setJobStatus(`Klaar: ${data.drafts.length} recept(en) herkend.`, false);
    data.drafts.forEach(renderCard);
}

async function retryJob() {
    if (!activeJobId) return;
    await fetch(`/dump/job/${activeJobId}/retry`, { method: 'POST' });
    setJobStatus('Opnieuw bezig...', true);
    pollTimer = setInterval(pollJob, 2500);
}

function setJobStatus(text, busy) {
    const box = document.getElementById('jobStatus');
    box.classList.remove('hidden');
    box.className = 'text-sm text-[#6B6B6B] flex items-center gap-2';
    document.getElementById('jobStatusText').textContent = text;
    document.getElementById('jobBanana').classList.toggle('hidden', !busy);
    document.getElementById('retryBtn').classList.add('hidden');
}

function setJobError(msg) {
    const box = document.getElementById('jobStatus');
    box.classList.remove('hidden');
    box.className = 'text-sm text-red-600 flex items-center gap-2';
    document.getElementById('jobStatusText').textContent = 'Fout: ' + (msg || 'onbekend');
    document.getElementById('jobBanana').classList.add('hidden');
    document.getElementById('retryBtn').classList.toggle('hidden', !activeJobId);
}

/* ── Draft-kaarten ── */
function renderCard(d) {
    const list = document.getElementById('draftList');
    const card = document.createElement('div');
    card.id = `draft-${d.id}`;
    card.className = 'border border-[#E8E4DC] rounded-lg p-4 flex gap-4';
    const ingHtml = d.ingredients.map(i =>
        `<li>${i.amount ?? ''} ${i.unit ?? ''} ${i.name}</li>`).join('');
    card.innerHTML = `
        ${d.image_path ? `<img src="/${d.image_path}" class="w-28 h-28 object-cover rounded shrink-0">` : ''}
        <div class="flex-1 min-w-0">
            <h3 class="font-bold">${d.name}</h3>
            ${d.serves ? `<p class="text-sm text-[#6B6B6B]">${d.serves} personen</p>` : ''}
            <ul class="text-sm mt-1 list-disc list-inside text-[#6B6B6B] max-h-28 overflow-y-auto">${ingHtml}</ul>
            <div class="flex gap-2 mt-3">
                <button onclick="acceptDraft(${d.id})" class="px-3 py-1.5 bg-[#8B4513] text-white rounded text-sm">✓ Opslaan</button>
                <a href="/recipe/new?draft=${d.id}" class="px-3 py-1.5 border border-[#E8E4DC] rounded text-sm">✎ Aanpassen</a>
                <button onclick="rejectDraft(${d.id})" class="px-3 py-1.5 border border-[#E8E4DC] text-red-600 rounded text-sm">✗ Weg</button>
            </div>
        </div>`;
    list.appendChild(card);
}

async function acceptDraft(id) {
    const cookbook_id = document.getElementById('cookbookSelect').value || null;
    const resp = await fetch(`/dump/draft/${id}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cookbook_id }),
    });
    if ((await resp.json()).status === 'success') document.getElementById(`draft-${id}`).remove();
}

async function rejectDraft(id) {
    await fetch(`/dump/draft/${id}/reject`, { method: 'POST' });
    document.getElementById(`draft-${id}`).remove();
}

/* ── Init: bestaande drafts + lopende jobs ── */
initialDrafts.forEach(renderCard);
initialJobs.forEach(j => {
    activeJobId = j.id;
    if (j.status === 'processing') {
        setJobStatus('Recepten worden herkend...', true);
        pollTimer = setInterval(pollJob, 2500);
    } else if (j.status === 'error') {
        setJobError(j.error_message);
    }
});
</script>
{% endblock %}
```

- [ ] **Step 2: Handmatige verificatie op dev**

```bash
docker compose -f docker-compose.dev.yml up -d --build
```
Open `http://<server>:5002/dump`: pagina laadt, dropzone reageert op klik en drag-over. Upload 2-3 kookboekfoto's: banaan verschijnt, na afloop kaarten met naam/ingrediënten. "✓ Opslaan" laat het recept verschijnen onder `http://<server>:5002/recipes`; "✗ Weg" verwijdert de kaart en na refresh blijft hij weg.

- [ ] **Step 3: Run tests (regressie)**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add templates/dump.html
git commit -m "Dump: review-pagina met dropzone, polling en draft-kaarten"
```

---

### Task 5: "Aanpassen"-prefill in het bestaande receptformulier

**Files:**
- Modify: `templates/new_recipe.html` (script-gedeelte, onderaan)
- Modify: `weekmenu/routes/recipes.py:224-320` (`new_recipe` POST)
- Test: `tests/test_dump_routes.py` (test toevoegen)

**Interfaces:**
- Consumes: `GET /dump/draft/<id>` (Task 3, zelfde payload-vorm als `/recipe/from-photo`); bestaande prefill-elementen in `new_recipe.html`: `fieldName`, `fieldServes`, `quill`, `fieldImagePath`, `importedImagePreview`, `addIngredientRow(name, amount, unit, category)`.
- Produces: `/recipe/new?draft=<id>` opent het formulier voorgevuld; na opslaan wordt de draft `accepted`.

- [ ] **Step 1: Schrijf failing test**

Toevoegen aan `tests/test_dump_routes.py`:
```python
def test_new_recipe_post_with_draft_id_accepts_draft(app, client):
    draft = _make_draft(app)
    resp = client.post('/recipe/new', data={
        'name': 'Dal (aangepast)', 'serves': '2', 'page': '',
        'draft_id': str(draft.id),
    })
    assert resp.status_code == 302
    assert db.session.get(RecipeDraft, draft.id).status == 'accepted'
```

- [ ] **Step 2: Run test, verwacht FAIL**

Run: `python -m pytest tests/test_dump_routes.py::test_new_recipe_post_with_draft_id_accepts_draft -v`
Expected: FAIL — draft-status blijft `pending`

- [ ] **Step 3: Implementeer**

In `weekmenu/routes/recipes.py`, in de `new_recipe` POST-tak, direct vóór `return redirect(...)`:
```python
        draft_id = request.form.get('draft_id')
        if draft_id:
            from weekmenu.models import RecipeDraft
            draft = db.session.get(RecipeDraft, int(draft_id))
            if draft:
                draft.status = 'accepted'
                db.session.commit()
```

In `templates/new_recipe.html`:
1. Hidden veld in het formulier (naast de bestaande hidden fields zoals `fieldImagePath`):
```html
<input type="hidden" name="draft_id" id="fieldDraftId" value="">
```
2. Onderaan het script-blok, na de bestaande on-load IIFE:
```javascript
/* ── Prefill vanuit een dump-draft (?draft=<id>) ── */
(async function() {
    const draftId = new URLSearchParams(location.search).get('draft');
    if (!draftId) return;
    try {
        const resp = await fetch(`/dump/draft/${draftId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        document.getElementById('fieldDraftId').value = draftId;
        if (data.name) document.getElementById('fieldName').value = data.name;
        if (data.serves) document.getElementById('fieldServes').value = data.serves;
        if (data.instructions) quill.root.innerHTML = data.instructions.replace(/\n/g, '<br>');
        if (data.image_path) {
            document.getElementById('fieldImagePath').value = data.image_path;
            const preview = document.getElementById('importedImagePreview');
            preview.src = '/' + data.image_path;
            preview.classList.remove('hidden');
        }
        if (data.ingredients && data.ingredients.length > 0) {
            document.getElementById('ingredients').innerHTML = '';
            data.ingredients.forEach(ing => addIngredientRow(ing.name, ing.amount, ing.unit, ing.category));
        }
    } catch (e) {}
})();
```
Controleer bij implementatie de exacte element-id's in `new_recipe.html` (o.a. of de instructie-editor `quill` heet) en pas aan indien anders.

- [ ] **Step 4: Run tests, verwacht PASS**

Run: `python -m pytest tests/ -v`
Expected: PASS. Plus kort handmatig op dev: kaart → "✎ Aanpassen" → formulier staat voorgevuld → opslaan → kaart is bij terugkeer op `/dump` verdwenen.

- [ ] **Step 5: Commit**

```bash
git add templates/new_recipe.html weekmenu/routes/recipes.py tests/test_dump_routes.py
git commit -m "Dump: draft aanpassen via voorgevuld receptformulier"
```

---

### Task 6: PWA share-target

**Files:**
- Modify: `static/manifest.json`

**Interfaces:**
- Consumes: `POST /dump/share` (Task 3).

- [ ] **Step 1: Voeg share_target toe**

In `static/manifest.json`, als top-level key naast de bestaande velden:
```json
"share_target": {
  "action": "/dump/share",
  "method": "POST",
  "enctype": "multipart/form-data",
  "params": {
    "files": [
      { "name": "files", "accept": ["image/*", "application/pdf"] }
    ]
  }
}
```
Valideer dat het bestand geldige JSON blijft: `python -m json.tool static/manifest.json`.

- [ ] **Step 2: Handmatige verificatie op Android**

PWA opnieuw installeren (of updaten; Chrome pikt manifest-wijzigingen bij herbezoek op). Vanuit de galerij 2 foto's delen → "Weekmenu" verschijnt in het deelmenu → app opent op `/dump` en de verwerking loopt. (Vereist dat de dev-site via de PWA geïnstalleerd is; anders testen na promotie naar prod en dat hier noteren.)

- [ ] **Step 3: Commit**

```bash
git add static/manifest.json
git commit -m "Dump: PWA share-target voor foto's en PDF"
```

---

### Task 7: End-to-end test op dev + spec-check

**Files:** geen nieuwe; verificatie.

- [ ] **Step 1: Volledige flow met echte input**

Op `http://<server>:5002/dump`:
1. Tinyscanner-PDF met ≥2 recepten uploaden → juiste splitsing, per recept een kaart, afbeelding uit de juiste pagina.
2. Batch losse foto's (3+ pagina's, waarvan één recept over 2 pagina's) → doorlopend recept is één kaart.
3. Eén kaart opslaan met kookboek-selectie → recept correct in `/recipes`, ingrediënten gematcht (bestaande ingrediënten hergebruikt, nieuwe aangemaakt).
4. Kapotte invoer (bijv. foto van iets zonder recept) → nette melding of 0 kaarten, geen crash.
5. Fout forceren (API-key tijdelijk leeg in container-env) → job op error met melding + werkende retry na herstel.

- [ ] **Step 2: Regressietests + spec-dekking**

Run: `python -m pytest tests/ -v` → PASS. Spec naast het resultaat leggen (`docs/superpowers/specs/2026-07-05-recipe-dump-design.md`): elk spec-punt afvinken.

- [ ] **Step 3: Eindcommit indien er nog fixes waren**

```bash
git add -A && git commit -m "Dump: fixes uit end-to-end test"
```
