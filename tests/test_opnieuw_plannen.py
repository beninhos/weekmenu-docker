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
