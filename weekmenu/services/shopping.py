from collections import defaultdict

from weekmenu.extensions import db
from weekmenu.models import (
    MenuItem, QuickAddItem, CustomShoppingIngredient,
    Ingredient, IngredientUnitConversion, ShoppingListExclusion, PantryIngredient,
)
from weekmenu.constants import _UNIT_BUY_ONE
from weekmenu.services.units import (
    _norm_unit, _calc_multiplier, _convert_unit_for_agg,
)


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
