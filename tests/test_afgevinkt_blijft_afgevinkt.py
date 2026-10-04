"""Afgevinkt blijft afgevinkt; toevoegen zet alleen het nieuwe op de lijst.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import ShoppingCheck, ShoppingListExclusion
from weekmenu.services import afgehandeld


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
