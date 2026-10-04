"""Wat er per week per ingredient al afgehandeld is: afgevinkt of weggehaald.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status. Op
de lijst staat per week: nodig - afgevinkt - weggehaald (services/shopping.py).

`hoeveelheden` is JSON {eenheid: hoeveelheid}. NULL betekent 'alles', ook wat
er later bij komt: zo bleven rijen van voor v23 werken, en zo houdt
sluit_af een week die geweest is dicht.
"""
import functools
import json
import threading
from datetime import date, datetime

from weekmenu.extensions import db
from weekmenu.models import ShoppingCheck, ShoppingListExclusion

ALLES = None
EPS = 1e-6

# Afvinken en wegklikken tellen op bij wat er al lag. Twee verzoeken die
# dezelfde lijst lazen tellen dus dubbel: een dubbele tik op ✕ legde 200 g
# gehakt twee keer weg, en een later gepland recept viel daarna stil van de
# lijst. De app draait als één proces (app.py, use_reloader=False), dus een
# slot in het proces houdt de schrijvende gebaren één voor één.
_slot = threading.RLock()


def een_tegelijk(view):
    """Laat een schrijvend lijstgebaar pas lezen als het vorige klaar is."""
    @functools.wraps(view)
    def omhulsel(*args, **kwargs):
        with _slot:
            return view(*args, **kwargs)
    return omhulsel


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
        # Een eenheid met 0 blijft staan: zo onthoudt een vinkje ook een regel
        # zonder hoeveelheid ('naar smaak').
        rij.hoeveelheden = json.dumps(
            {u: round(max(a, 0.0), 9) for u, a in sorted(per_eenheid.items()) if a > -EPS})


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


def vul_hoeveelheden_aan():
    """Eenmalig na v23: elke rij zonder getal krijgt wat er toen nodig was.

    Een rij van voor v23 betekende 'alles' en blijft dat doen tot hij gevuld
    is: de lijst ziet er na het vullen precies zo uit als ervoor. Pas daarna
    zet een toevoeging alleen het nieuwe erop. Een vinkje dekt nodig, een
    kruisje het receptdeel (losse items verborg het nooit). Een rij voor iets
    wat die week niet (meer) nodig is krijgt {} -- behalve in een week die
    geweest is: die blijft 'alles' en dus dicht.
    """
    from weekmenu.models import Settings
    from weekmenu.services.shopping import omrekening, week_nodig
    vlag = Settings.query.filter_by(key='afgehandeld_vullen').first()
    if vlag is None:
        return 0
    iso = date.today().isocalendar()
    deze_week = (iso[0], iso[1])
    omr, per_week, gevuld = omrekening(), {}, 0
    for model, deel in ((ShoppingCheck, 0), (ShoppingListExclusion, 1)):
        for rij in model.query.filter(model.hoeveelheden.is_(None)).all():
            wk = (rij.year, rij.week_number)
            if wk not in per_week:
                per_week[wk] = week_nodig(wk[0], wk[1], omr)
            per = {u: h for (i, u), h in per_week[wk][deel].items() if i == rij.ingredient_id}
            if not per and wk < deze_week:
                # Toen niet nodig (meestal: stond in de voorraad) in een week die
                # geweest is: 'alles' laten, anders gaat die week open zodra het
                # de kast uit gaat.
                continue
            _schrijf(rij, per)
            gevuld += 1
    db.session.delete(vlag)
    db.session.commit()
    print(f'[afgehandeld] {gevuld} vinkjes en kruisjes gevuld met hun hoeveelheid')
    return gevuld
