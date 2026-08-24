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


def test_bron_zetten_en_terugdraaien(client, app):
    ing = _ing('polenta', 'Pasta, Rijst & Wereldkeuken')
    assert client.post(f'/api/ingredient/{ing.id}/bron',
                       json={'bron': 'toko'}).get_json()['bron'] == 'toko'
    assert Ingredient.query.get(ing.id).bron == 'toko'
    # 'ah' betekent gewoon bij de AH, en dat slaan we op als leeg
    assert client.post(f'/api/ingredient/{ing.id}/bron',
                       json={'bron': 'ah'}).get_json()['bron'] == 'ah'
    assert Ingredient.query.get(ing.id).bron is None


def test_onbekende_bron_wordt_geweigerd(client, app):
    ing = _ing('polenta', 'Pasta, Rijst & Wereldkeuken')
    assert client.post(f'/api/ingredient/{ing.id}/bron',
                       json={'bron': 'gamma'}).status_code == 400
    assert Ingredient.query.get(ing.id).bron is None


def test_niet_ah_items_krijgen_een_eigen_blok_op_de_lijst(client, app):
    from weekmenu.models import Recipe, MenuItem
    from datetime import date
    iso = date.today().isocalendar()

    polenta = _ing('polenta', 'Pasta, Rijst & Wereldkeuken')
    ui = _ing('ui', 'Groente, Fruit & Aardappelen')
    r = _recipe()
    _use(r, polenta, 250, 'g')
    _use(r, ui, 2, 'stuks')
    db.session.add(MenuItem(recipe_id=r.id, week_number=iso[1], year=iso[0],
                            day_of_week=0, meal_type='diner', people_count=2))
    db.session.commit()

    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'Niet bij de AH' not in html          # nog niets gemarkeerd

    client.post(f'/api/ingredient/{polenta.id}/bron', json={'bron': 'toko'})
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'Niet bij de AH' in html
    assert 'Toko' in html
    # polenta staat in het elders-blok, de ui blijft erboven in de AH-lijst
    kop = html.index('Niet bij de AH')
    assert 'polenta' in html[kop:]
    assert 'polenta' not in html[:kop]
    assert 'ui' in html[:kop]
