# Draft-afbeelding croppen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ✂️-knop op de /dump-reviewkaarten die de draft-afbeelding in een Cropper.js-modal opent en server-side (Pillow) bijsnijdt, altijd vanuit het bewaarde origineel.

**Architecture:** Bestaande recepten-dump-feature (branch `recepten-dump`): model `RecipeDraft` krijgt kolom `original_image_path`; nieuw endpoint `POST /dump/draft/<id>/crop` in `weekmenu/routes/dump.py`; modal + Cropper.js (CDN) in `templates/dump.html`. Spec: `docs/superpowers/specs/2026-07-07-draft-crop-design.md`.

**Tech Stack:** Flask/SQLAlchemy, Pillow (al aanwezig), Cropper.js 1.6.2 via jsdelivr-CDN, pytest (bestaande suite in `tests/`).

## Global Constraints

- Testen op dev: `docker compose -f docker-compose.dev.yml up -d --build`, poort 5002. Testsuite: `docker compose -f docker-compose.dev.yml exec -T weekmenu-dev sh -c "pip install -q pytest; python -m pytest tests/ -v"` (of lokaal `python3 -m pytest tests/ -v` als deps aanwezig).
- Commits op branch `recepten-dump`, Nederlandse boodschap, GEEN Co-Authored-By/attributieregels.
- UI-teksten Nederlands; stijl zoals bestaande dump.html (accent `#8B4513`, borders `#E8E4DC`).
- `image_path`-formaat blijft `static/uploads/<md5>.<ext>` (zoals bestaand).
- Crop-coördinaten in de API zijn fracties 0–1 t.o.v. het bronbeeld: `{x, y, width, height}`.

---

### Task 1: Modelveld `original_image_path` + migratie + serialisatie

**Files:**
- Modify: `weekmenu/models.py` (class `RecipeDraft`)
- Modify: `weekmenu/migrations.py` (nieuwe `_migrate_v7`, target 6 → 7)
- Modify: `weekmenu/routes/dump.py` (`serialize_draft`)
- Test: `tests/test_dump_routes.py`

**Interfaces:**
- Produces: `RecipeDraft.original_image_path` (String(200), nullable); `serialize_draft(d)` bevat key `original_image_path`.

- [ ] **Step 1: Schrijf failing test**

Toevoegen aan `tests/test_dump_routes.py`:
```python
def test_serialize_draft_includes_original_image_path(app, client):
    draft = _make_draft(app)
    draft.original_image_path = 'static/uploads/orig.png'
    db.session.commit()
    data = client.get(f'/dump/draft/{draft.id}').get_json()
    assert data['original_image_path'] == 'static/uploads/orig.png'
```

- [ ] **Step 2: Run test, verwacht FAIL**

Run: `python3 -m pytest tests/test_dump_routes.py::test_serialize_draft_includes_original_image_path -v`
Expected: FAIL — `AttributeError: 'RecipeDraft' object has no attribute 'original_image_path'`

- [ ] **Step 3: Implementeer**

In `weekmenu/models.py`, class `RecipeDraft`, na de regel met `image_path`:
```python
    original_image_path = db.Column(db.String(200), nullable=True)
```

In `weekmenu/migrations.py`: nieuwe functie naast de bestaande `_migrate_v6`:
```python
def _migrate_v7(conn):
    """Crop-functie: original_image_path op recipe_draft."""
    cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe_draft)')).fetchall()]
    if 'original_image_path' not in cols:
        try:
            conn.execute(text('ALTER TABLE recipe_draft ADD COLUMN original_image_path VARCHAR(200)'))
        except OperationalError:
            pass
```
En in `migrate_db()`: na het `if current < 6:`-blok toevoegen:
```python
        if current < 7:
            _migrate_v7(conn)
```
en `target = 6` wijzigen naar `target = 7`.

In `weekmenu/routes/dump.py`, in `serialize_draft`, na `'image_path': d.image_path,`:
```python
        'original_image_path': d.original_image_path,
```

- [ ] **Step 4: Run alle tests, verwacht PASS**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add weekmenu/models.py weekmenu/migrations.py weekmenu/routes/dump.py tests/test_dump_routes.py
git commit -m "Crop: original_image_path op RecipeDraft + migratie v7"
```

---

### Task 2: Crop-endpoint `POST /dump/draft/<id>/crop`

**Files:**
- Modify: `weekmenu/routes/dump.py`
- Test: `tests/test_dump_routes.py`

**Interfaces:**
- Consumes: `RecipeDraft.original_image_path` (Task 1); bestaand `_make_draft`-patroon in de testfile.
- Produces: `POST /dump/draft/<int:id>/crop`, JSON-body `{x, y, width, height}` (fracties 0–1) → `{status:'success', image_path:<nieuw pad>}` of 400/404 met `{status:'error', message}`.

- [ ] **Step 1: Schrijf failing tests**

Toevoegen aan `tests/test_dump_routes.py` (bovenaan staat al `import json`; voeg `import os` toe als die ontbreekt):
```python
def _make_draft_with_image(app):
    from PIL import Image
    draft = _make_draft(app)
    uploads = os.path.join(app.static_folder, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    img = Image.new('RGBA', (100, 80), (200, 30, 30, 255))  # PNG met alpha
    img.save(os.path.join(uploads, 'bron.png'))
    draft.image_path = 'static/uploads/bron.png'
    db.session.commit()
    return draft


def test_crop_creates_new_image_and_keeps_original(app, client):
    from PIL import Image
    draft = _make_draft_with_image(app)
    resp = client.post(f'/dump/draft/{draft.id}/crop',
                       json={'x': 0.25, 'y': 0.25, 'width': 0.5, 'height': 0.5})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'
    new_path = data['image_path']
    assert new_path != 'static/uploads/bron.png'
    assert new_path.endswith('.jpg')

    d = db.session.get(RecipeDraft, draft.id)
    assert d.image_path == new_path
    assert d.original_image_path == 'static/uploads/bron.png'

    out = Image.open(os.path.join(app.static_folder, new_path.replace('static/', '', 1)))
    assert out.size == (50, 40)

    # tweede crop snijdt weer uit het 100x80-origineel
    resp2 = client.post(f'/dump/draft/{draft.id}/crop',
                        json={'x': 0, 'y': 0, 'width': 1, 'height': 1})
    assert resp2.status_code == 200
    d = db.session.get(RecipeDraft, draft.id)
    assert d.original_image_path == 'static/uploads/bron.png'
    out2 = Image.open(os.path.join(app.static_folder, d.image_path.replace('static/', '', 1)))
    assert out2.size == (100, 80)


def test_crop_invalid_coords_and_missing_image(app, client):
    draft = _make_draft_with_image(app)
    for bad in [{'x': -0.1, 'y': 0, 'width': 0.5, 'height': 0.5},
                {'x': 0.8, 'y': 0, 'width': 0.5, 'height': 0.5},
                {'x': 0, 'y': 0, 'width': 0, 'height': 0.5},
                {'x': 0, 'y': 0}]:
        assert client.post(f'/dump/draft/{draft.id}/crop', json=bad).status_code == 400

    kaal = _make_draft(app)  # zonder afbeelding
    assert client.post(f'/dump/draft/{kaal.id}/crop',
                       json={'x': 0, 'y': 0, 'width': 1, 'height': 1}).status_code == 400
```

- [ ] **Step 2: Run tests, verwacht FAIL**

Run: `python3 -m pytest tests/test_dump_routes.py -k crop -v`
Expected: FAIL — 404 (route bestaat niet)

- [ ] **Step 3: Implementeer endpoint**

In `weekmenu/routes/dump.py`, imports bovenaan aanvullen met `import hashlib`, `import io`, `import os` en `current_app` bij de flask-import. Nieuwe route na `dump_draft_reject`:
```python
@bp.route('/dump/draft/<int:id>/crop', methods=['POST'])
def dump_draft_crop(id):
    d = RecipeDraft.query.get_or_404(id)
    body = request.get_json(silent=True) or {}
    try:
        x = float(body['x'])
        y = float(body['y'])
        w = float(body['width'])
        h = float(body['height'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'Ongeldige crop-coördinaten'}), 400
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1
            and x + w <= 1.0001 and y + h <= 1.0001):
        return jsonify({'status': 'error', 'message': 'Ongeldige crop-coördinaten'}), 400

    src_rel = d.original_image_path or d.image_path
    if not src_rel:
        return jsonify({'status': 'error', 'message': 'Geen afbeelding om bij te snijden'}), 400
    src_abs = os.path.join(current_app.static_folder, src_rel.replace('static/', '', 1))
    if not os.path.exists(src_abs):
        return jsonify({'status': 'error', 'message': 'Bronafbeelding niet gevonden'}), 404

    from PIL import Image
    try:
        im = Image.open(src_abs)
        im.load()
    except Exception:
        return jsonify({'status': 'error',
                        'message': 'Dit afbeeldingsformaat kan niet bijgesneden worden'}), 400

    width, height = im.size
    left = int(x * width)
    top = int(y * height)
    right = max(left + 1, int((x + w) * width))
    bottom = max(top + 1, int((y + h) * height))
    cropped = im.crop((left, top, right, bottom)).convert('RGB')

    buf = io.BytesIO()
    cropped.save(buf, 'JPEG', quality=85)
    data = buf.getvalue()
    fname = hashlib.md5(data).hexdigest() + '.jpg'
    uploads = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    with open(os.path.join(uploads, fname), 'wb') as f:
        f.write(data)

    if not d.original_image_path:
        d.original_image_path = d.image_path
    d.image_path = os.path.join('static/uploads', fname)
    db.session.commit()
    return jsonify({'status': 'success', 'image_path': d.image_path})
```

- [ ] **Step 4: Run alle tests, verwacht PASS**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add weekmenu/routes/dump.py tests/test_dump_routes.py
git commit -m "Crop: endpoint POST /dump/draft/<id>/crop (Pillow, altijd vanuit origineel)"
```

---

### Task 3: Crop-modal met Cropper.js in dump.html

**Files:**
- Modify: `templates/dump.html`

**Interfaces:**
- Consumes: `POST /dump/draft/<id>/crop` (Task 2), `GET /dump/draft/<id>` met `original_image_path` (Task 1); bestaande JS-helpers `esc()`, `imageUrl()`, `renderCard()` in dump.html.

- [ ] **Step 1: Voeg CDN-includes, modal en JS toe**

1. Direct na `{% block content %}` (vóór de bestaande div) Cropper.js-includes:
```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.css">
<script src="https://cdn.jsdelivr.net/npm/cropperjs@1.6.2/dist/cropper.min.js"></script>
```

2. In `renderCard()` in de actie-knoppenrij, na de ✎ Aanpassen-link, alleen bij een afbeelding:
```javascript
${img ? `<button onclick="openCrop(${d.id})" class="px-3 py-1.5 border border-[#E8E4DC] rounded text-sm">✂️ Bijsnijden</button>` : ''}
```

3. Modal-HTML, vlak vóór het `<script>`-blok:
```html
<!-- Crop-modal -->
<div id="cropModal" class="hidden fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4"
     onclick="if (event.target === this) closeCrop()">
    <div class="bg-white rounded-lg p-4 max-w-[90vw] max-h-[90vh] flex flex-col gap-3">
        <h3 class="font-bold">Afbeelding bijsnijden</h3>
        <div class="overflow-hidden max-h-[70vh]">
            <img id="cropImage" class="max-w-full block">
        </div>
        <p id="cropError" class="hidden text-sm text-red-600"></p>
        <div class="flex gap-2 justify-end">
            <button onclick="closeCrop()" class="px-3 py-1.5 border border-[#E8E4DC] rounded text-sm">Annuleren</button>
            <button onclick="saveCrop()" class="px-3 py-1.5 bg-[#8B4513] text-white rounded text-sm">Opslaan</button>
        </div>
    </div>
</div>
```

4. JS onderaan het bestaande scriptblok:
```javascript
/* ── Croppen ── */
let cropper = null;
let cropDraftId = null;

async function openCrop(id) {
    let src = null;
    try {
        const resp = await fetch(`/dump/draft/${id}`);
        if (!resp.ok) return;
        const data = await resp.json();
        src = imageUrl(data.original_image_path || data.image_path);
    } catch (e) { return; }
    if (!src) return;

    cropDraftId = id;
    const modal = document.getElementById('cropModal');
    const img = document.getElementById('cropImage');
    document.getElementById('cropError').classList.add('hidden');
    modal.classList.remove('hidden');
    if (cropper) { cropper.destroy(); cropper = null; }
    img.onload = () => {
        if (typeof Cropper === 'undefined') {
            showCropError('Bijsnijden niet beschikbaar (library niet geladen)');
            return;
        }
        cropper = new Cropper(img, { viewMode: 1, autoCropArea: 0.8 });
    };
    img.src = src + '?t=' + Date.now();
}

function closeCrop() {
    if (cropper) { cropper.destroy(); cropper = null; }
    document.getElementById('cropModal').classList.add('hidden');
    document.getElementById('cropImage').src = '';
    cropDraftId = null;
}

function showCropError(msg) {
    const el = document.getElementById('cropError');
    el.textContent = msg;
    el.classList.remove('hidden');
}

async function saveCrop() {
    if (!cropper || !cropDraftId) return;
    const cd = cropper.getData();
    const nat = cropper.getImageData();
    const body = {
        x: cd.x / nat.naturalWidth,
        y: cd.y / nat.naturalHeight,
        width: cd.width / nat.naturalWidth,
        height: cd.height / nat.naturalHeight,
    };
    try {
        const resp = await fetch(`/dump/draft/${cropDraftId}/crop`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok || data.status !== 'success') {
            showCropError(data.message || 'Bijsnijden mislukt');
            return;
        }
        const cardImg = document.querySelector(`#draft-${cropDraftId} img`);
        if (cardImg) cardImg.src = imageUrl(data.image_path) + '?t=' + Date.now();
        closeCrop();
    } catch (err) {
        showCropError('Bijsnijden mislukt: ' + err.message);
    }
}
```

- [ ] **Step 2: Handmatige verificatie op dev**

```bash
docker compose -f docker-compose.dev.yml up -d --build
```
Op `http://<server>:5002/dump`: er staan nog pending drafts uit de E2E-test met afbeelding? Zo niet: upload een foto zodat er een kaart met afbeelding ontstaat. Controleer: ✂️-knop alleen op kaarten mét afbeelding; klik opent modal met crop-kader; kader slepen en Opslaan → kaartafbeelding toont direct de uitsnede; nogmaals ✂️ → modal toont weer het volledige origineel; Annuleren en klik-buiten sluiten de modal.

- [ ] **Step 3: Run tests (regressie)**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS

- [ ] **Step 4: Commit**

```bash
git add templates/dump.html
git commit -m "Crop: Cropper.js-modal op de dump-reviewkaarten"
```
