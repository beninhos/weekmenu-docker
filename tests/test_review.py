"""Nakijkpagina: voorraadkandidaten, onbekende categorieën, afwijkingen."""
from weekmenu.extensions import db
from weekmenu.models import Ingredient, PantryIngredient, Recipe, RecipeIngredient
from weekmenu.services.pantry import review_lists


def _ing(name, category, pantry=False):
    i = Ingredient(name=name, display_name=name, category=category)
    db.session.add(i)
    db.session.flush()
    if pantry:
        db.session.add(PantryIngredient(ingredient_id=i.id))
    db.session.commit()
    return i


def _use(recipe, ing, amount, unit):
    db.session.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ing.id,
                                    amount=amount, unit=unit))
    db.session.commit()


def _recipe():
    r = Recipe(name='R', serves=2)
    db.session.add(r)
    db.session.commit()
    return r


def test_kandidaat_wel_dosis_geen_voorraad(client, app):
    r = _recipe()
    kaneel = _ing('kaneel', 'Kruiden & Specerijen')
    puree = _ing('tomatenpuree', 'Oliën, Sauzen & Smaakmakers')
    olie = _ing('olijfolie', 'Oliën, Sauzen & Smaakmakers', pantry=True)
    _use(r, kaneel, 1, 'tl')
    _use(r, puree, 140, 'g')
    _use(r, olie, 2, 'el')

    namen = [k['name'] for k in review_lists()['kandidaten']]
    assert 'kaneel' in namen            # dosis, niet op voorraad
    assert 'tomatenpuree' not in namen  # hele verpakking
    assert 'olijfolie' not in namen     # staat al op voorraad


def test_ongebruikt_ingredient_is_geen_kandidaat(client, app):
    _ing('kurkuma', 'Kruiden & Specerijen')
    assert review_lists()['kandidaten'] == []


def test_overig_met_testafval_achteraan(client, app):
    r = _recipe()
    echt = _ing('kappertjes', 'Overig')
    _use(r, echt, 1, 'el')
    _ing('test ingredient 1', 'Overig')
    overig = review_lists()['overig']
    assert [o['name'] for o in overig] == ['kappertjes', 'test ingredient 1']
    assert overig[0]['testafval'] is False
    assert overig[1]['testafval'] is True


def test_afwijking_van_de_gok(client, app):
    _ing('rucola', 'Dranken')
    afw = {a['name']: a for a in review_lists()['afwijkend']}
    assert afw['rucola']['guess'] == 'Groente, Fruit & Aardappelen'


def test_categorie_wijzigen_via_de_api(client, app):
    ing = _ing('rucola', 'Dranken')
    resp = client.post(f'/api/ingredient/{ing.id}/category',
                       json={'category': 'Groente, Fruit & Aardappelen'})
    assert resp.get_json()['category'] == 'Groente, Fruit & Aardappelen'
    assert Ingredient.query.get(ing.id).category == 'Groente, Fruit & Aardappelen'


def test_onbekende_categorie_wordt_geweigerd(client, app):
    ing = _ing('rucola', 'Dranken')
    resp = client.post(f'/api/ingredient/{ing.id}/category',
                       json={'category': 'Soepen, Sauzen & Kruiden'})
    assert resp.status_code == 400
    assert Ingredient.query.get(ing.id).category == 'Dranken'


def test_pagina_rendert_en_staat_op_de_voorraadpagina(client, app):
    r = _recipe()
    kaneel = _ing('kaneel', 'Kruiden & Specerijen')
    _use(r, kaneel, 1, 'tl')
    html = client.get('/twijfelgevallen').get_data(as_text=True)
    assert 'Twijfelgevallen' in html and 'kaneel' in html
    assert '/twijfelgevallen' in client.get('/voorraad').get_data(as_text=True)
