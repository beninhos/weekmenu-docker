"""Afgevinkt blijft afgevinkt; toevoegen zet alleen het nieuwe op de lijst.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status.
"""
from datetime import date, datetime

from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, MenuItem, QuickAddItem, Recipe,
    RecipeIngredient, ShoppingCheck, ShoppingListExclusion,
)
from weekmenu.services import afgehandeld
from weekmenu.services.shopping import build_combined_shopping_list, lopende_weken

JAAR, WEEK = date.today().isocalendar()[0], date.today().isocalendar()[1]


def _ing(naam):
    ing = Ingredient.query.filter_by(name=naam).first()
    if not ing:
        ing = Ingredient(name=naam, display_name=naam, category='overig')
        db.session.add(ing)
        db.session.flush()
    return ing


def _recept(naam, regels, serves=2):
    r = Recipe(name=naam, serves=serves)
    db.session.add(r)
    db.session.flush()
    for ing_naam, hoeveel, eenheid in regels:
        db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=_ing(ing_naam).id,
                                        amount=hoeveel, unit=eenheid))
    db.session.commit()
    return r


def _plan(r, personen, dag=1, jaar=JAAR, week=WEEK):
    db.session.add(MenuItem(day_of_week=dag, meal_type='diner', recipe_id=r.id,
                            people_count=personen, week_number=week, year=jaar))
    db.session.commit()


def _open(naam):
    ing = _ing(naam)
    return sum(x['amount'] for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == ing.id)


def _chili():
    return _recept('Chili', [('kidneybonen', 1, 'blik'), ('rundergehakt', 200, 'g')])


# ── De opslag: per week per ingredient een hoeveelheid per eenheid ────────

def test_afvinken_telt_hoeveelheden_per_eenheid_op(app):
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    afgehandeld.vink_af(2026, 40, 7, {'blik': 6, 'g': 50})
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) == {'blik': 7, 'g': 50}


def test_een_rij_zonder_getal_betekent_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES
    assert afgehandeld.lees(None) == {}


def test_afvinken_bovenop_alles_blijft_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES


def test_weghalen_zet_de_datum_voor_het_afgevinkt_blok(app):
    afgehandeld.haal_weg(2026, 40, 2, {'g': 200})
    db.session.commit()
    rij = ShoppingListExclusion.query.one()
    assert afgehandeld.lees(rij) == {'g': 200}
    assert rij.weggehaald_op is not None


def test_afsluiten_dateert_een_nieuw_vinkje_op_de_maandag_van_die_week(app):
    afgehandeld.sluit_af(2026, 32, 7)
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) is afgehandeld.ALLES
    assert rij.checked_at.date() == date.fromisocalendar(2026, 32, 1)


def test_meegroeien_naar_rato_van_wat_al_afgehandeld_was(app):
    # Chili-week: nodig 7 blik, 1 gekocht; recept +50% geeft 3,5 extra.
    afgehandeld.vink_af(2026, 40, 158, {'blik': 1})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 158, 'blik', extra=3.5, nodig_oud=7)
    assert afgehandeld.lees(ShoppingCheck.query.one()) == {'blik': 1.5}


def test_meegroeien_verdeelt_over_vinkje_en_kruisje_en_nooit_meer_dan_het_extra(app):
    afgehandeld.vink_af(2026, 40, 1, {'g': 600})
    afgehandeld.haal_weg(2026, 40, 1, {'g': 600})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 1, 'g', extra=100, nodig_oud=1000)  # 120% afgehandeld
    a = afgehandeld.lees(ShoppingCheck.query.one())['g']
    w = afgehandeld.lees(ShoppingListExclusion.query.one())['g']
    assert round(a + w - 1200, 6) == 100
    assert round(a - w, 6) == 0


# ── De lijst: open = nodig - afgevinkt - weggehaald ──────────────────────

def test_rekenregel_open_is_nodig_min_afgevinkt_min_weggehaald(app):
    r = _chili()
    _plan(r, 2)
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.haal_weg(JAAR, WEEK, _ing('rundergehakt').id, {'g': 200})
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=12, year=JAAR, week_number=WEEK))
    db.session.commit()
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_een_eenheid_die_niet_meer_bestaat_verbergt_niets(app):
    ui = _ing('ui')
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=ui.id, amount=2, unit='stuks'))
    db.session.commit()
    afgehandeld.vink_af(JAAR, WEEK, ui.id, {'stuks': 2})
    CustomShoppingIngredient.query.delete()
    db.session.commit()
    _plan(_recept('Soep', [('ui', 100, 'g')], serves=2), 2)
    assert _open('ui') == 100


def test_drie_derden_afvinken_laat_geen_ruis_open(app):
    r = _recept('Taart', [('bloem', 1, 'kg')], serves=3)
    _plan(r, 3)
    for _ in range(3):
        afgehandeld.vink_af(JAAR, WEEK, _ing('bloem').id, {'kg': 1 / 3})
    db.session.commit()
    assert not [x for x in build_combined_shopping_list()['open']
                if x['ingredient_id'] == _ing('bloem').id]


def test_een_oude_rij_zonder_getal_dekt_alles_zoals_voorheen(app):
    r = _chili()
    _plan(r, 2)
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK,
                                 ingredient_id=_ing('kidneybonen').id))
    db.session.add(ShoppingListExclusion(year=JAAR, week_number=WEEK,
                                         ingredient_id=_ing('rundergehakt').id))
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=_ing('rundergehakt').id,
                                            amount=100, unit='g'))
    db.session.commit()
    assert _open('kidneybonen') == 0
    assert _open('rundergehakt') == 100   # een oud kruisje verborg nooit losse items


def test_afgevinkt_blok_toont_wat_er_de_laatste_14_dagen_afgevinkt_is(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    _plan(r, 14)
    db.session.add(ShoppingCheck(year=2026, week_number=13,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 3, 23, 12)))
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 7})
    db.session.commit()
    blok = [x for x in build_combined_shopping_list()['checked']
            if x['ingredient_id'] == _ing('kidneybonen').id]
    assert [(x['soort'], x['amount']) for x in blok] == [('afgevinkt', 7)]


def test_een_week_met_alleen_weggehaalde_regels_loopt_niet_meer(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    afgehandeld.haal_weg(2026, 13, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.vink_af(2026, 13, _ing('rundergehakt').id, {'g': 200})
    db.session.commit()
    assert (2026, 13) not in lopende_weken()


def test_een_ingredient_zonder_hoeveelheid_staat_open_tot_je_het_afvinkt(app):
    # 'Naar smaak' (hoeveelheid 0, zoals de aragilde olie op de live-data) is
    # een herinnering: hij hoort op de lijst tot je hem afvinkt of wegklikt.
    _plan(_recept('Salade', [('olijfolie', 0, '')]), 2)
    olie = _ing('olijfolie').id
    assert [x['amount'] for x in build_combined_shopping_list()['open']
            if x['ingredient_id'] == olie] == [0]
    afgehandeld.vink_af(JAAR, WEEK, olie, {'': 0})
    db.session.commit()
    lijst = build_combined_shopping_list()
    assert not [x for x in lijst['open'] if x['ingredient_id'] == olie]
    assert [(x['soort'], x['amount']) for x in lijst['checked']
            if x['ingredient_id'] == olie] == [('afgevinkt', 0)]
