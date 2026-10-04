"""Elk gebaar waarmee je iets op de lijst zet, zet het ook echt terug.

Rutgers regel: afvinken of weghalen is geen blijvend oordeel. Voegt hij het
daarna opnieuw toe, dan staat het er weer. Dat geldt niet alleen voor plannen
en voor de knoppen op /boodschappen, maar ook voor de twee gebaren die er
zijdelings hetzelfde doen: een recept bewerken, en iets uit de voorraad halen.

De grens is de week: een week waarvoor je al boodschappen hebt gedaan blijft
dicht. Anders komt de kapsalon van week 32 terug zodra je in september een
recept aanpast.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, MenuItem, PantryIngredient, QuickAddItem, Recipe,
    RecipeIngredient, ShoppingCheck,
)
from weekmenu.services.shopping import build_combined_shopping_list


def _iso():
    return date.today().isocalendar()


NU = None


def _huidige():
    iso = _iso()
    return iso[0], iso[1]


def _voorbij():
    return _iso()[0] - 1, 32


def _ing(naam, categorie='overig'):
    ing = Ingredient.query.filter_by(name=naam).first()
    if not ing:
        ing = Ingredient(name=naam, display_name=naam.capitalize(), category=categorie)
        db.session.add(ing)
        db.session.flush()
    return ing


def _recept(naam, paren, serves=4):
    r = Recipe(name=naam, serves=serves)
    db.session.add(r)
    db.session.flush()
    for ing_naam, hoeveelheid in paren:
        db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=_ing(ing_naam).id,
                                        amount=hoeveelheid, unit='g'))
    db.session.commit()
    return r


def _plan(recept, jaar, week, dag=1):
    db.session.add(MenuItem(day_of_week=dag, meal_type='diner', recipe_id=recept.id,
                            week_number=week, year=jaar))
    db.session.commit()


def _sluit(jaar, week):
    """Week afgerond: alles wat hij aanlevert staat afgevinkt."""
    for (ing_id, _unit) in list(__import__(
            'weekmenu.services.shopping', fromlist=['x'])._build_shopping_dict(jaar, week)):
        db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=ing_id))
    db.session.commit()


def _open_ids():
    return {x['ingredient_id'] for x in build_combined_shopping_list()['open']}


def _post_edit(client, recept, paren, **over):
    form = {
        'name': recept.name, 'page': '', 'serves': str(recept.serves or 4),
        'cookbook': '', 'url': '', 'instructions': '',
        'ingredient[]': [n for n, _ in paren],
        'ingredient_id[]': ['' for _ in paren],
        'amount[]': [str(a) for _, a in paren],
        'unit[]': ['g' for _ in paren],
        'category[]': ['overig' for _ in paren],
        'preparation[]': ['' for _ in paren],
        'pantry_flag[]': ['0' for _ in paren],
    }
    form.update(over)
    return client.post(f'/recipe/{recept.id}/edit', data=form, follow_redirects=False)


# ── Los recept toevoegen: vervangen, niet stapelen ────────────────────────

def test_zelfde_recept_opnieuw_toevoegen_stapelt_de_hoeveelheden_niet(app, client):
    r = _recept('Soep', [('bouillon', 100)])
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})

    assert QuickAddItem.query.count() == 1, 'opnieuw toevoegen om te checken hoort geen tweede regel te maken'
    rij = next(x for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == _ing('bouillon').id)
    assert rij['amount'] == 100


def test_zelfde_recept_met_ander_aantal_personen_werkt_de_regel_bij(app, client):
    r = _recept('Soep', [('bouillon', 100)], serves=4)
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 8})

    assert QuickAddItem.query.count() == 1
    assert QuickAddItem.query.one().people_count == 8
    rij = next(x for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == _ing('bouillon').id)
    assert rij['amount'] == 200


def test_hetzelfde_recept_in_een_nieuwe_week_krijgt_wel_een_eigen_regel(app, client):
    r = _recept('Soep', [('bouillon', 100)])
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})
    qi = QuickAddItem.query.one()
    qi.week_number = (qi.week_number - 1) or 52       # alsof hij van vorige week was
    db.session.commit()

    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 4})

    assert QuickAddItem.query.count() == 2, 'vervangen geldt binnen een week, niet erover heen'


# ── Recept bewerken ───────────────────────────────────────────────────────

def test_recept_bewerken_zet_niets_terug_wat_al_afgevinkt_is(app, client):
    # Rutger, 4 okt 2026: 'alleen ingrediënten toevoegen als ik iets op het
    # menu plan.' Patatje oorlog stond die week gepland en was via de AH
    # gekocht; het inkorten van de ingrediëntenlijst zette ui, komkommer,
    # aardappelen en sperziebonen terug -- en via de gedeelde ui- en
    # aardappelregel ook het deel van de zuurkoolstamppot.
    jaar, week = _huidige()
    r = _recept('Patatje', [('ui', 1), ('komkommer', 1), ('pindakaas', 2)])
    _plan(r, jaar, week)
    client.post('/api/boodschappen/check-all')
    assert _open_ids() == set()

    _post_edit(client, r, [('ui', 1), ('komkommer', 1)])

    assert _open_ids() == set()


def test_recept_bewerken_laat_afgevinkt_staan_en_een_nieuw_ingredient_verschijnt(app, client):
    # Een ingredient dat er nieuw bij komt is nooit afgevinkt; dat staat open
    # omdat het recept gepland is, niet omdat bewerken iets terugzet.
    jaar, week = _huidige()
    r = _recept('Kapsalon', [('kipgehakt', 300)])
    _plan(r, jaar, week)
    client.post('/api/boodschappen/check-all')
    assert _open_ids() == set()

    _post_edit(client, r, [('kipgehakt', 300), ('feta', 100)])

    assert _open_ids() == {_ing('feta').id}


def test_recept_bewerken_laat_een_afgeronde_week_dicht(app, client):
    jaar, week = _voorbij()
    r = _recept('Kapsalon', [('kipgehakt', 300)])
    _plan(r, jaar, week)
    _sluit(jaar, week)
    assert _open_ids() == set()

    _post_edit(client, r, [('kipgehakt', 600), ('feta', 100)])

    assert _open_ids() == set(), 'een week waarvoor je al boodschappen deed gaat niet open'


# ── Uit de voorraad halen ─────────────────────────────────────────────────

def test_uit_de_voorraad_halen_zet_het_ingredient_weer_op_de_lijst(app, client):
    jaar, week = _huidige()
    r = _recept('Soep', [('groentebouillon', 1000)])
    _plan(r, jaar, week)
    bouillon = _ing('groentebouillon')
    db.session.add(PantryIngredient(ingredient_id=bouillon.id))
    # Een vinkje van voordat hij de kast in ging; zonder opruimen landt de regel
    # na het eruit halen regelrecht in het dichtgeklapte afgevinkt-blok.
    db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=bouillon.id))
    db.session.commit()
    assert bouillon.id not in _open_ids(), 'staat in de kast, dus niet op de lijst'

    assert client.delete(f'/api/pantry/{bouillon.id}').status_code == 200

    assert bouillon.id in _open_ids()


def test_uit_de_voorraad_halen_laat_een_afgeronde_week_dicht(app, client):
    jaar, week = _voorbij()
    r = _recept('Soep', [('groentebouillon', 1000), ('ui', 2)])
    _plan(r, jaar, week)
    _sluit(jaar, week)
    bouillon = _ing('groentebouillon')
    db.session.add(PantryIngredient(ingredient_id=bouillon.id))
    db.session.commit()

    client.delete(f'/api/pantry/{bouillon.id}')

    assert bouillon.id not in _open_ids()
