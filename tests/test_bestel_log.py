"""Wat er per week echt gehaald is, los van de boodschappenlijst.

Rutger: 'ik heb geen actieve historie nodig, alleen het stuk voor de analyse
achteraf, door te loggen wat echt besteld is.' Echt betekent: teruggelezen uit
de order, niet wat de app heeft doorgestuurd -- zodra het magazijn iets niet
heeft wijkt dat af. En wat hij zelf afvinkt, bij de slager of de markt, hoort
in dezelfde pot.
"""
from datetime import date

import pytest

from weekmenu.extensions import db
from weekmenu.models import (
    Bestelling, BestellingRegel, Ingredient, MenuItem, Recipe, RecipeIngredient,
)
from weekmenu.services import ah as ah_svc
from weekmenu.services import shopping as shop_svc


def _iso():
    return date.today().isocalendar()


def _ing(naam, bron=None, ah_product_id=None):
    ing = Ingredient(name=naam, display_name=naam.capitalize(), category='overig',
                     bron=bron, ah_product_id=ah_product_id)
    db.session.add(ing)
    db.session.flush()
    return ing


def _plan(*ingredienten):
    r = Recipe(name='Weekrecept', serves=4)
    db.session.add(r)
    db.session.flush()
    for ing in ingredienten:
        db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                        amount=2, unit='stuks'))
    iso = _iso()
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r.id,
                            week_number=iso[1], year=iso[0]))
    db.session.commit()
    return r


def _order(*producten):
    return {
        'orderId': 955, 'orderState': 'CONFIRMED', 'deliveryDate': '2026-09-24',
        'total': sum(p.get('price', 0) * p.get('quantity', 1) for p in producten),
        'savings': 1.5, 'productIds': [p['productId'] for p in producten],
        'groups': [{'taxonomy': 'Groente', 'items': list(producten)}],
    }


def _product(pid, titel, aantal=1, prijs=2.49, bonus=False):
    return {'productId': pid, 'title': titel, 'brand': 'AH', 'size': '500 g',
            'quantity': aantal, 'price': prijs, 'wasPrice': None, 'isBonus': bonus}


@pytest.fixture()
def ah(monkeypatch):
    """Doe alsof er een AH-sessie is en de order teruglezen lukt."""
    verzonden = {}

    def _verstuur(shopping_dict, qty_overrides):
        verzonden['dict'] = shopping_dict
        return ({'status': 'success', 'sent': len(shopping_dict), 'not_linked': [],
                 'order_id': 955, 'message': 'ok'}, 200,
                [ing_id for (ing_id, _u) in shopping_dict])

    monkeypatch.setattr(shop_svc, 'send_dict_to_ah', _verstuur)
    from weekmenu.routes import shopping as route
    monkeypatch.setattr(route, 'send_dict_to_ah', _verstuur)
    return verzonden


def test_versturen_legt_de_teruggelezen_order_vast(app, client, ah, monkeypatch):
    tomaat = _ing('tomaat', ah_product_id=111)
    _plan(tomaat)
    # De order bevat iets anders dan wat we stuurden: het magazijn had geen
    # tomaten en er staat een zak uien in die hij zelf toevoegde.
    monkeypatch.setattr(ah_svc, 'ah_get_order',
                        lambda oid: _order(_product(222, 'Uien 1 kg', 2, 1.29, bonus=True)))

    assert client.post('/api/boodschappen/send-to-ah', json={}).status_code == 200

    pot = Bestelling.query.one()
    assert (pot.year, pot.week_number) == (_iso()[0], _iso()[1])
    assert pot.ah_order_id == 955
    assert pot.bezorgdatum == '2026-09-24'
    regel = BestellingRegel.query.one()
    assert (regel.titel, regel.aantal, regel.prijs, regel.bonus) == ('Uien 1 kg', 2, 1.29, True)
    assert regel.ingredient_id is None, 'een product dat de app niet kent mag er gewoon in'


def test_zelf_afvinken_komt_in_dezelfde_pot(app, client, ah, monkeypatch):
    tomaat = _ing('tomaat', ah_product_id=111)
    vlees = _ing('half-om-half', bron='slager')
    _plan(tomaat, vlees)
    monkeypatch.setattr(ah_svc, 'ah_get_order',
                        lambda oid: _order(_product(111, 'Tomaten', 1)))

    client.post('/api/boodschappen/send-to-ah', json={})
    # De slager stuur je niet naar de Appie; die vink je zelf af.
    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': True})

    assert Bestelling.query.count() == 1, 'een pot per week, niet een per winkel'
    bronnen = {r.bron: r.titel for r in BestellingRegel.query.all()}
    assert bronnen == {'ah': 'Tomaten', 'slager': 'Half-om-half'}


def test_order_opnieuw_lezen_vervangt_ah_regels_en_laat_handwerk_staan(app, client, ah, monkeypatch):
    tomaat = _ing('tomaat', ah_product_id=111)
    vlees = _ing('half-om-half', bron='slager')
    _plan(tomaat, vlees)
    monkeypatch.setattr(ah_svc, 'ah_get_order',
                        lambda oid: _order(_product(111, 'Tomaten', 1)))
    client.post('/api/boodschappen/send-to-ah', json={})
    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': True})

    # Winkelmand openen terwijl het magazijn de tomaten heeft laten vallen.
    monkeypatch.setattr(ah_svc, 'ah_get_order',
                        lambda oid: _order(_product(333, 'Trostomaten', 1, 3.49)))
    assert client.get('/api/ah/order/955').status_code == 200

    titels = {r.bron: r.titel for r in BestellingRegel.query.all()}
    assert titels == {'ah': 'Trostomaten', 'slager': 'Half-om-half'}


def test_twee_keer_afvinken_telt_niet_dubbel(app, client):
    vlees = _ing('half-om-half', bron='slager')
    _plan(vlees)

    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': True})
    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': False})
    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': True})

    assert BestellingRegel.query.count() == 1


def test_alles_afvinken_legt_elke_regel_vast(app, client):
    markt = _ing('klein uitje', bron='markt')
    slager = _ing('half-om-half', bron='slager')
    _plan(markt, slager)

    client.post('/api/boodschappen/check-all')

    assert {r.bron for r in BestellingRegel.query.all()} == {'markt', 'slager'}


def test_het_log_overleeft_het_opruimen_van_de_lijst(app, client):
    """De lijst vergeet, het log niet -- dat is de hele reden dat het bestaat."""
    from weekmenu.migrations import _migrate_v21
    vlees = _ing('half-om-half', bron='slager')
    _plan(vlees)
    client.post(f'/api/boodschappen/item/{vlees.id}/check', json={'checked': True})
    assert BestellingRegel.query.count() == 1

    db.session.commit()
    with db.engine.connect() as conn:
        _migrate_v21(conn)
        conn.commit()

    assert BestellingRegel.query.count() == 1
