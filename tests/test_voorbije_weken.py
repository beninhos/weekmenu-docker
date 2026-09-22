"""Voorbije weken zijn afgesloten: geen actieve historie.

Rutgers regel: 'afgevinkt is afgevinkt, ik heb geen actieve historie nodig.'
Zonder die streep telde elke ooit geplande week voor altijd mee, en kon een
regel uit augustus zomaar terugkomen zodra een weekbesluit sneuvelde — precies
wat er gebeurde toen 'kipgehakt naturel' werd samengevoegd met 'kipgehakt' en
de uitsluiting van week 32 daarbij verdween.
"""
from datetime import date

from sqlalchemy import text

from weekmenu.extensions import db
from weekmenu.migrations import _migrate_v21
from weekmenu.models import (
    Ingredient, MenuItem, Recipe, RecipeIngredient,
    ShoppingCheck, ShoppingListExclusion,
)
from weekmenu.services.ingredienten import voeg_samen
from weekmenu.services.shopping import build_combined_shopping_list


def _iso():
    return date.today().isocalendar()


def _voorbije_week():
    """Een week die zeker achter ons ligt, zonder kalenderaanname in de test."""
    iso = _iso()
    return (iso[0] - 1, 32)


def _mk(naam, ing_naam, hoeveelheid=200):
    ing = Ingredient(name=ing_naam, display_name=ing_naam, category='overig')
    db.session.add(ing)
    db.session.flush()
    r = Recipe(name=naam, serves=4)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=hoeveelheid, unit='g'))
    db.session.commit()
    return r, ing


def _sluit_voorbije_weken():
    db.session.commit()
    with db.engine.connect() as conn:
        _migrate_v21(conn)
        conn.commit()
    db.session.expire_all()


def _open_ids():
    return {x['ingredient_id'] for x in build_combined_shopping_list()['open']}


def test_voorbije_week_levert_niets_meer_aan_de_open_lijst(app):
    jaar, week = _voorbije_week()
    r, ing = _mk('Kapsalon', 'kipgehakt')
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()
    assert ing.id in _open_ids(), 'zonder afsluiting staat hij er nog op'

    _sluit_voorbije_weken()

    assert ing.id not in _open_ids()


def test_afsluiten_laat_de_huidige_week_met_rust(app):
    iso = _iso()
    r, ing = _mk('Nasi', 'kroepoek')
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r.id,
                            week_number=iso[1], year=iso[0]))
    db.session.commit()

    _sluit_voorbije_weken()

    assert ing.id in _open_ids(), 'de week waarin je leeft wordt niet afgesloten'


def test_weggeklikte_regel_uit_een_voorbije_week_komt_niet_terug_door_samenvoegen(app):
    """Het kipgehakt-geval van 20 sep 2026, precies nagespeeld.

    Samenvoegen gooit de weekbesluiten van de verliezer weg — een bewuste keuze
    (zie _wis_weekbesluiten), want in een lopende week zie je zo'n regel gewoon
    terugkomen en klik je hem opnieuw weg. Maar in een week van twee maanden
    terug zag je hem juist niet aankomen. Nu die week is afgesloten, kan het niet.
    """
    jaar, week = _voorbije_week()
    r, verliezer = _mk('Kapsalon', 'kipgehakt naturel')
    winnaar = Ingredient(name='kipgehakt', display_name='Kipgehakt', category='vlees')
    db.session.add(winnaar)
    db.session.flush()
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r.id,
                            week_number=week, year=jaar))
    # Destijds weggeklikt: 'dat haal ik deze week niet'.
    db.session.add(ShoppingListExclusion(year=jaar, week_number=week,
                                         ingredient_id=verliezer.id))
    db.session.commit()

    _sluit_voorbije_weken()
    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingListExclusion.query.filter_by(ingredient_id=verliezer.id).count() == 0, \
        'samenvoegen gooit het weekbesluit van de verliezer weg — dat blijft zo'
    assert winnaar.id not in _open_ids(), \
        'maar de regel komt niet terug: die week is afgesloten'


def test_afsluiten_zet_de_vinkjes_op_de_week_zelf_niet_op_vandaag(app):
    """Anders vult het afgevinkt-blok — dat veertien dagen toont — in één klap."""
    jaar, week = _voorbije_week()
    r, ing = _mk('Kapsalon', 'feta')
    db.session.add(MenuItem(day_of_week=1, meal_type='diner', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    _sluit_voorbije_weken()

    check = ShoppingCheck.query.filter_by(year=jaar, week_number=week,
                                          ingredient_id=ing.id).one()
    assert check.checked_at.date() == date.fromisocalendar(jaar, week, 1)
    assert not build_combined_shopping_list()['checked'], \
        'een afgesloten week van lang geleden hoort ook niet in het afgevinkt-blok'
