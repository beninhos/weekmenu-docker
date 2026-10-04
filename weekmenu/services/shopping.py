import logging
from collections import defaultdict, namedtuple
from datetime import date, datetime, time, timedelta

import requests
from weekmenu.extensions import db
from weekmenu.models import (
    MenuItem, QuickAddItem, CustomShoppingIngredient,
    Ingredient, IngredientUnitConversion, PantryIngredient,
    ShoppingCheck, ShoppingListExclusion, ShoppingListOverride,
)
from weekmenu.constants import _UNIT_BUY_ONE
from weekmenu.services.afgehandeld import ALLES, EPS, lees
from weekmenu.services.units import (
    _norm_unit, _calc_multiplier, _convert_unit_for_agg, _calc_ah_qty, format_amount,
)
from weekmenu.services.ah import ah_get_access_token

log = logging.getLogger(__name__)
_al_gemeld = set()


def omrekening():
    """Wat elke weekberekening nodig heeft; een keer ophalen per lijst."""
    conversions = {(c.ingredient_id, c.from_unit): (c.to_unit, c.factor)
                   for c in IngredientUnitConversion.query.all()}
    preferred_units = {i.id: i.preferred_unit for i in
                       Ingredient.query.filter(Ingredient.preferred_unit.isnot(None)).all()}
    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    return conversions, preferred_units, pantry_ids


def bijdrage_van_regel(ri, serves, people_count, omr):
    """(ingredient, eenheid, hoeveelheid) van één receptregel voor zoveel personen."""
    conversions, preferred_units, _ = omr
    eenheid, hoeveel = _convert_unit_for_agg(
        ri.ingredient_id, _norm_unit(ri.unit),
        ri.amount * _calc_multiplier(serves, people_count),
        conversions, preferred_units)
    return ri.ingredient_id, eenheid, hoeveel


def _voeg_samen_per_ingredient(per_sleutel):
    """Gewichts- en volume-eenheden van één ingredient tot één regel, zoals altijd."""
    per_ing = defaultdict(list)
    for (ing_id, eenheid), hoeveel in per_sleutel.items():
        per_ing[ing_id].append((eenheid, hoeveel))
    uit = {}
    for ing_id, regels in per_ing.items():
        if len(regels) > 1 and all(u in _UNIT_BUY_ONE for u, _ in regels):
            beste, _ = max(regels, key=lambda r: r[1])
            uit[(ing_id, beste)] = sum(h for _, h in regels)
        else:
            for eenheid, hoeveel in regels:
                uit[(ing_id, eenheid)] = hoeveel
    return uit


def week_nodig(jaar, week, omr=None):
    """Wat een week vraagt, per (ingredient, eenheid), na voorraad en omrekening.

    Geeft (nodig, receptdeel, bronnen). Het receptdeel is nodig zonder losse
    items: een kruisje van voor v23 verborg alleen dat deel (BUG 4 FIX).
    Afgevinkt en weggehaald gaan er hier nog niet af; dat doet _week_stand.
    """
    omr = omr or omrekening()
    conversions, preferred_units, pantry_ids = omr
    recept = defaultdict(float)
    bronnen = defaultdict(set)

    def tel(item):
        if not item.recipe:
            return
        for ri in item.recipe.ingredients:
            if ri.ingredient_id in pantry_ids:
                continue
            ing, eenheid, hoeveel = bijdrage_van_regel(
                ri, item.recipe.serves, item.people_count, omr)
            recept[(ing, eenheid)] += hoeveel
            bronnen[ing].add(item.recipe.name)

    for mi in MenuItem.query.filter_by(week_number=week, year=jaar).all():
        if not mi.skip_shopping_list:
            tel(mi)
    for qi in QuickAddItem.query.filter_by(week_number=week, year=jaar).all():
        tel(qi)

    alles = defaultdict(float, recept)
    for ci in CustomShoppingIngredient.query.filter_by(week_number=week, year=jaar).all():
        eenheid, hoeveel = _convert_unit_for_agg(
            ci.ingredient_id, _norm_unit(ci.unit), ci.amount, conversions, preferred_units)
        alles[(ci.ingredient_id, eenheid)] += hoeveel

    return _voeg_samen_per_ingredient(alles), _voeg_samen_per_ingredient(recept), bronnen


def _doeleenheid(ing_id, eenheid, hoeveel, nodig_ing, omr):
    if eenheid in nodig_ing:
        return eenheid, hoeveel
    conversions, preferred_units, _ = omr
    naar, omgerekend = _convert_unit_for_agg(ing_id, eenheid, hoeveel,
                                             conversions, preferred_units)
    if naar in nodig_ing:
        return naar, omgerekend
    gewicht = [u for u in nodig_ing if u in _UNIT_BUY_ONE]
    if eenheid in _UNIT_BUY_ONE and len(gewicht) == 1:
        return gewicht[0], hoeveel
    return None


def _gedekt(jaar, week, ing_id, nodig_ing, per, bij_alles, omr):
    """Hoeveel van nodig_ing (per eenheid) een vinkje of kruisje dekt.

    Geeft (gedekt per eenheid, eenheden die het vinkje noemt). Dat tweede is
    nodig voor een regel zonder hoeveelheid: daar dekt een vinkje niets, maar
    handelt het de regel wel af. Een eenheid die niet meer te plaatsen is telt
    niet mee: liever een regel die je nog eens afvinkt dan een regel die stil
    verdwijnt (zelfde keuze als in services/ingredienten.py::_wis_weekbesluiten).
    """
    if per is ALLES:
        return ({u: min(nodig_ing[u], bij_alles.get(u, 0)) for u in nodig_ing},
                {u for u in nodig_ing if u in bij_alles})
    gedekt = dict.fromkeys(nodig_ing, 0.0)
    genoemd = set()
    for eenheid, hoeveel in per.items():
        doel = _doeleenheid(ing_id, eenheid, hoeveel, nodig_ing, omr)
        if doel is None:
            sleutel = (jaar, week, ing_id, eenheid)
            if nodig_ing and sleutel not in _al_gemeld:
                _al_gemeld.add(sleutel)
                log.warning('Afgehandeld in %s telt niet mee voor de lijst: %s %s (nodig: %s)',
                            sleutel[:3], hoeveel, eenheid, sorted(nodig_ing))
            continue
        gedekt[doel[0]] += doel[1]
        genoemd.add(doel[0])
    return {u: min(nodig_ing[u], gedekt[u]) for u in nodig_ing}, genoemd


def _afhandeling(weken):
    """Vinkjes, kruisjes en aantal-overrides van deze weken, per (jaar, week, ingredient)."""
    if not weken:
        return {}, {}, {}

    def per_sleutel(model):
        return {(r.year, r.week_number, r.ingredient_id): r for r in model.query.filter(
            db.tuple_(model.year, model.week_number).in_(list(weken))).all()}

    overrides = {k: r.qty for k, r in per_sleutel(ShoppingListOverride).items()}
    return per_sleutel(ShoppingCheck), per_sleutel(ShoppingListExclusion), overrides


# Eén eenheid van één ingredient in één week. `staat_open` en de twee
# toon-vlaggen zijn er voor regels zonder hoeveelheid ('naar smaak'): die staan
# open tot je ze afvinkt of wegklikt, ook al is open daar altijd 0.
Regel = namedtuple('Regel', 'open afgevinkt weggehaald staat_open '
                            'toon_afgevinkt toon_weggehaald')


def _week_stand(jaar, week, omr, checks, excls):
    """Per ingredient per eenheid een Regel: open = nodig - afgevinkt - weggehaald."""
    nodig, receptdeel, bronnen = week_nodig(jaar, week, omr)
    per_ing, recept_ing = defaultdict(dict), defaultdict(dict)
    for (ing, u), h in nodig.items():
        per_ing[ing][u] = h
    for (ing, u), h in receptdeel.items():
        recept_ing[ing][u] = h
    stand = {}
    for ing, nodig_ing in per_ing.items():
        afg, afg_genoemd = _gedekt(jaar, week, ing, nodig_ing,
                                   lees(checks.get((jaar, week, ing))), nodig_ing, omr)
        rest = {u: nodig_ing[u] - afg[u] for u in nodig_ing}
        weg, weg_genoemd = _gedekt(jaar, week, ing, rest,
                                   lees(excls.get((jaar, week, ing))),
                                   recept_ing.get(ing, {}), omr)
        stand[ing] = {}
        for u in nodig_ing:
            open_ = max(0.0, rest[u] - weg[u])
            zonder = nodig_ing[u] <= EPS
            stand[ing][u] = Regel(
                open_, afg[u], weg[u],
                staat_open=(not (u in afg_genoemd or u in weg_genoemd)) if zonder else open_ > EPS,
                toon_afgevinkt=(u in afg_genoemd) if zonder else afg[u] > EPS,
                toon_weggehaald=(u in weg_genoemd and u not in afg_genoemd) if zonder
                else weg[u] > EPS)
    return stand, bronnen


def weken_van_recept(recipe):
    """De weken waarin dit recept boodschappen levert."""
    weken = {(mi.year, mi.week_number) for mi in
             MenuItem.query.filter_by(recipe_id=recipe.id).all() if not mi.skip_shopping_list}
    weken |= {(qi.year, qi.week_number) for qi in
              QuickAddItem.query.filter_by(recipe_id=recipe.id).all()}
    return weken


def momentopname(recipe):
    """Wat de weken van dit recept nodig hadden, vlak voor een bewerking."""
    omr = omrekening()
    return {'ingredienten': {ri.ingredient_id for ri in recipe.ingredients},
            'nodig': {wk: week_nodig(wk[0], wk[1], omr)[0] for wk in weken_van_recept(recipe)}}


def window_weeks():
    """Alle weken waarvoor iets gepland staat. Welke daarvan nog iets open
    hebben rekent build_combined_shopping_list uit: wat afgevinkt of weggehaald
    is blijft dat, ook als er later iets bij komt (Rutger, 4 okt 2026)."""
    weken = set()
    for model in (MenuItem, QuickAddItem, CustomShoppingIngredient):
        for y, w in db.session.query(model.year, model.week_number).distinct():
            weken.add((y, w))
    return sorted(weken)


def lopende_weken(today=None):
    """De weken waar een zijdelingse wijziging nog in mag doorwerken.

    Een week loopt als hij niet achter ons ligt, of als er nog iets open staat.
    Wat afgevinkt of weggehaald is telt als klaar. Andersom is een week van
    twee maanden terug waarin niets meer open staat echt geweest, en hoort een
    receptwijziging daar niets meer te openen -- dat was de kapsalon van week 32.
    De kalender beantwoordt hier alleen de vraag 'ligt deze week achter ons'.
    """
    iso = (today or date.today()).isocalendar()
    nu = (iso[0], iso[1])
    weken = window_weeks()
    omr = omrekening()
    checks, excls, _ = _afhandeling(weken)
    lopend = set()
    for wk in weken:
        if wk >= nu:
            lopend.add(wk)
            continue
        stand, _ = _week_stand(wk[0], wk[1], omr, checks, excls)
        if any(r.staat_open for per in stand.values() for r in per.values()):
            lopend.add(wk)
    return lopend


def _row_base(ing, unit, amount, recipe_names=None):
    from weekmenu.constants import CATEGORY_BG
    api_color = ing.ah_product_color or ''
    return {
        'name': ing.display,
        'amount': amount,
        'amount_display': format_amount(amount),
        'unit': unit,
        'category': ing.category,
        'ingredient_id': ing.id,
        'recipes': sorted(recipe_names) if recipe_names else [],
        'ah_product_id': ing.ah_product_id,
        'ah_product_name': ing.ah_product_name,
        'ah_product_size': ing.ah_product_size,
        'ah_product_image': ing.ah_product_image,
        'ah_product_price': ing.ah_product_price,
        'ah_product_bonus': ing.ah_product_bonus or False,
        'ah_product_bg': api_color or CATEGORY_BG.get(ing.category, '#f0ede8'),
        'bron': ing.bron or 'ah',
    }




def build_combined_shopping_list(today=None):
    """De boodschappenlijst over alle weken: open = nodig - afgevinkt - weggehaald.

    Het afgevinkt-blok toont wat er de laatste veertien dagen is afgevinkt of
    weggehaald, met de hoeveelheid van dat moment -- niet de som van alle weken
    ooit (kidneybonen stond er als 9 blik: week 13 + 33 + 40).
    """
    grens = datetime.combine(today or date.today(), time.min) - timedelta(days=14)
    weken = window_weeks()
    omr = omrekening()
    checks, excls, overrides = _afhandeling(weken)
    ingredienten = {}

    def ingredient(ing_id):
        if ing_id not in ingredienten:
            ingredienten[ing_id] = db.session.get(Ingredient, ing_id)
        return ingredienten[ing_id]

    open_agg, blok = {}, {}
    open_per_week = defaultdict(dict)
    afgevinkt_weken, weggehaald_weken = defaultdict(list), defaultdict(list)
    for (y, w) in weken:
        stand, bronnen = _week_stand(y, w, omr, checks, excls)
        for ing_id, per_eenheid in stand.items():
            ing = ingredient(ing_id)
            if not ing:
                continue
            check, excl = checks.get((y, w, ing_id)), excls.get((y, w, ing_id))
            vers_vinkje = bool(check and check.checked_at and check.checked_at >= grens)
            vers_kruisje = bool(excl and excl.weggehaald_op and excl.weggehaald_op >= grens)
            for eenheid, r in per_eenheid.items():
                if r.staat_open:
                    open_per_week[ing_id].setdefault((y, w), {})[eenheid] = r.open
                    rij = open_agg.setdefault((ing_id, eenheid),
                                              {'amount': 0.0, 'qty': 0, 'bronnen': set()})
                    rij['amount'] += r.open
                    rij['qty'] += overrides.get((y, w, ing_id)) or _calc_ah_qty(ing, r.open, eenheid)
                    rij['bronnen'] |= bronnen.get(ing_id, set())
                for soort, vers, toon, deel, rij_db in (
                        ('afgevinkt', vers_vinkje, r.toon_afgevinkt, r.afgevinkt, check),
                        ('weggehaald', vers_kruisje, r.toon_weggehaald, r.weggehaald, excl)):
                    if not (vers and toon):
                        continue
                    b = blok.setdefault((ing_id, eenheid, soort),
                                        {'amount': 0.0, 'bronnen': set(), 'via_ah': False,
                                         'checked_at': None})
                    b['amount'] += deel
                    b['bronnen'] |= bronnen.get(ing_id, set())
                    moment = rij_db.checked_at if soort == 'afgevinkt' else rij_db.weggehaald_op
                    b['checked_at'] = max(m for m in (b['checked_at'], moment) if m)
                    b['via_ah'] = b['via_ah'] or (soort == 'afgevinkt' and bool(rij_db.via_ah))
            if vers_vinkje:
                afgevinkt_weken[ing_id].append((y, w))
            if vers_kruisje:
                weggehaald_weken[ing_id].append((y, w))

    open_rows = []
    for (ing_id, eenheid), r in open_agg.items():
        row = _row_base(ingredient(ing_id), eenheid, r['amount'], r['bronnen'])
        row['qty'] = r['qty']
        row['default_qty'] = _calc_ah_qty(ingredient(ing_id), r['amount'], eenheid)
        open_rows.append(row)

    checked_rows = []
    for (ing_id, eenheid, soort), b in blok.items():
        row = _row_base(ingredient(ing_id), eenheid, b['amount'], b['bronnen'])
        row.update(soort=soort, via_ah=b['via_ah'], checked_at=b['checked_at'])
        checked_rows.append(row)

    quick_add = []
    if weken:
        for qi in QuickAddItem.query.filter(
                db.tuple_(QuickAddItem.year, QuickAddItem.week_number).in_(weken)).all():
            if qi.recipe:
                quick_add.append({'id': qi.id, 'recipe_id': qi.recipe_id,
                                  'recipe_name': qi.recipe.name,
                                  'people_count': qi.people_count,
                                  'year': qi.year, 'week': qi.week_number})

    return {'open': open_rows, 'checked': checked_rows,
            'open_per_week': dict(open_per_week),
            'weeks_by_ingredient': {i: sorted(wk) for i, wk in open_per_week.items()},
            'afgevinkt_weken': dict(afgevinkt_weken),
            'weggehaald_weken': dict(weggehaald_weken),
            'quick_add': quick_add}


def send_dict_to_ah(shopping_dict, qty_overrides):
    """Stuur een shopping-dict naar AH (lijst of actieve order). Returns (payload, status, sent_ingredient_ids)."""
    from weekmenu.constants import (_AH_HEADERS, _AH_SHOPPINGLIST_URL,
                                    _AH_ORDER_ACTIVE_URL, _AH_ORDER_ITEMS_URL)

    access_token = ah_get_access_token()
    if not access_token:
        return ({'status': 'error',
                 'message': 'Geen AH-account gekoppeld. Ga naar Instellingen.'}, 401, [])

    if not shopping_dict:
        return ({'status': 'success', 'sent': 0, 'not_linked': [],
                 'message': 'Boodschappenlijst is leeg'}, 200, [])

    headers = {**_AH_HEADERS, 'Authorization': f'Bearer {access_token}',
               'Content-Type': 'application/json'}

    merged = defaultdict(int)
    name_by_pid = {}
    not_linked = []
    sent_ingredient_ids = []
    for (ing_id, unit), amount in shopping_dict.items():
        ing = db.session.get(Ingredient, ing_id)
        if not ing:
            continue
        if not ing.ah_product_id:
            not_linked.append(ing.display)
            continue
        qty = qty_overrides.get(ing_id, _calc_ah_qty(ing, amount, unit))
        merged[ing.ah_product_id] += max(int(qty or 1), 1)
        name_by_pid.setdefault(ing.ah_product_id, ing.display)
        sent_ingredient_ids.append(ing_id)

    if not merged:
        return ({'status': 'success', 'sent': 0, 'not_linked': not_linked,
                 'message': 'Geen gekoppelde AH-producten in de lijst. '
                            'Koppel ze eerst via AH-producten.'}, 200, [])

    order_id = None
    try:
        r = requests.get(_AH_ORDER_ACTIVE_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            order_id = (r.json() or {}).get('id')
    except Exception:
        pass

    try:
        if order_id:
            items = [{'productId': pid, 'quantity': qty, 'originCode': 'PRD',
                      'description': '', 'strikethrough': False}
                     for pid, qty in merged.items()]
            resp = requests.put(
                _AH_ORDER_ITEMS_URL, json={'items': items},
                headers={**headers, 'Appie-Current-Order-Id': str(order_id)},
                timeout=20)
            target = 'bestelling'
        else:
            items = [{'originCode': 'PRD', 'productId': pid,
                      'quantity': qty, 'type': 'SHOPPABLE',
                      'description': name_by_pid.get(pid, ''),
                      'searchTerm': name_by_pid.get(pid, ''),
                      'strikeThrough': False}
                     for pid, qty in merged.items()]
            resp = requests.patch(_AH_SHOPPINGLIST_URL, json={'items': items},
                                  headers=headers, timeout=20)
            target = 'boodschappenlijst'
        resp.raise_for_status()
    except Exception as e:
        from flask import current_app
        current_app.logger.warning('AH send mislukt: %r', e)
        return ({'status': 'error', 'sent': 0, 'not_linked': not_linked,
                 'message': f'Versturen naar AH mislukt: {e}'}, 502, [])

    sent = len(merged)
    msg = f'{sent} product{"en" if sent != 1 else ""} toegevoegd aan je AH-{target}'
    if not_linked:
        msg += f'. {len(not_linked)} nog niet gekoppeld (overgeslagen): {", ".join(not_linked[:5])}'
    return ({'status': 'success', 'sent': sent, 'not_linked': not_linked,
             'order_id': order_id, 'message': msg}, 200, sent_ingredient_ids)
