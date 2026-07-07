# Eén boodschappenlijst + weeknavigatie Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eén doorlopende boodschappenlijst op `/boodschappen` (afvinken i.p.v. wissen, losse recepten via QuickAddItem, AH-verzenden vinkt automatisch af) plus een prominente weekbalk met onthouden-laatste-week.

**Architecture:** De lijst blijft per week afgeleid (`_build_shopping_dict`); nieuw is een aggregatielaag `build_combined_shopping_list()` over een weekvenster, met afvink-status in een nieuwe tabel `ShoppingCheck`. De AH-verzendkern wordt uit de route gerefactored naar een servicefunctie zodat zowel de per-week-route als het nieuwe gecombineerde endpoint hem gebruiken. Spec: `docs/superpowers/specs/2026-07-07-single-shopping-list-design.md`.

**Tech Stack:** Flask/SQLAlchemy, bestaande pytest-suite in `tests/`, Tailwind-stijl zoals bestaande templates.

## Global Constraints

- Testen: `python3 -m pytest tests/ -v` (lokaal) of in de dev-container (`docker compose -f docker-compose.dev.yml exec -T weekmenu-dev sh -c "pip install -q pytest; python -m pytest tests/ -v"`). Dev-UI op poort 5002.
- Commits op branch `main` is NIET toegestaan tijdens de bouw: werk op branch **`boodschappenlijst`** (maak die in Taak 1 vanaf main). Nederlandse commits, GEEN Co-Authored-By/attributieregels.
- UI-teksten Nederlands; stijl zoals bestaande templates (accent `#8B4513`, borders `#E8E4DC`/`#D4CEC4`, knopstijl zwart `#2C2C2C`).
- Weekvenster: ISO-weken van (vandaag − 7 dagen) t/m (vandaag + 14 dagen); handmatige weken (QuickAddItem/CustomShoppingIngredient) tot 4 weken terug tellen ook mee.
- Afvinken is per ingrediënt per week (eenheid-onafhankelijk); afgevinkt met `checked_at` ouder dan 14 dagen wordt niet meer getoond.
- AH-verzenden: één gebundeld request; bij succes alléén verzonden (gekoppelde) items afvinken met `via_ah=True`; bij fout niets afvinken.
- GEEN weeklabels in de lijst-UI.

---

### Task 1: Branch + `ShoppingCheck`-model + aggregatieservice

**Files:**
- Modify: `weekmenu/models.py` (onderaan)
- Modify: `weekmenu/services/shopping.py`
- Test: `tests/test_combined_shopping.py` (nieuw)

**Interfaces:**
- Produces:
  - `ShoppingCheck` model: `id`, `year`, `week_number`, `ingredient_id` (FK ingredient.id), `checked_at` (datetime, default now), `via_ah` (bool, default False); unique constraint (`year`,`week_number`,`ingredient_id`), naam `uq_check_week_ingredient`.
  - `window_weeks(today=None) -> list[(year, week)]` — ISO-weken van vandaag−7d t/m vandaag+14d, plus weken tot 4 weken terug die QuickAddItem- of CustomShoppingIngredient-rijen hebben; gededupliceerd, gesorteerd.
  - `build_combined_shopping_list(today=None) -> dict` met keys:
    - `open`: lijst rowdicts (zelfde velden als de bestaande per-week-items in `routes/shopping.py:44-66`: `name`, `amount`, `amount_display`, `unit`, `category`, `ingredient_id`, `ah_product_*`, `default_qty`, `qty`) — `amount` = som van niet-afgevinkte weken, `qty` = som per open week van override of `_calc_ah_qty`.
    - `checked`: zelfde rowdicts + `via_ah` (bool) en `checked_at` (laatste), alleen rijen waarvan álle bijdragende weken afgevinkt zijn en `checked_at` ≤ 14 dagen oud.
    - `weeks_by_ingredient`: dict `ingredient_id -> list[(year, week)]` (alle bijdragende weken, voor de check-endpoints).
    - `quick_add`: lijst `{id, recipe_id, recipe_name, people_count}` van QuickAddItems in de venster+handmatige weken.

- [ ] **Step 1: Maak de branch**

```bash
cd /pool/apps/weekmenu-planner && git checkout main && git checkout -b boodschappenlijst
```

- [ ] **Step 2: Schrijf failing tests**

`tests/test_combined_shopping.py`:
```python
import json
from datetime import date, datetime, timedelta

from weekmenu.extensions import db
from weekmenu.models import (
    Cookbook, Ingredient, MenuItem, QuickAddItem, Recipe, RecipeIngredient,
    ShoppingCheck,
)
from weekmenu.services.shopping import build_combined_shopping_list, window_weeks

TODAY = date(2026, 7, 11)  # zaterdag, ISO-week 28


def _mk_recipe(name, ing_name, amount, unit='g', serves=4):
    ing = Ingredient.query.filter_by(name=ing_name).first()
    if not ing:
        ing = Ingredient(name=ing_name, display_name=ing_name, category='overig')
        db.session.add(ing)
        db.session.flush()
    r = Recipe(name=name, serves=serves)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=amount, unit=unit))
    db.session.flush()
    return r, ing


def _plan(recipe, year, week, day=0):
    db.session.add(MenuItem(day_of_week=day, meal_type='avond',
                            recipe_id=recipe.id, week_number=week, year=year))
    db.session.flush()


def test_window_weeks_covers_prev_to_plus_two(app):
    weeks = window_weeks(today=TODAY)
    assert (2026, 27) in weeks and (2026, 28) in weeks
    assert (2026, 29) in weeks and (2026, 30) in weeks


def test_same_ingredient_two_weeks_merges_and_checks_partially(app):
    r1, ing = _mk_recipe('Dal wk28', 'rode linzen', 200)
    r2, _ = _mk_recipe('Dal wk29', 'rode linzen', 300)
    _plan(r1, 2026, 28)
    _plan(r2, 2026, 29)

    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['name'].lower().startswith('rode linzen')]
    assert len(rows) == 1
    assert rows[0]['amount'] == 500  # 200 + 300 samengevoegd

    # week 28 afvinken → alleen 300 nog open
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert rows[0]['amount'] == 300

    # beide weken afgevinkt → rij naar checked
    db.session.add(ShoppingCheck(year=2026, week_number=29, ingredient_id=ing.id,
                                 via_ah=True))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]
    checked = [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert checked and checked[0]['via_ah'] is True


def test_checked_older_than_14_days_hidden(app):
    r, ing = _mk_recipe('Soep', 'prei', 2, unit='stuks')
    _plan(r, 2026, 28)
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id,
                                 checked_at=datetime(2026, 6, 1)))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]


def test_quick_add_recipe_counts_and_old_manual_week_included(app):
    r, ing = _mk_recipe('Feestje', 'chips', 3, unit='zak')
    # QuickAddItem in een week buiten het venster (3 weken terug, week 25)
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=4,
                                week_number=25, year=2026))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert any(q['recipe_id'] == r.id for q in result['quick_add'])
```

- [ ] **Step 3: Run tests, verwacht FAIL**

Run: `python3 -m pytest tests/test_combined_shopping.py -v`
Expected: FAIL — `ImportError: cannot import name 'ShoppingCheck'`

- [ ] **Step 4: Implementeer model + service**

Onderaan `weekmenu/models.py`:
```python
class ShoppingCheck(db.Model):
    __tablename__ = 'shopping_check'
    __table_args__ = (
        db.UniqueConstraint('year', 'week_number', 'ingredient_id',
                            name='uq_check_week_ingredient'),
    )
    id            = db.Column(db.Integer, primary_key=True)
    year          = db.Column(db.Integer, nullable=False)
    week_number   = db.Column(db.Integer, nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    checked_at    = db.Column(db.DateTime, default=datetime.now, nullable=False)
    via_ah        = db.Column(db.Boolean, default=False, nullable=False)
```
(Nieuwe tabel: `db.create_all()` maakt hem aan, geen ALTER-migratie nodig — zelfde aanpak als DumpJob/RecipeDraft.)

In `weekmenu/services/shopping.py` — imports uitbreiden (`from datetime import date, datetime, timedelta`, en `ShoppingCheck`, `QuickAddItem` staat er al, plus `ShoppingListOverride` toevoegen aan de models-import en `from weekmenu.services.units import _calc_ah_qty, format_amount`) en onderaan toevoegen:
```python
def window_weeks(today=None):
    """ISO-weken van vandaag-7d t/m vandaag+14d, plus handmatige weken tot 4 weken terug."""
    today = today or date.today()
    weeks = []
    for delta in (-7, 0, 7, 14):
        iso = (today + timedelta(days=delta)).isocalendar()
        wk = (iso[0], iso[1])
        if wk not in weeks:
            weeks.append(wk)
    for delta in (-28, -21, -14):
        iso = (today + timedelta(days=delta)).isocalendar()
        wk = (iso[0], iso[1])
        if wk in weeks:
            continue
        has_manual = (
            QuickAddItem.query.filter_by(year=wk[0], week_number=wk[1]).count() > 0
            or CustomShoppingIngredient.query.filter_by(year=wk[0], week_number=wk[1]).count() > 0
        )
        if has_manual:
            weeks.append(wk)
    return sorted(weeks)


def _row_base(ing, unit, amount):
    from weekmenu.constants import CATEGORY_BG
    api_color = ing.ah_product_color or ''
    return {
        'name': ing.display,
        'amount': amount,
        'amount_display': format_amount(amount),
        'unit': unit,
        'category': ing.category,
        'ingredient_id': ing.id,
        'ah_product_id': ing.ah_product_id,
        'ah_product_name': ing.ah_product_name,
        'ah_product_size': ing.ah_product_size,
        'ah_product_image': ing.ah_product_image,
        'ah_product_price': ing.ah_product_price,
        'ah_product_bonus': ing.ah_product_bonus or False,
        'ah_product_bg': api_color or CATEGORY_BG.get(ing.category, '#f0ede8'),
    }


def build_combined_shopping_list(today=None):
    """Combineer de per-week-lijsten van het venster tot één lijst met afvink-status."""
    weeks = window_weeks(today)
    per_week = {wk: _build_shopping_dict(wk[0], wk[1]) for wk in weeks}

    checks = {}
    for c in ShoppingCheck.query.filter(
            db.tuple_(ShoppingCheck.year, ShoppingCheck.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        checks[(c.year, c.week_number, c.ingredient_id)] = c

    overrides = {}
    for o in ShoppingListOverride.query.filter(
            db.tuple_(ShoppingListOverride.year, ShoppingListOverride.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        overrides[(o.year, o.week_number, o.ingredient_id)] = o.qty

    agg = {}
    weeks_by_ingredient = {}
    for (y, w), d in per_week.items():
        for (ing_id, unit), amount in d.items():
            weeks_by_ingredient.setdefault(ing_id, [])
            if (y, w) not in weeks_by_ingredient[ing_id]:
                weeks_by_ingredient[ing_id].append((y, w))
            row = agg.setdefault((ing_id, unit), {
                'weeks': [], 'open_amount': 0.0, 'total_amount': 0.0,
                'open_qty': 0, 'checked': [], 'via_ah': False, 'checked_at': None,
            })
            row['weeks'].append((y, w))
            row['total_amount'] += amount
            c = checks.get((y, w, ing_id))
            if c:
                row['checked'].append((y, w))
                row['via_ah'] = row['via_ah'] or c.via_ah
                if row['checked_at'] is None or c.checked_at > row['checked_at']:
                    row['checked_at'] = c.checked_at
            else:
                row['open_amount'] += amount

    open_rows, checked_rows = [], []
    cutoff = datetime.now() - timedelta(days=14)
    for (ing_id, unit), r in agg.items():
        ing = Ingredient.query.get(ing_id)
        if not ing:
            continue
        fully_checked = len(r['checked']) == len(r['weeks'])
        if fully_checked:
            if r['checked_at'] and r['checked_at'] < cutoff:
                continue
            row = _row_base(ing, unit, r['total_amount'])
            row['via_ah'] = r['via_ah']
            row['checked_at'] = r['checked_at']
            checked_rows.append(row)
        else:
            row = _row_base(ing, unit, r['open_amount'])
            qty = 0
            for (y, w) in r['weeks']:
                if (y, w) in r['checked']:
                    continue
                wk_amount = per_week[(y, w)].get((ing_id, unit), 0)
                qty += overrides.get((y, w, ing_id), _calc_ah_qty(ing, wk_amount, unit))
            row['default_qty'] = _calc_ah_qty(ing, r['open_amount'], unit)
            row['qty'] = qty
            open_rows.append(row)

    quick_add = []
    for qi in QuickAddItem.query.filter(
            db.tuple_(QuickAddItem.year, QuickAddItem.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        if qi.recipe:
            quick_add.append({'id': qi.id, 'recipe_id': qi.recipe_id,
                              'recipe_name': qi.recipe.name,
                              'people_count': qi.people_count})

    return {'open': open_rows, 'checked': checked_rows,
            'weeks_by_ingredient': weeks_by_ingredient, 'quick_add': quick_add}
```

- [ ] **Step 5: Run tests, verwacht PASS**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS (bestaande 12 + 4 nieuwe)

- [ ] **Step 6: Commit**

```bash
git add weekmenu/models.py weekmenu/services/shopping.py tests/test_combined_shopping.py
git commit -m "Boodschappen: ShoppingCheck-model en gecombineerde lijst-aggregatie"
```

---

### Task 2: AH-verzendkern refactoren + gecombineerd verzenden

**Files:**
- Modify: `weekmenu/routes/shopping.py:195-285` (`send_to_ah`)
- Modify: `weekmenu/services/shopping.py`
- Test: `tests/test_combined_shopping.py`

**Interfaces:**
- Consumes: Task 1 (`build_combined_shopping_list`, `ShoppingCheck`).
- Produces:
  - `send_dict_to_ah(shopping_dict, qty_overrides) -> (payload: dict, status: int, sent_ingredient_ids: list[int])` in `weekmenu/services/shopping.py` — bevat de volledige huidige logica van de route (access-token, merge per AH-productId, order-mode-detectie, PUT/PATCH). Gebruikt module-level `import requests` (zodat tests `weekmenu.services.shopping.requests` kunnen monkeypatchen) en `ah_get_access_token` geïmporteerd als module-attribuut.
  - De bestaande route `POST /api/shopping-list/<y>/<w>/send-to-ah` wordt een dunne wrapper: bouwt `_build_shopping_dict(year, week)`, roept `send_dict_to_ah` aan, geeft payload/status terug (gedrag identiek; geen checks zetten — per-week-route blijft zoals hij was).

- [ ] **Step 1: Schrijf failing test**

Toevoegen aan `tests/test_combined_shopping.py`:
```python
def test_send_dict_to_ah_returns_sent_ids(app, monkeypatch):
    from weekmenu.services import shopping as shopping_svc

    r, ing = _mk_recipe('Dal', 'linzen-ah', 200)
    ing.ah_product_id = 12345
    _plan(r, 2026, 28)
    r2, ing2 = _mk_recipe('Soep', 'ongekoppeld-ding', 1, unit='stuks')
    _plan(r2, 2026, 28)
    db.session.commit()

    monkeypatch.setattr(shopping_svc, 'ah_get_access_token', lambda: 'token')

    class FakeResp:
        status_code = 404
        def json(self): return {}
        def raise_for_status(self): pass
    class FakeReq:
        def get(self, *a, **kw): return FakeResp()
        def patch(self, *a, **kw): return FakeResp()
        def put(self, *a, **kw): return FakeResp()
    monkeypatch.setattr(shopping_svc, 'requests', FakeReq())

    from weekmenu.services.shopping import _build_shopping_dict, send_dict_to_ah
    payload, status, sent_ids = send_dict_to_ah(_build_shopping_dict(2026, 28), {})
    assert status == 200
    assert payload['status'] == 'ok'
    assert ing.id in sent_ids
    assert ing2.id not in sent_ids
    assert 'ongekoppeld-ding' in ' '.join(payload['not_linked'])
```

- [ ] **Step 2: Run test, verwacht FAIL**

Run: `python3 -m pytest tests/test_combined_shopping.py::test_send_dict_to_ah_returns_sent_ids -v`
Expected: FAIL — `ImportError: cannot import name 'send_dict_to_ah'`

- [ ] **Step 3: Implementeer**

In `weekmenu/services/shopping.py`: bovenaan `import requests` en `from weekmenu.services.ah import ah_get_access_token` en `from weekmenu.services.units import _calc_ah_qty` (al toegevoegd in Task 1). Verplaats de body van de huidige route `send_to_ah` (`weekmenu/routes/shopping.py:195-285`) hierheen als:
```python
def send_dict_to_ah(shopping_dict, qty_overrides):
    """Stuur een shopping-dict naar AH (lijst of actieve order). Returns (payload, status, sent_ingredient_ids)."""
    from collections import defaultdict
    from weekmenu.constants import (_AH_HEADERS, _AH_SHOPPINGLIST_URL,
                                    _AH_ORDER_ACTIVE_URL, _AH_ORDER_ITEMS_URL)

    access_token = ah_get_access_token()
    if not access_token:
        return ({'status': 'error',
                 'message': 'Geen AH-account gekoppeld. Ga naar Instellingen.'}, 401, [])

    if not shopping_dict:
        return ({'status': 'ok', 'sent': 0, 'not_linked': [],
                 'message': 'Boodschappenlijst is leeg'}, 200, [])

    headers = {**_AH_HEADERS, 'Authorization': f'Bearer {access_token}',
               'Content-Type': 'application/json'}

    merged = defaultdict(int)
    name_by_pid = {}
    not_linked = []
    sent_ingredient_ids = []
    for (ing_id, unit), amount in shopping_dict.items():
        ing = Ingredient.query.get(ing_id)
        if not ing:
            continue
        if not ing.ah_product_id:
            not_linked.append(ing.display)
            continue
        qty = qty_overrides.get(ing_id, _calc_ah_qty(ing, amount, unit))
        merged[ing.ah_product_id] += max(int(qty or 1), 1)
        name_by_pid.setdefault(ing.ah_product_id, ing.display)
        sent_ingredient_ids.append(ing_id)

    if not merged:
        return ({'status': 'ok', 'sent': 0, 'not_linked': not_linked,
                 'message': 'Geen gekoppelde AH-producten in de lijst. '
                            'Koppel ze eerst via AH-producten.'}, 200, [])

    order_id = None
    try:
        r = requests.get(_AH_ORDER_ACTIVE_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            order_id = (r.json() or {}).get('id')
    except Exception:
        pass

    try:
        if order_id:
            items = [{'productId': pid, 'quantity': qty, 'originCode': 'PRD',
                      'description': '', 'strikethrough': False}
                     for pid, qty in merged.items()]
            resp = requests.put(
                _AH_ORDER_ITEMS_URL, json={'items': items},
                headers={**headers, 'Appie-Current-Order-Id': str(order_id)},
                timeout=20)
            target = 'bestelling'
        else:
            items = [{'originCode': 'PRD', 'productId': pid,
                      'quantity': qty, 'type': 'SHOPPABLE',
                      'description': name_by_pid.get(pid, ''),
                      'searchTerm': name_by_pid.get(pid, ''),
                      'strikeThrough': False}
                     for pid, qty in merged.items()]
            resp = requests.patch(_AH_SHOPPINGLIST_URL, json={'items': items},
                                  headers=headers, timeout=20)
            target = 'boodschappenlijst'
        resp.raise_for_status()
    except Exception as e:
        from flask import current_app
        current_app.logger.warning('AH send mislukt: %r', e)
        return ({'status': 'error', 'sent': 0, 'not_linked': not_linked,
                 'message': f'Versturen naar AH mislukt: {e}'}, 502, [])

    sent = len(merged)
    msg = f'{sent} product{"en" if sent != 1 else ""} toegevoegd aan je AH-{target}'
    if not_linked:
        msg += f'. {len(not_linked)} nog niet gekoppeld (overgeslagen): {", ".join(not_linked[:5])}'
    return ({'status': 'ok', 'sent': sent, 'not_linked': not_linked,
             'message': msg}, 200, sent_ingredient_ids)
```
De route `send_to_ah` in `weekmenu/routes/shopping.py` wordt:
```python
@bp.route('/api/shopping-list/<int:year>/<int:week>/send-to-ah', methods=['POST'])
def send_to_ah(year, week):
    _body = request.get_json(force=True) or {}
    qty_overrides = {int(k): v for k, v in _body.get('qty_overrides', {}).items()}
    payload, status, _sent = send_dict_to_ah(_build_shopping_dict(year, week), qty_overrides)
    return jsonify(payload), status
```
(imports in de route-file opschonen: `_AH_HEADERS`/`_AH_SHOPPINGLIST_URL`/`ah_get_access_token` verwijderen als ze nergens anders gebruikt worden; `send_dict_to_ah` importeren uit de service. Let op: de route-versie gebruikte `import requests as _req` binnen de functie — die verdwijnt mee.)

- [ ] **Step 4: Run alle tests, verwacht PASS**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS

- [ ] **Step 5: Commit**

```bash
git add weekmenu/services/shopping.py weekmenu/routes/shopping.py tests/test_combined_shopping.py
git commit -m "Boodschappen: AH-verzendkern naar service (send_dict_to_ah)"
```

---

### Task 3: Routes voor de gecombineerde lijst

**Files:**
- Modify: `weekmenu/routes/shopping.py`
- Modify: `weekmenu/routes/main.py` (`/boodschappenlijst`-redirect)
- Modify: `weekmenu/routes/menu.py` (quick-add-routes vervangen door redirect)
- Test: `tests/test_combined_shopping.py`

**Interfaces:**
- Consumes: Task 1 (`build_combined_shopping_list`, `window_weeks`, `ShoppingCheck`), Task 2 (`send_dict_to_ah`).
- Produces:
  - `GET /boodschappen` → rendert `boodschappen.html` (Task 4) met context `grouped_open` (per categorie gegroepeerd zoals de per-week-lijst), `checked_items`, `quick_add`, `recipes_json` (voor de receptpicker: `[{id, name, serves}]`).
  - `POST /api/boodschappen/item/<int:ingredient_id>/check` body `{checked: bool}` → zet/verwijdert ShoppingCheck-rijen voor alle bijdragende weken (`weeks_by_ingredient`); onbekend ingrediënt → 404.
  - `POST /api/boodschappen/check-all` → vinkt alle open regels af (`via_ah=False`).
  - `POST /api/boodschappen/send-to-ah` body `{qty_overrides}` → gecombineerde open items naar AH; bij `status=='ok'` en `sent>0`: checks (`via_ah=True`) voor alle bijdragende weken van `sent_ingredient_ids`.
  - `POST /api/boodschappen/extra` body `{recipe_id, people_count}` → QuickAddItem in huidige ISO-week; `DELETE /api/boodschappen/extra/<int:id>` verwijdert hem.
  - Redirects: `/shopping-list/<y>/<w>` (GET) → 301 `/boodschappen`; `/quick-add` → 302 `/boodschappen`; `/boodschappenlijst` (main.py) → `/boodschappen`. De routes `save_quick_add`/`clear_quick_add` in menu.py worden verwijderd.

- [ ] **Step 1: Schrijf failing tests**

Toevoegen aan `tests/test_combined_shopping.py`:
```python
def test_check_endpoint_checks_all_weeks(app, client):
    r1, ing = _mk_recipe('A', 'kikkererwten', 200)
    r2, _ = _mk_recipe('B', 'kikkererwten', 100)
    iso = date.today().isocalendar()
    nxt = (date.today() + timedelta(days=7)).isocalendar()
    _plan(r1, iso[0], iso[1])
    _plan(r2, nxt[0], nxt[1])
    db.session.commit()

    resp = client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': True})
    assert resp.status_code == 200
    assert ShoppingCheck.query.filter_by(ingredient_id=ing.id).count() == 2

    resp = client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': False})
    assert resp.status_code == 200
    assert ShoppingCheck.query.filter_by(ingredient_id=ing.id).count() == 0


def test_check_unknown_ingredient_404(app, client):
    assert client.post('/api/boodschappen/item/99999/check',
                       json={'checked': True}).status_code == 404


def test_extra_add_and_delete(app, client):
    r, ing = _mk_recipe('Shakshuka', 'eieren-extra', 3, unit='stuks')
    db.session.commit()
    resp = client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 2})
    assert resp.status_code == 200
    qid = resp.get_json()['id']
    assert QuickAddItem.query.get(qid) is not None

    assert client.delete(f'/api/boodschappen/extra/{qid}').status_code == 200
    assert QuickAddItem.query.get(qid) is None


def test_old_urls_redirect(app, client):
    resp = client.get('/shopping-list/2026/28')
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/boodschappen')
    resp = client.get('/quick-add')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/boodschappen')


def test_combined_send_to_ah_checks_sent_items(app, client, monkeypatch):
    from weekmenu.services import shopping as shopping_svc
    r, ing = _mk_recipe('Dal-ah', 'linzen-combined', 200)
    ing.ah_product_id = 777
    iso = date.today().isocalendar()
    _plan(r, iso[0], iso[1])
    db.session.commit()

    monkeypatch.setattr(shopping_svc, 'ah_get_access_token', lambda: 'token')
    class FakeResp:
        status_code = 404
        def json(self): return {}
        def raise_for_status(self): pass
    class FakeReq:
        def get(self, *a, **kw): return FakeResp()
        def patch(self, *a, **kw): return FakeResp()
        def put(self, *a, **kw): return FakeResp()
    monkeypatch.setattr(shopping_svc, 'requests', FakeReq())

    resp = client.post('/api/boodschappen/send-to-ah', json={})
    assert resp.status_code == 200
    check = ShoppingCheck.query.filter_by(ingredient_id=ing.id).first()
    assert check is not None and check.via_ah is True
```
(`test_check_endpoint_checks_all_weeks` en `test_combined_send_to_ah_checks_sent_items` gebruiken `date.today()` omdat de endpoints geen testdatum accepteren — dat is prima: de geplande weken vallen altijd in het venster.)

- [ ] **Step 2: Run tests, verwacht FAIL**

Run: `python3 -m pytest tests/test_combined_shopping.py -v`
Expected: nieuwe tests FAIL met 404 (routes bestaan niet)

- [ ] **Step 3: Implementeer routes**

In `weekmenu/routes/shopping.py` toevoegen (imports: `redirect`, `url_for` bij flask; `build_combined_shopping_list`, `window_weeks`, `send_dict_to_ah` uit de service; `ShoppingCheck`, `QuickAddItem`, `Recipe` bij models; `import json` bovenaan):
```python
def _grouped(items):
    category_order = {cat: i for i, cat in enumerate(CATEGORY_ORDER_SUPERMARKET)}
    items = sorted(items, key=lambda x: (category_order.get(x['category'], 999), x['name']))
    grouped = []
    for item in items:
        if not grouped or grouped[-1]['category'] != item['category']:
            grouped.append({'category': item['category'], 'producten': []})
        grouped[-1]['producten'].append(item)
    return grouped


@bp.route('/boodschappen')
def boodschappen():
    data = build_combined_shopping_list()
    recipes = Recipe.query.order_by(Recipe.name).all()
    recipes_json = json.dumps([{'id': r.id, 'name': r.name, 'serves': r.serves}
                               for r in recipes])
    weeks_json = json.dumps({str(k): v for k, v in data['weeks_by_ingredient'].items()})
    return render_template('boodschappen.html',
                           grouped_open=_grouped(data['open']),
                           checked_items=sorted(data['checked'],
                                                key=lambda x: x['checked_at'] or datetime.min,
                                                reverse=True),
                           quick_add=data['quick_add'],
                           recipes_json=recipes_json,
                           weeks_by_ingredient_json=weeks_json)


def _set_checks(ingredient_id, checked, via_ah=False):
    data = build_combined_shopping_list()
    weeks = data['weeks_by_ingredient'].get(ingredient_id)
    if not weeks:
        return False
    for (y, w) in weeks:
        existing = ShoppingCheck.query.filter_by(
            year=y, week_number=w, ingredient_id=ingredient_id).first()
        if checked and not existing:
            db.session.add(ShoppingCheck(year=y, week_number=w,
                                         ingredient_id=ingredient_id, via_ah=via_ah))
        elif not checked and existing:
            db.session.delete(existing)
    db.session.commit()
    return True


@bp.route('/api/boodschappen/item/<int:ingredient_id>/check', methods=['POST'])
def boodschappen_check(ingredient_id):
    body = request.get_json(silent=True) or {}
    if not _set_checks(ingredient_id, bool(body.get('checked', True))):
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/check-all', methods=['POST'])
def boodschappen_check_all():
    data = build_combined_shopping_list()
    for row in data['open']:
        _set_checks(row['ingredient_id'], True)
    return jsonify({'status': 'success', 'checked': len(data['open'])})


@bp.route('/api/boodschappen/send-to-ah', methods=['POST'])
def boodschappen_send_to_ah():
    body = request.get_json(silent=True) or {}
    qty_overrides = {int(k): v for k, v in body.get('qty_overrides', {}).items()}
    data = build_combined_shopping_list()
    open_dict = {}
    for row in data['open']:
        open_dict[(row['ingredient_id'], row['unit'])] = row['amount']
    payload, status, sent_ids = send_dict_to_ah(open_dict, qty_overrides)
    if status == 200 and payload.get('status') == 'ok' and sent_ids:
        for ing_id in sent_ids:
            _set_checks(ing_id, True, via_ah=True)
    return jsonify(payload), status


@bp.route('/api/boodschappen/extra', methods=['POST'])
def boodschappen_extra_add():
    body = request.get_json(silent=True) or {}
    recipe = Recipe.query.get(body.get('recipe_id') or 0)
    if not recipe:
        return jsonify({'status': 'error', 'message': 'Recept niet gevonden'}), 404
    iso = date.today().isocalendar()
    qi = QuickAddItem(recipe_id=recipe.id,
                      people_count=body.get('people_count') or recipe.serves or 4,
                      year=iso[0], week_number=iso[1])
    db.session.add(qi)
    db.session.commit()
    return jsonify({'status': 'success', 'id': qi.id})


@bp.route('/api/boodschappen/extra/<int:id>', methods=['DELETE'])
def boodschappen_extra_delete(id):
    qi = QuickAddItem.query.get_or_404(id)
    db.session.delete(qi)
    db.session.commit()
    return jsonify({'status': 'success'})
```
(`from datetime import date, datetime` bovenaan de route-file toevoegen.)

De bestaande route `shopping_list` (`/shopping-list/<int:year>/<int:week>`) vervangen door:
```python
@bp.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    return redirect(url_for('shopping.boodschappen'), code=301)
```
De niet meer gebruikte hulpvariabelen in die route (quick-add URL-params-blok) vervallen daarmee. De API-routes voor qty/exclude/add-item/clear blijven staan.

In `weekmenu/routes/menu.py`: routes `quick_add`, `save_quick_add` en `clear_quick_add` verwijderen en vervangen door:
```python
@bp.route('/quick-add')
def quick_add():
    return redirect(url_for('shopping.boodschappen'), code=302)
```
In `weekmenu/routes/main.py`: `boodschappenlijst_redirect` laten wijzen naar `url_for('shopping.boodschappen')`.

Let op: `render_template('boodschappen.html', ...)` bestaat pas na Task 4; de tests hierboven raken `GET /boodschappen` niet aan.

- [ ] **Step 4: Run alle tests, verwacht PASS**

Run: `python3 -m pytest tests/ -v`
Expected: alles PASS

- [ ] **Step 5: Commit**

```bash
git add weekmenu/routes/shopping.py weekmenu/routes/menu.py weekmenu/routes/main.py tests/test_combined_shopping.py
git commit -m "Boodschappen: gecombineerde routes, check/extra-API's en redirects"
```

---

### Task 4: Template `boodschappen.html` + navigatie

**Files:**
- Create: `templates/boodschappen.html`
- Modify: `templates/base.html` (nav-link "Boodschappen" → `/boodschappen`)

**Interfaces:**
- Consumes: Task 3 route-context (`grouped_open`, `checked_items`, `quick_add`, `recipes_json`) en API's (`check`, `check-all`, `send-to-ah`, `extra`).

- [ ] **Step 1: Bouw de template**

Lees eerst `templates/shopping_list.html` volledig en neem daaruit de kaart-markup per product over (afbeelding, naam, hoeveelheid, qty-stepper, AH-info) — dezelfde look. Bouw `templates/boodschappen.html` met:

1. Kop "Boodschappen" + subtitel "Alles wat gepland en nog open staat".
2. Actieknoppenrij: **"Verstuur naar AH (n)"** (n = aantal open items, POST `/api/boodschappen/send-to-ah` met `qty_overrides` verzameld zoals de bestaande per-week-pagina dat doet), **"+ Recept"**, **"Alles afvinken"** (POST `/api/boodschappen/check-all`, daarna reload).
3. Chips-regel losse recepten (alleen tonen als `quick_add` niet leeg):
```html
{% if quick_add %}
<div class="flex flex-wrap gap-2 items-center text-sm">
    <span class="text-[#6B6B6B]">Losse recepten:</span>
    {% for q in quick_add %}
    <span class="inline-flex items-center gap-1 border border-[#E8E4DC] rounded-full px-3 py-1">
        {{ q.recipe_name }} ({{ q.people_count }}p)
        <button onclick="removeExtra({{ q.id }})" class="text-red-600">✕</button>
    </span>
    {% endfor %}
</div>
{% endif %}
```
4. Open items: per categorie gegroepeerd (loop over `grouped_open` zoals `shopping_list.html` over zijn groepen loopt), met vóór elk item een checkbox die `checkItem(ingredient_id, this.checked)` aanroept.
5. Inklapbaar blok "Afgevinkt ({{ checked_items|length }})" onderaan: doorgestreepte regels (`line-through text-[#9CA3AF]`), checkbox aangevinkt (uncheck → terug naar open), badge `via AH` (groen: `bg-green-100 text-green-800 rounded-full px-2 text-xs`) waar `item.via_ah`.
6. "+ Recept"-picker: eenvoudige modal of inline blok met `<input list>`-datalist gevuld uit `recipes_json`, personen-invoer (default serves), knop "Toevoegen".

JS onderaan (volledige functies):
```javascript
async function checkItem(ingredientId, checked) {
    const resp = await fetch(`/api/boodschappen/item/${ingredientId}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checked }),
    });
    if (resp.ok) location.reload();
}

async function checkAll() {
    if (!confirm('Alle openstaande items afvinken?')) return;
    await fetch('/api/boodschappen/check-all', { method: 'POST' });
    location.reload();
}

async function removeExtra(id) {
    await fetch(`/api/boodschappen/extra/${id}`, { method: 'DELETE' });
    location.reload();
}

async function addExtra() {
    const name = document.getElementById('extraRecipeInput').value;
    const recipe = RECIPES.find(r => r.name === name);
    if (!recipe) { alert('Kies een recept uit de lijst'); return; }
    const people = parseInt(document.getElementById('extraPeople').value) || recipe.serves || 4;
    const resp = await fetch('/api/boodschappen/extra', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipe.id, people_count: people }),
    });
    if (resp.ok) location.reload();
}

async function sendToAh() {
    const btn = document.getElementById('sendAhBtn');
    btn.disabled = true;
    const qty_overrides = collectQtyOverrides();
    const resp = await fetch('/api/boodschappen/send-to-ah', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qty_overrides }),
    });
    const data = await resp.json();
    alert(data.message || (resp.ok ? 'Verstuurd' : 'Mislukt'));
    if (resp.ok && data.status === 'ok') location.reload(); else btn.disabled = false;
}
```
(`RECIPES = {{ recipes_json | safe }}`; `collectQtyOverrides()` overnemen van hoe `shopping_list.html` de qty-steppers uitleest — zelfde element-structuur aanhouden.)

Heeft `shopping_list.html` een uitsluit-knop (✗) per item, neem die over met deze JS (exclusion naar álle bijdragende weken, conform spec):
```javascript
const WEEKS_BY_ING = {{ weeks_by_ingredient_json | safe }};
async function excludeItem(ingredientId) {
    const weeks = WEEKS_BY_ING[String(ingredientId)] || [];
    for (const [y, w] of weeks) {
        await fetch(`/api/shopping-list/${y}/${w}/item/${ingredientId}/exclude`,
                    { method: 'POST' });
    }
    location.reload();
}
```
Qty-wijzigingen sturen naar de **laatste** bijdragende week: `const [y, w] = weeks[weeks.length - 1];` en dan het bestaande per-week qty-endpoint.

In `templates/base.html`: de bestaande nav-link naar de boodschappenlijst laten wijzen naar `{{ url_for('shopping.boodschappen') }}`.

- [ ] **Step 2: Verifieer op dev**

```bash
docker compose -f docker-compose.dev.yml up -d --build
```
`http://<server>:5002/boodschappen`: pagina 200, plan een recept in deze én volgende week met een gedeeld ingrediënt → één regel met opgeteld aantal; checkbox af → regel doorgestreept onderaan; uncheck → terug; "+ Recept" → chips-regel + ingrediënten erbij; "Alles afvinken" leegt de open lijst. Oude URL `/shopping-list/2026/28` redirect. Regressie: `python3 -m pytest tests/ -v` → PASS.

- [ ] **Step 3: Commit**

```bash
git add templates/boodschappen.html templates/base.html
git commit -m "Boodschappen: gecombineerde lijstpagina met afvinken en losse recepten"
```

---

### Task 5: Weekbalk + laatst-bekeken-week

**Files:**
- Modify: `templates/week_menu.html` (weekbalk bovenaan)
- Modify: `weekmenu/routes/menu.py` (`week_menu`: cookie zetten)
- Modify: `weekmenu/routes/main.py` (homepage: cookie lezen)
- Test: `tests/test_combined_shopping.py`

**Interfaces:**
- Consumes: bestaande route `menu.week_menu(year, week)`.
- Produces: cookie `last_viewed_week` = `"<iso-jaar>-<week>"`, max-age 1209600 (14 dagen); homepage redirect naar die week.

- [ ] **Step 1: Schrijf failing tests**

Toevoegen aan `tests/test_combined_shopping.py`:
```python
def test_week_menu_sets_cookie_and_home_follows_it(app, client):
    resp = client.get('/week/2026/30')
    assert resp.status_code == 200
    cookies = resp.headers.getlist('Set-Cookie')
    assert any('last_viewed_week=2026-30' in c for c in cookies)

    client.set_cookie('last_viewed_week', '2026-30')
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/week/2026/30' in resp.headers['Location']


def test_home_ignores_invalid_cookie(app, client):
    client.set_cookie('last_viewed_week', '2026-60')
    resp = client.get('/')
    iso = date.today().isocalendar()
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']

    client.set_cookie('last_viewed_week', 'onzin')
    resp = client.get('/')
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']
```

- [ ] **Step 2: Run tests, verwacht FAIL**

Run: `python3 -m pytest tests/test_combined_shopping.py -k cookie -v`
Expected: FAIL — geen Set-Cookie / redirect naar huidige week

- [ ] **Step 3: Implementeer**

`weekmenu/routes/menu.py`, `week_menu`: response via `make_response(render_template(...))` en vlak voor de return:
```python
    resp = make_response(render_template('week_menu.html', ...bestaande kwargs...))
    resp.set_cookie('last_viewed_week', f'{year}-{week}', max_age=1209600, samesite='Lax')
    return resp
```
(`make_response` bij de flask-imports.)

`weekmenu/routes/main.py`, index-route:
```python
@bp.route('/')
def index():
    today = date.today()
    iso = today.isocalendar()
    year, week_number = iso[0], iso[1]
    cookie = request.cookies.get('last_viewed_week', '')
    try:
        c_year, c_week = (int(p) for p in cookie.split('-'))
        if 1 <= c_week <= 53 and abs(c_year - year) <= 1:
            year, week_number = c_year, c_week
    except (ValueError, AttributeError):
        pass
    return redirect(url_for('menu.week_menu', year=year, week=week_number))
```
(`request` bij de flask-imports; let op: het bestaande `today.year` wordt vervangen door het ISO-jaar `iso[0]`.)

`templates/week_menu.html` — bovenaan de content een weekbalk (bestaande navigatie-elementen voor vorige/volgende week vervangen door deze balk; bereken de datums server-side met de al beschikbare `year`/`week`):
```html
{% set monday = namespace(d=None) %}
<div class="bg-white border border-[#E8E4DC] rounded-lg px-5 py-3 mb-4">
    <div class="flex items-center justify-between gap-3">
        <a href="{{ url_for('menu.week_menu', year=prev_year, week=prev_week) }}"
           class="text-2xl px-3 py-1 rounded hover:bg-[#F5F2ED]" aria-label="Vorige week">‹</a>
        <div class="text-center">
            <div class="text-xl font-bold">Week {{ week }}</div>
            <div class="text-sm text-[#6B6B6B]">{{ week_range }}</div>
        </div>
        <a href="{{ url_for('menu.week_menu', year=next_year, week=next_week) }}"
           class="text-2xl px-3 py-1 rounded hover:bg-[#F5F2ED]" aria-label="Volgende week">›</a>
    </div>
    {% if not is_current_week %}
    <div class="flex items-center justify-center gap-2 mt-2">
        <span class="text-xs bg-amber-100 text-amber-800 rounded-full px-3 py-1">
            Je kijkt naar een andere week</span>
        <a href="{{ url_for('menu.week_menu', year=current_year, week=current_week) }}"
           class="text-xs border border-[#E8E4DC] rounded px-3 py-1 hover:bg-[#F5F2ED]">
            Naar deze week</a>
    </div>
    {% endif %}
</div>
```
Bijbehorende context in `week_menu` (route) berekenen en meegeven:
```python
    from datetime import date as _date, timedelta as _td
    monday = _date.fromisocalendar(year, week, 1)
    sunday = monday + _td(days=6)
    MAANDEN = ['januari', 'februari', 'maart', 'april', 'mei', 'juni', 'juli',
               'augustus', 'september', 'oktober', 'november', 'december']
    week_range = f'ma {monday.day} {MAANDEN[monday.month-1][:3]} – zo {sunday.day} {MAANDEN[sunday.month-1][:3]}'
    prev_monday = monday - _td(days=7)
    next_monday = monday + _td(days=7)
    iso_now = _date.today().isocalendar()
    extra_ctx = dict(
        week_range=week_range,
        prev_year=prev_monday.isocalendar()[0], prev_week=prev_monday.isocalendar()[1],
        next_year=next_monday.isocalendar()[0], next_week=next_monday.isocalendar()[1],
        current_year=iso_now[0], current_week=iso_now[1],
        is_current_week=(year == iso_now[0] and week == iso_now[1]),
    )
```
en `**extra_ctx` aan de `render_template`-aanroep toevoegen. Bestond er al een week-navigatie-element in `week_menu.html`, verwijder dat (geen dubbele pijlen).

- [ ] **Step 4: Run alle tests + dev-check, verwacht PASS**

Run: `python3 -m pytest tests/ -v` → PASS. Dev: weekbalk zichtbaar, pijlen werken over jaargrens (week 1/53), indicator + "Naar deze week" alleen bij andere week, homepage opent laatst bekeken week.

- [ ] **Step 5: Commit**

```bash
git add templates/week_menu.html weekmenu/routes/menu.py weekmenu/routes/main.py tests/test_combined_shopping.py
git commit -m "Weekmenu: prominente weekbalk en laatst-bekeken-week-cookie"
```

---

### Task 6: Quick-add-restanten opruimen + e2e op dev

**Files:**
- Delete: `templates/quick_add.html`
- Modify: `weekmenu/routes/menu.py`, `weekmenu/services/shopping.py` (checken op dode imports)

**Interfaces:** geen nieuwe.

- [ ] **Step 1: Opruimen**

`templates/quick_add.html` verwijderen (`git rm`). In `weekmenu/routes/menu.py` ongebruikte imports na het verwijderen van de quick-add-routes opschonen (o.a. `QuickAddItem` als die daar nergens meer gebruikt wordt). `grep -rn "quick_add\|quick-add" templates/ static/ weekmenu/` — resterende verwijzingen (behalve de redirect-route en `QuickAddItem` in service/models/nieuwe API) opruimen.

- [ ] **Step 2: E2E op dev**

`docker compose -f docker-compose.dev.yml up -d --build`, daarna het volledige scenario: plan recepten in huidige én volgende week → `/boodschappen` toont alles samengevoegd zonder weeklabels → "+ Recept" → verstuur naar AH (of, zonder AH-koppeling op dev: "Alles afvinken") → open lijst leeg, afgevinkt-blok gevuld → menu wijzigen (extra recept) → nieuw item verschijnt open. Weekbalk: navigeer naar volgende week, sluit browser-sessie na, homepage opent die week weer.

- [ ] **Step 3: Run tests + commit**

Run: `python3 -m pytest tests/ -v` → PASS.
```bash
git add -A
git commit -m "Boodschappen: quick-add-restanten opgeruimd"
```
