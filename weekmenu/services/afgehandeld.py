"""Wat er per week per ingredient al afgehandeld is: afgevinkt of weggehaald.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status. Op
de lijst staat per week: nodig - afgevinkt - weggehaald (services/shopping.py).

`hoeveelheden` is JSON {eenheid: hoeveelheid}. NULL betekent 'alles', ook wat
er later bij komt: zo bleven rijen van voor v23 werken, en zo houdt
sluit_af een week die geweest is dicht.
"""
import json
from datetime import date, datetime

from weekmenu.extensions import db
from weekmenu.models import ShoppingCheck, ShoppingListExclusion

ALLES = None
EPS = 1e-6


def lees(rij):
    """{eenheid: hoeveelheid} van een rij; {} zonder rij, ALLES zonder getal."""
    if rij is None:
        return {}
    if rij.hoeveelheden is None:
        return ALLES
    return json.loads(rij.hoeveelheden)


def _schrijf(rij, per_eenheid):
    if per_eenheid is ALLES:
        rij.hoeveelheden = None
    else:
        rij.hoeveelheden = json.dumps(
            {u: round(a, 6) for u, a in sorted(per_eenheid.items()) if a > EPS})


def _tel_op(oud, erbij):
    if oud is ALLES:
        return ALLES
    som = dict(oud)
    for eenheid, hoeveel in erbij.items():
        som[eenheid] = som.get(eenheid, 0) + hoeveel
    return som


def _rij(model, jaar, week, ingredient_id, **nieuw):
    rij = model.query.filter_by(year=jaar, week_number=week,
                                ingredient_id=ingredient_id).first()
    if rij is None:
        rij = model(year=jaar, week_number=week, ingredient_id=ingredient_id,
                    hoeveelheden='{}', **nieuw)
        db.session.add(rij)
    return rij


def vink_af(jaar, week, ingredient_id, per_eenheid, via_ah=False):
    """Leg vast dat deze hoeveelheid gekocht is (in de kar ligt)."""
    rij = _rij(ShoppingCheck, jaar, week, ingredient_id, via_ah=via_ah)
    _schrijf(rij, _tel_op(lees(rij), per_eenheid))
    rij.checked_at = datetime.now()
    rij.via_ah = bool(rij.via_ah) or via_ah


def haal_weg(jaar, week, ingredient_id, per_eenheid):
    """Leg vast dat deze hoeveelheid niet gekocht hoeft te worden (✕)."""
    rij = _rij(ShoppingListExclusion, jaar, week, ingredient_id)
    _schrijf(rij, _tel_op(lees(rij), per_eenheid))
    rij.weggehaald_op = datetime.now()


def vinkje_eraf(jaar, week, ingredient_id):
    ShoppingCheck.query.filter_by(year=jaar, week_number=week,
                                  ingredient_id=ingredient_id).delete()


def kruisje_eraf(jaar, week, ingredient_id):
    ShoppingListExclusion.query.filter_by(year=jaar, week_number=week,
                                          ingredient_id=ingredient_id).delete()


def zet_terug(jaar, week, ingredient_id):
    """Alles weer open. Alleen voor uit de voorraad halen: 'ik heb het toch niet
    in huis' spreekt een vinkje van voor de voorraad tegen."""
    vinkje_eraf(jaar, week, ingredient_id)
    kruisje_eraf(jaar, week, ingredient_id)


def sluit_af(jaar, week, ingredient_id):
    """Een week die geweest is blijft dicht, ook voor wat er later bij komt.

    Een nieuw vinkje krijgt de maandag van die week als datum, niet nu: anders
    verschijnt een regel uit augustus in het afgevinkt-blok van de laatste
    veertien dagen (zelfde reden als in migratie v21).
    """
    maandag = datetime.combine(date.fromisocalendar(jaar, week, 1),
                               datetime.min.time()).replace(hour=12)
    rij = _rij(ShoppingCheck, jaar, week, ingredient_id, checked_at=maandag)
    _schrijf(rij, ALLES)


def groei_mee(jaar, week, ingredient_id, eenheid, extra, nodig_oud):
    """Recept bewerken: het al afgehandelde deel groeit naar rato mee.

    Rutger, 4 okt 2026: gekocht is gekocht, ook als hij een gepland recept
    groter maakt. Volledig afgehandeld: niets open. Half: alleen de helft van
    het extra open, want het nog niet gekochte deel volgt het nieuwe recept.
    Samen nooit meer dan het extra, ook als er na inkorten meer afgehandeld
    is dan nodig.
    """
    if extra <= EPS or nodig_oud <= EPS:
        return
    rijen = [r for r in (
        ShoppingCheck.query.filter_by(year=jaar, week_number=week,
                                      ingredient_id=ingredient_id).first(),
        ShoppingListExclusion.query.filter_by(year=jaar, week_number=week,
                                              ingredient_id=ingredient_id).first(),
    ) if r is not None and lees(r) is not ALLES]
    delen = [lees(r).get(eenheid, 0) for r in rijen]
    totaal = sum(delen)
    if totaal <= EPS:
        return
    erbij = extra * min(1.0, totaal / nodig_oud)
    for rij, deel in zip(rijen, delen):
        per = lees(rij)
        per[eenheid] = deel + erbij * deel / totaal
        _schrijf(rij, per)
