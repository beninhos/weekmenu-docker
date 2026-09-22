"""Rutgers regel: 'alles wat ik afvink gaat van de lijst — tot ik het opnieuw
erop zet.' Een recept (opnieuw) plannen moet zijn ingrediënten dus terug op
de open lijst zetten, ook als ze in die week al afgevinkt of uitgesloten waren.
En de recepthint hoort alleen recepten te noemen waarvoor de regel nog open is.
"""
from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, MenuItem, Recipe, RecipeIngredient,
    ShoppingCheck, ShoppingListExclusion,
)
from weekmenu.services.menu import plan_recipe, update_week_menu
from weekmenu.services.shopping import build_combined_shopping_list


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


def _open_ids(result):
    return {x['ingredient_id'] for x in result['open']}


def _menu(day, recipe_id):
    return [{'day': day, 'meals': {'diner': {'recipe_id': recipe_id, 'people_count': 2}}}]


def test_nieuw_recept_via_weekmenu_maakt_afgevinkt_ingredient_weer_open(app):
    r, ing = _mk_recipe('Nasi', 'kroepoek', 75)
    # Week 38 al naar de AH gestuurd: kroepoek staat afgevinkt.
    db.session.add(ShoppingCheck(year=2026, week_number=38, ingredient_id=ing.id, via_ah=True))
    db.session.commit()
    assert ing.id not in _open_ids(build_combined_shopping_list())

    update_week_menu(38, 2026, _menu(1, r.id))

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_week_opnieuw_opslaan_zonder_nieuw_recept_laat_afgevinkt_staan(app):
    r, ing = _mk_recipe('Nasi', 'kroepoek', 75)
    update_week_menu(38, 2026, _menu(1, r.id))
    db.session.add(ShoppingCheck(year=2026, week_number=38, ingredient_id=ing.id, via_ah=True))
    db.session.commit()

    # Zelfde recept, andere dag: geen nieuw recept, dus niks resurrecteren.
    update_week_menu(38, 2026, _menu(3, r.id))

    assert ing.id not in _open_ids(build_combined_shopping_list())


def test_plan_recipe_maakt_afgevinkt_en_uitgesloten_ingredient_weer_open(app):
    r, ing = _mk_recipe('Nasi', 'sambal', 2, unit='el')
    ri = r.ingredients[0]
    db.session.add(ShoppingCheck(year=2026, week_number=38, ingredient_id=ing.id, via_ah=True))
    db.session.add(ShoppingListExclusion(year=2026, week_number=38, ingredient_id=ing.id))
    db.session.commit()

    plan_recipe(r.id, 1, 'diner', 38, 2026, 2, [ri.id])

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_recepthint_noemt_alleen_recepten_waarvoor_de_regel_open_is(app):
    oud, ing = _mk_recipe('Goudgele kip', 'ui', 1, unit='stuks')
    nieuw, _ = _mk_recipe('Nasi', 'ui', 2, unit='stuks')
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=oud.id,
                            week_number=36, year=2026))
    db.session.add(ShoppingCheck(year=2026, week_number=36, ingredient_id=ing.id, via_ah=True))
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=nieuw.id,
                            week_number=38, year=2026))
    db.session.commit()

    row = next(x for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == ing.id)
    assert row['recipes'] == ['Nasi']
    assert row['amount'] == 2


def test_winkelmand_nodig_volgt_de_open_boodschappenlijst(app, client, monkeypatch):
    from weekmenu.services import ah as ah_svc
    r_oud, ing_oud = _mk_recipe('Orzo', 'orzo', 300)
    r_nieuw, ing_nieuw = _mk_recipe('Nasi', 'kroepoek', 75)
    ing_oud.ah_product_id = 111
    ing_nieuw.ah_product_id = 222
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r_oud.id,
                            week_number=37, year=2026))
    db.session.add(ShoppingCheck(year=2026, week_number=37, ingredient_id=ing_oud.id, via_ah=True))
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r_nieuw.id,
                            week_number=38, year=2026))
    db.session.commit()

    monkeypatch.setattr(ah_svc, 'ah_get_order',
                        lambda oid: {'id': oid, 'editable': True, 'groups': [],
                                     'productIds': [], 'total': 0, 'savings': 0,
                                     'itemCount': 0})
    resp = client.get('/api/ah/order/955')
    assert resp.status_code == 200
    needed = {n['ingredientId'] for n in resp.get_json()['needed']}
    assert needed == {ing_nieuw.id}, 'afgevinkte orzo van week 37 hoort niet als "nog nodig"'


def test_ander_aantal_personen_zet_afgevinkt_recept_terug_op_de_lijst(app):
    r, ing = _mk_recipe('Nasi', 'kroepoek', 75)
    update_week_menu(38, 2026, _menu(1, r.id))
    db.session.add(ShoppingCheck(year=2026, week_number=38, ingredient_id=ing.id, via_ah=True))
    db.session.commit()

    update_week_menu(38, 2026, [{'day': 1, 'meals': {'diner': {'recipe_id': r.id, 'people_count': 4}}}])

    row = next((x for x in build_combined_shopping_list()['open'] if x['ingredient_id'] == ing.id), None)
    assert row is not None and row['amount'] == 75


def test_alles_afvinken_bouwt_de_lijst_een_keer_en_vinkt_alles_af(app, client, monkeypatch):
    from weekmenu.routes import shopping as route
    r1, ing1 = _mk_recipe('Nasi', 'kroepoek', 75)
    r2, ing2 = _mk_recipe('Chili', 'bonen', 400)
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r1.id, week_number=38, year=2026))
    db.session.add(MenuItem(day_of_week=2, meal_type='diner', recipe_id=r2.id, week_number=38, year=2026))
    db.session.add(MenuItem(day_of_week=2, meal_type='diner', recipe_id=r2.id, week_number=39, year=2026))
    db.session.commit()

    calls = []
    echt = route.build_combined_shopping_list
    monkeypatch.setattr(route, 'build_combined_shopping_list',
                        lambda *a, **kw: calls.append(1) or echt(*a, **kw))
    resp = client.post('/api/boodschappen/check-all')
    assert resp.status_code == 200
    assert resp.get_json()['checked'] == 2
    assert len(calls) == 1, 'per regel de hele lijst opnieuw bouwen duurde 6 s op de echte data'
    assert ShoppingCheck.query.filter_by(ingredient_id=ing2.id).count() == 2  # week 38 én 39
    assert build_combined_shopping_list()['open'] == []


# ── Opnieuw toevoegen vanaf de boodschappenlijst zelf ──────────────────────
# Dezelfde regel geldt voor de gebaren op /boodschappen: afvinken of weghalen
# is geen blijvend oordeel. Rutger haalt een regel juist weg om hem opnieuw toe
# te voegen en zo te controleren wat er nodig is; dat gebaar moet altijd werken.

def _iso():
    from datetime import date
    return date.today().isocalendar()


def test_los_recept_toevoegen_zet_afgevinkt_ingredient_weer_open(app, client):
    r, ing = _mk_recipe('Mexicaanse soep', 'tortillachips', 200)
    jaar, week = _iso()[0], _iso()[1]
    db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=ing.id))
    db.session.commit()

    assert client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 4}).status_code == 200

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_los_recept_toevoegen_haalt_de_uitsluiting_van_zijn_ingredient_weg(app, client):
    r, ing = _mk_recipe('Mexicaanse soep', 'jalapeno', 1, unit='stuks')
    jaar, week = _iso()[0], _iso()[1]
    db.session.add(ShoppingListExclusion(year=jaar, week_number=week, ingredient_id=ing.id))
    db.session.commit()

    assert client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 4}).status_code == 200

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_afvinken_en_opnieuw_toevoegen_is_gewoon_een_rondje(app, client):
    r, ing = _mk_recipe('Mexicaanse soep', 'cheddar', 100)
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 4}).get_json()['id']
    assert ing.id in _open_ids(build_combined_shopping_list())

    client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': True})
    assert ing.id not in _open_ids(build_combined_shopping_list())

    client.delete(f'/api/boodschappen/extra/{qid}')
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_weggehaalde_regel_komt_terug_door_het_recept_opnieuw_toe_te_voegen(app, client):
    r, ing = _mk_recipe('Mexicaanse soep', 'verse koriander', 1, unit='stuks')
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 4}).get_json()['id']

    client.post(f'/api/boodschappen/item/{ing.id}/remove')
    assert ing.id not in _open_ids(build_combined_shopping_list())

    client.delete(f'/api/boodschappen/extra/{qid}')
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_handmatig_item_opnieuw_toevoegen_na_afvinken_staat_weer_open(app, client):
    ing = Ingredient(name='limoen', display_name='Limoen', category='groente')
    db.session.add(ing)
    db.session.commit()
    jaar, week = _iso()[0], _iso()[1]
    pad = f'/api/shopping-list/{jaar}/{week}/add-item'

    assert client.post(pad, json={'ingredient_id': ing.id, 'amount': 2,
                                  'unit': 'stuks'}).status_code == 200
    client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': True})
    assert ing.id not in _open_ids(build_combined_shopping_list())

    assert client.post(pad, json={'ingredient_id': ing.id, 'amount': 2,
                                  'unit': 'stuks'}).status_code == 200

    assert ing.id in _open_ids(build_combined_shopping_list())


def test_opnieuw_toevoegen_laat_de_boodschappen_van_een_andere_week_afgevinkt(app, client):
    """Terugzetten geldt voor de week die je aanraakt, niet voor alle weken.

    Zonder deze grens haalt één nieuw recept de ui van vorige week — allang
    gekocht en afgevinkt — weer op de lijst, en telt hij de hoeveelheid erbij op.
    """
    oud, ing = _mk_recipe('Nasi', 'ui', 200)
    vorige = 37 if _iso()[1] != 37 else 36
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=oud.id,
                            week_number=vorige, year=_iso()[0]))
    db.session.add(ShoppingCheck(year=_iso()[0], week_number=vorige,
                                 ingredient_id=ing.id, via_ah=True))
    db.session.commit()

    nieuw, _ = _mk_recipe('Chili', 'ui', 100)
    client.post('/api/boodschappen/extra', json={'recipe_id': nieuw.id, 'people_count': 4})

    row = next(x for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == ing.id)
    assert row['amount'] == 100, 'de al gekochte ui van de vorige week hoort niet mee te tellen'
    assert row['recipes'] == ['Chili']
