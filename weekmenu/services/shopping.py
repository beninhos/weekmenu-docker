from collections import defaultdict
from datetime import date, datetime, timedelta

import requests
from weekmenu.extensions import db
from weekmenu.models import (
    MenuItem, QuickAddItem, CustomShoppingIngredient,
    Ingredient, IngredientUnitConversion, ShoppingListExclusion, PantryIngredient,
    ShoppingCheck, ShoppingListOverride,
)
from weekmenu.constants import _UNIT_BUY_ONE
from weekmenu.services.units import (
    _norm_unit, _calc_multiplier, _convert_unit_for_agg, _calc_ah_qty, format_amount,
)
from weekmenu.services.ah import ah_get_access_token


def _build_shopping_dict(year, week):
    """Bouw geaggregeerde boodschappendict voor een week.

    Returns dict met key (ingredient_id, normalized_unit) -> totaal_hoeveelheid.

    BUG 4 FIX: Custom items worden toegevoegd NA de exclusion filter,
    zodat handmatig toegevoegde items nooit verborgen worden door exclusions.
    """
    conversions = {}
    for conv in IngredientUnitConversion.query.all():
        conversions[(conv.ingredient_id, conv.from_unit)] = (conv.to_unit, conv.factor)
    preferred_units = {
        ing.id: ing.preferred_unit
        for ing in Ingredient.query.filter(Ingredient.preferred_unit.isnot(None)).all()
    }

    shopping_dict = {}

    # 1. Recepten uit weekmenu
    for item in MenuItem.query.filter_by(week_number=week, year=year).all():
        if item.skip_shopping_list or not item.recipe:
            continue
        m = _calc_multiplier(item.recipe.serves, item.people_count)
        for ri in item.recipe.ingredients:
            norm = _norm_unit(ri.unit)
            amount = ri.amount * m
            norm, amount = _convert_unit_for_agg(ri.ingredient_id, norm, amount, conversions, preferred_units)
            shopping_dict[(ri.ingredient_id, norm)] = shopping_dict.get((ri.ingredient_id, norm), 0) + amount

    # 2. Quick-add items
    for qi in QuickAddItem.query.filter_by(week_number=week, year=year).all():
        if not qi.recipe:
            continue
        m = _calc_multiplier(qi.recipe.serves, qi.people_count)
        for ri in qi.recipe.ingredients:
            norm = _norm_unit(ri.unit)
            amount = ri.amount * m
            norm, amount = _convert_unit_for_agg(ri.ingredient_id, norm, amount, conversions, preferred_units)
            shopping_dict[(ri.ingredient_id, norm)] = shopping_dict.get((ri.ingredient_id, norm), 0) + amount

    # 3a. Pantry filter — ingrediënten die altijd in huis zijn nooit op de lijst
    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    shopping_dict = {k: v for k, v in shopping_dict.items() if k[0] not in pantry_ids}

    # 3. Exclusion filter — VOOR custom items (BUG 4 FIX)
    excluded_ids = {
        e.ingredient_id
        for e in ShoppingListExclusion.query.filter_by(year=year, week_number=week).all()
    }
    shopping_dict = {k: v for k, v in shopping_dict.items() if k[0] not in excluded_ids}

    # 4. Custom shopping items — NA exclusion filter, zodat ze altijd zichtbaar zijn
    for ci in CustomShoppingIngredient.query.filter_by(week_number=week, year=year).all():
        norm = _norm_unit(ci.unit)
        amount = ci.amount
        norm, amount = _convert_unit_for_agg(ci.ingredient_id, norm, amount, conversions, preferred_units)
        shopping_dict[(ci.ingredient_id, norm)] = shopping_dict.get((ci.ingredient_id, norm), 0) + amount

    # 5. Merge buy-one entries
    by_ing = defaultdict(list)
    for (ing_id, unit), amount in shopping_dict.items():
        by_ing[ing_id].append((unit, amount))

    merged = {}
    for ing_id, entries in by_ing.items():
        if len(entries) == 1:
            unit, amount = entries[0]
            merged[(ing_id, unit)] = amount
        elif all(u in _UNIT_BUY_ONE for u, _ in entries):
            best_unit, best_amount = max(entries, key=lambda e: e[1])
            total = sum(a for _, a in entries)
            merged[(ing_id, best_unit)] = total
        else:
            for unit, amount in entries:
                merged[(ing_id, unit)] = amount

    return merged


def window_weeks(today=None):
    """ISO-weken van vandaag-7d t/m vandaag+14d, plus handmatige weken tot 4 weken terug."""
    today = today or date.today()
    weeks = []
    for delta in (-7, 0, 7, 14):
        iso = (today + timedelta(days=delta)).isocalendar()
        wk = (iso[0], iso[1])
        if wk not in weeks:
            weeks.append(wk)
    for delta in (-28, -21, -14):
        iso = (today + timedelta(days=delta)).isocalendar()
        wk = (iso[0], iso[1])
        if wk in weeks:
            continue
        has_manual = (
            QuickAddItem.query.filter_by(year=wk[0], week_number=wk[1]).count() > 0
            or CustomShoppingIngredient.query.filter_by(year=wk[0], week_number=wk[1]).count() > 0
        )
        if has_manual:
            weeks.append(wk)
    return sorted(weeks)


def _row_base(ing, unit, amount):
    from weekmenu.constants import CATEGORY_BG
    api_color = ing.ah_product_color or ''
    return {
        'name': ing.display,
        'amount': amount,
        'amount_display': format_amount(amount),
        'unit': unit,
        'category': ing.category,
        'ingredient_id': ing.id,
        'ah_product_id': ing.ah_product_id,
        'ah_product_name': ing.ah_product_name,
        'ah_product_size': ing.ah_product_size,
        'ah_product_image': ing.ah_product_image,
        'ah_product_price': ing.ah_product_price,
        'ah_product_bonus': ing.ah_product_bonus or False,
        'ah_product_bg': api_color or CATEGORY_BG.get(ing.category, '#f0ede8'),
    }


def build_combined_shopping_list(today=None):
    """Combineer de per-week-lijsten van het venster tot één lijst met afvink-status."""
    weeks = window_weeks(today)
    per_week = {wk: _build_shopping_dict(wk[0], wk[1]) for wk in weeks}

    checks = {}
    for c in ShoppingCheck.query.filter(
            db.tuple_(ShoppingCheck.year, ShoppingCheck.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        checks[(c.year, c.week_number, c.ingredient_id)] = c

    overrides = {}
    for o in ShoppingListOverride.query.filter(
            db.tuple_(ShoppingListOverride.year, ShoppingListOverride.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        overrides[(o.year, o.week_number, o.ingredient_id)] = o.qty

    agg = {}
    weeks_by_ingredient = {}
    for (y, w), d in per_week.items():
        for (ing_id, unit), amount in d.items():
            weeks_by_ingredient.setdefault(ing_id, [])
            if (y, w) not in weeks_by_ingredient[ing_id]:
                weeks_by_ingredient[ing_id].append((y, w))
            row = agg.setdefault((ing_id, unit), {
                'weeks': [], 'open_amount': 0.0, 'total_amount': 0.0,
                'checked': [], 'via_ah': False, 'checked_at': None,
            })
            row['weeks'].append((y, w))
            row['total_amount'] += amount
            c = checks.get((y, w, ing_id))
            if c:
                row['checked'].append((y, w))
                row['via_ah'] = row['via_ah'] or c.via_ah
                if row['checked_at'] is None or c.checked_at > row['checked_at']:
                    row['checked_at'] = c.checked_at
            else:
                row['open_amount'] += amount

    open_rows, checked_rows = [], []
    cutoff = datetime.now() - timedelta(days=14)
    for (ing_id, unit), r in agg.items():
        ing = Ingredient.query.get(ing_id)
        if not ing:
            continue
        fully_checked = len(r['checked']) == len(r['weeks'])
        if fully_checked:
            if r['checked_at'] and r['checked_at'] < cutoff:
                continue
            row = _row_base(ing, unit, r['total_amount'])
            row['via_ah'] = r['via_ah']
            row['checked_at'] = r['checked_at']
            checked_rows.append(row)
        else:
            row = _row_base(ing, unit, r['open_amount'])
            qty = 0
            for (y, w) in r['weeks']:
                if (y, w) in r['checked']:
                    continue
                wk_amount = per_week[(y, w)].get((ing_id, unit), 0)
                qty += overrides.get((y, w, ing_id), _calc_ah_qty(ing, wk_amount, unit))
            row['default_qty'] = _calc_ah_qty(ing, r['open_amount'], unit)
            row['qty'] = qty
            open_rows.append(row)

    quick_add = []
    for qi in QuickAddItem.query.filter(
            db.tuple_(QuickAddItem.year, QuickAddItem.week_number)
              .in_([(y, w) for (y, w) in weeks])).all():
        if qi.recipe:
            quick_add.append({'id': qi.id, 'recipe_id': qi.recipe_id,
                              'recipe_name': qi.recipe.name,
                              'people_count': qi.people_count})

    return {'open': open_rows, 'checked': checked_rows,
            'weeks_by_ingredient': weeks_by_ingredient, 'quick_add': quick_add}


def send_dict_to_ah(shopping_dict, qty_overrides):
    """Stuur een shopping-dict naar AH (lijst of actieve order). Returns (payload, status, sent_ingredient_ids)."""
    from weekmenu.constants import (_AH_HEADERS, _AH_SHOPPINGLIST_URL,
                                    _AH_ORDER_ACTIVE_URL, _AH_ORDER_ITEMS_URL)

    access_token = ah_get_access_token()
    if not access_token:
        return ({'status': 'error',
                 'message': 'Geen AH-account gekoppeld. Ga naar Instellingen.'}, 401, [])

    if not shopping_dict:
        return ({'status': 'ok', 'sent': 0, 'not_linked': [],
                 'message': 'Boodschappenlijst is leeg'}, 200, [])

    headers = {**_AH_HEADERS, 'Authorization': f'Bearer {access_token}',
               'Content-Type': 'application/json'}

    merged = defaultdict(int)
    name_by_pid = {}
    not_linked = []
    sent_ingredient_ids = []
    for (ing_id, unit), amount in shopping_dict.items():
        ing = Ingredient.query.get(ing_id)
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
        return ({'status': 'ok', 'sent': 0, 'not_linked': not_linked,
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
    return ({'status': 'ok', 'sent': sent, 'not_linked': not_linked,
             'message': msg}, 200, sent_ingredient_ids)
