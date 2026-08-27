"""Regressies uit de eindreview van branch fix/voorraad-en-categorie."""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import (Ingredient, MenuItem, PantryIngredient, Recipe,
                             RecipeIngredient)


def _ing(name, category='Oliën, Sauzen & Smaakmakers', **kw):
    i = Ingredient(name=name, display_name=name, category=category, **kw)
    db.session.add(i)
    db.session.flush()
    return i


def _plan(ing, amount=1, unit='el'):
    iso = date.today().isocalendar()
    r = Recipe(name='R', serves=2)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=amount, unit=unit))
    db.session.add(MenuItem(recipe_id=r.id, week_number=iso[1], year=iso[0],
                            day_of_week=0, meal_type='diner', people_count=2))
    db.session.commit()
    return r


def _form(**over):
    form = {
        'name': 'Test', 'page': '', 'serves': '2', 'cookbook': '', 'url': '',
        'instructions': '',
        'ingredient[]': ['olijfolie'], 'ingredient_id[]': [''],
        'amount[]': ['2'], 'unit[]': ['el'],
        'category[]': ['Oliën, Sauzen & Smaakmakers'],
        'preparation[]': [''], 'pantry_flag[]': ['0'],
    }
    form.update(over)
    return form


# ── Voorraad volgt alleen rijen met een bekende identiteit ──────────────

def test_naam_voluit_typen_haalt_niets_uit_de_voorraad(client, app):
    """Zonder ingredient_id weet het formulier niet waarover het praat,
    dus een leeg vinkje mag niets verwijderen."""
    olie = _ing('olijfolie')
    db.session.add(PantryIngredient(ingredient_id=olie.id))
    db.session.commit()

    client.post('/recipe/new', data=_form())
    assert PantryIngredient.query.count() == 1


def test_vinkje_zonder_id_kan_wel_toevoegen(client, app):
    """Toevoegen is een expliciete klik, dus dat mag altijd."""
    client.post('/recipe/new', data=_form(**{'pantry_flag[]': ['1']}))
    ing = Ingredient.query.filter_by(name='olijfolie').one()
    assert PantryIngredient.query.filter_by(ingredient_id=ing.id).first()


def test_uitvinken_met_id_haalt_wel_uit_de_voorraad(client, app):
    olie = _ing('olijfolie')
    db.session.add(PantryIngredient(ingredient_id=olie.id))
    db.session.commit()

    client.post('/recipe/new', data=_form(**{'ingredient_id[]': [str(olie.id)]}))
    assert PantryIngredient.query.count() == 0


# ── Verstuur naar AH respecteert de bron ────────────────────────────────

def _mock_ah(monkeypatch):
    """Zonder AH-sessie keert send_dict_to_ah al op regel 1 terug met 401 en
    kijkt hij niet eens naar de lijst; dan toetst de test niets."""
    from weekmenu.services import shopping as shopping_svc
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


def test_elders_item_gaat_niet_mee_naar_ah(client, app, monkeypatch):
    from weekmenu.models import ShoppingCheck
    _mock_ah(monkeypatch)
    toko = _ing('sambal oelek', ah_product_id=12345, bron='toko')
    _plan(toko)

    resp = client.post('/api/boodschappen/send-to-ah', json={})
    assert resp.status_code == 200
    # Niet verstuurd, dus ook niet afgevinkt als 'via AH'.
    assert ShoppingCheck.query.filter_by(ingredient_id=toko.id).first() is None


def test_ah_item_wordt_wel_verstuurd_en_afgevinkt(client, app, monkeypatch):
    from weekmenu.models import ShoppingCheck
    _mock_ah(monkeypatch)
    gewoon = _ing('olijfolie', ah_product_id=777)
    _plan(gewoon)

    resp = client.post('/api/boodschappen/send-to-ah', json={})
    assert resp.status_code == 200
    check = ShoppingCheck.query.filter_by(ingredient_id=gewoon.id).first()
    assert check is not None and check.via_ah is True


def test_ah_item_gaat_wel_mee(client, app):
    from weekmenu.services.shopping import build_combined_shopping_list
    gewoon = _ing('olijfolie', ah_product_id=999)
    _plan(gewoon)
    rows = build_combined_shopping_list()['open']
    assert [r['name'] for r in rows if (r.get('bron') or 'ah') == 'ah'] == ['olijfolie']


# ── _is_dose overleeft rommelige hoeveelheden ───────────────────────────

def test_is_dose_valt_niet_om_op_tekst(app):
    from weekmenu.services.pantry import _is_dose
    assert _is_dose('g', '40') is True
    assert _is_dose('g', '2-3') is False
    assert _is_dose('g', None) is False
    assert _is_dose('el', 'veel') is True     # dosis-eenheid, hoeveelheid doet niet mee
    assert _is_dose('g', 100) is True
    assert _is_dose('g', 101) is False


def test_gemini_amount_wordt_een_getal(app):
    from weekmenu.services.gemini import _build_gemini_ingredients
    rows = _build_gemini_ingredients([
        {'name': 'bloem', 'amount': '140', 'unit': 'g'},
        {'name': 'ui', 'amount': '2-3', 'unit': 'stuks'},
        {'name': 'zout', 'amount': None, 'unit': ''},
    ])
    assert [r['amount'] for r in rows] == [140.0, None, None]


# ── Migratieketen in de echte volgorde ──────────────────────────────────

def test_keten_v10_v11_v12_in_de_juiste_volgorde(client, app):
    from weekmenu.migrations import _migrate_v10, _migrate_v11, _migrate_v12
    from weekmenu.constants import PRODUCT_CATEGORIES

    for naam, cat in [('walnoten', 'Noten, Zaden & Gedroogd Fruit'),
                      ('veldsla', 'Groente & Aardappelen'),
                      ('zalm', 'Vis & Schaaldieren'),
                      ('geraspte oude kaas', 'Kaas & Vleeswaren'),
                      ('spaghetti', 'Pasta, Rijst & Granen')]:
        db.session.add(Ingredient(name=naam, display_name=naam, category=cat))
    db.session.commit()

    with db.engine.connect() as conn:
        _migrate_v10(conn)
        _migrate_v11(conn)      # deze zat er in de test niet tussen
        _migrate_v12(conn)
        conn.commit()
    db.session.expire_all()

    def cat(n):
        return Ingredient.query.filter_by(name=n).one().category

    assert cat('walnoten') == 'Noten & Snacks'
    assert cat('veldsla') == 'Groente, Fruit & Aardappelen'
    assert cat('zalm') == 'Vlees & Vis'
    assert cat('geraspte oude kaas') == 'Kaas & Vleeswaren'
    assert cat('spaghetti') == 'Pasta, Rijst & Wereldkeuken'
    for ing in Ingredient.query.all():
        assert ing.category in PRODUCT_CATEGORIES, ing.name


# ── Lijstweergave ───────────────────────────────────────────────────────

def test_lege_melding_blijft_weg_als_er_elders_items_zijn(client, app):
    toko = _ing('polenta', 'Pasta, Rijst & Wereldkeuken', bron='toko')
    _plan(toko, 250, 'g')
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'Niet bij de AH' in html
    assert 'alles is al afgevinkt' not in html.lower()


def test_ingredient_api_weigert_een_verouderde_categorie(client, app):
    resp = client.post('/api/ingredients',
                       json={'name': 'venkelzaad', 'category': 'Groente & Aardappelen'})
    from weekmenu.constants import PRODUCT_CATEGORIES
    ing = Ingredient.query.filter_by(name='venkelzaad').one()
    assert ing.category in PRODUCT_CATEGORIES
    assert resp.status_code in (200, 201)


# ── Opruimwerk uit de 'kan later'-lijst ─────────────────────────────────

def test_parser_slikt_de_meervoudsstaart_van_de_eenheid(app):
    """Kookboeken schrijven 'stuk(s)'; die staart hoorde niet in de naam."""
    from weekmenu.services.units import _parse_dutch_ingredient as p
    assert p('1 stuk(s) tomaat')['name'] == 'tomaat'
    assert p('2 stuk(s) rode paprika')['name'] == 'rode paprika'
    teen = p('1 teen(tjes) knoflook')
    assert teen['name'] == 'knoflook' and teen['unit'] == 'teen'
    # en de gewone vormen blijven werken
    assert p('2 stuks tomaat')['name'] == 'tomaat'
    assert p('1 el olijfolie')['unit'] == 'el'
    assert p('500 g kipfilet')['amount'] == 500


def test_meervoudige_noten_vallen_niet_in_overig(app):
    from weekmenu.services.units import _guess_ingredient_category as g
    for naam in ('walnoot', 'walnoten', 'hazelnoot', 'hazelnoten'):
        assert g(naam) == 'Noten & Snacks', naam


def test_zip_import_valideert_de_categorie(client, app):
    """De ZIP-tak maakte Ingredient() rechtstreeks aan, dus zonder
    display_name en met een categorie die niet meer bestaat."""
    from weekmenu.services.recipes import _resolve_or_create_ingredient
    from weekmenu.constants import PRODUCT_CATEGORIES
    ing = _resolve_or_create_ingredient('venkelzaad', 'Groente & Aardappelen')
    db.session.commit()
    assert ing.category in PRODUCT_CATEGORIES
    assert ing.display_name


def test_dode_ah_route_is_weg(client, app):
    assert client.post('/api/shopping-list/2026/35/send-to-ah', json={}).status_code == 404


def test_zip_import_rondrit(client, app):
    """Exporteer een recept naar ZIP en lees het weer in: het ingredient moet
    een display_name, een alias en een geldige categorie hebben."""
    import io as _io, json, zipfile
    from weekmenu.constants import PRODUCT_CATEGORIES
    from weekmenu.models import IngredientAlias

    payload = {'cookbooks': [], 'recipes': [{
        'name': 'Ingelezen recept', 'serves': 2, 'page': None, 'url': None,
        'instructions': 'Stap 1.', 'image_filename': None,
        'ingredients': [{'name': 'venkelzaad', 'category': 'Groente & Aardappelen',
                         'amount': 1, 'unit': 'tl'}],
    }]}
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('weekmenu_export.json', json.dumps(payload))
    buf.seek(0)

    resp = client.post('/import/zip',
                       data={'file': (buf, 'export.zip')},
                       content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]

    ing = Ingredient.query.filter_by(name='venkelzaad').one()
    assert ing.category in PRODUCT_CATEGORIES
    assert ing.category != 'Groente & Aardappelen'
    assert ing.display_name
    assert IngredientAlias.query.filter_by(ingredient_id=ing.id).count() >= 1


def test_import_slaat_regels_zonder_naam_over(client, app):
    """Een export van een andere versie kan het naamveld missen; dat mag
    geen KeyError geven."""
    import json
    payload = {'cookbooks': [], 'recipes': [{
        'name': 'Half recept', 'serves': 2, 'instructions': '',
        'ingredients': [{'category': 'Overig', 'amount': 1, 'unit': 'tl'},
                        {'name': 'kaneel', 'category': 'Kruiden & Specerijen',
                         'amount': 1, 'unit': 'tl'}],
    }]}
    resp = client.post('/import', data={'file': (
        __import__('io').BytesIO(json.dumps(payload).encode()), 'export.json')},
        content_type='multipart/form-data')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
    assert Ingredient.query.filter_by(name='kaneel').count() == 1


# ── v14: spookingredienten uit de parserbug ─────────────────────────────

def test_v14_voegt_spookingredient_samen_met_het_echte(client, app):
    from weekmenu.migrations import _migrate_v14
    echt = _ing('tomaat', 'Groente, Fruit & Aardappelen')
    spook = _ing('stuk(s) tomaat', 'Groente, Fruit & Aardappelen')
    r = Recipe(name='R', serves=2)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=spook.id,
                                    amount=1, unit='stuks'))
    db.session.commit()
    spook_id, echt_id = spook.id, echt.id

    with db.engine.connect() as conn:
        _migrate_v14(conn)
        conn.commit()
    db.session.expire_all()

    assert Ingredient.query.get(spook_id) is None
    assert RecipeIngredient.query.filter_by(ingredient_id=echt_id).count() == 1
    assert RecipeIngredient.query.filter_by(ingredient_id=spook_id).count() == 0


def test_v14_hernoemt_als_het_echte_nog_niet_bestaat(client, app):
    from weekmenu.migrations import _migrate_v14
    spook = _ing('stuk(s) sjalot', 'Groente, Fruit & Aardappelen')
    db.session.commit()
    spook_id = spook.id

    with db.engine.connect() as conn:
        _migrate_v14(conn)
        conn.commit()
    db.session.expire_all()

    bewaard = Ingredient.query.get(spook_id)
    assert bewaard is not None and bewaard.name == 'sjalot'
    assert bewaard.display_name == 'sjalot'


def test_v14_laat_gewone_namen_met_haakjes_met_rust(client, app):
    from weekmenu.migrations import _migrate_v14
    ing = _ing('koriander (vers)', 'Groente, Fruit & Aardappelen')
    db.session.commit()
    with db.engine.connect() as conn:
        _migrate_v14(conn)
        conn.commit()
    db.session.expire_all()
    assert Ingredient.query.get(ing.id).name == 'koriander (vers)'
