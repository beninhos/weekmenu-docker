"""NL-seizoens-advies: welke groente/fruit deze maand in seizoen is,
en welke recepten die ingrediënten gebruiken.

De statische lookup staat in `weekmenu.constants`. Het matching-mechanisme
is puur exact + alias — varianten ("bladspinazie" voor "spinazie",
"verse witte asperges" voor "asperge") horen als IngredientAlias in de DB.
"""
from datetime import date

from weekmenu.constants import SEASONAL_NL, MONTH_NAMES_NL
from weekmenu.models import Ingredient, IngredientAlias


def current_month():
    return date.today().month


def seasonal_names(month=None):
    return SEASONAL_NL.get(month or current_month(), [])


def resolve_seasonal_ingredients(month=None):
    """Match seizoens-termen tegen Ingredient.name en IngredientAlias.alias.

    Returns:
        list[dict]: per seizoens-term `{name, display_name, matched, ingredient_ids}`.
        `matched=False` items worden getoond in UI als grijze chip (signaleert
        dat er een alias ontbreekt in de DB).
    """
    names = seasonal_names(month)
    if not names:
        return []

    by_name = {
        i.name: i
        for i in Ingredient.query.filter(Ingredient.name.in_(names)).all()
    }
    by_alias = {
        a.alias: a.ingredient
        for a in IngredientAlias.query.filter(IngredientAlias.alias.in_(names)).all()
    }

    results = []
    for n in names:
        ing = by_name.get(n) or by_alias.get(n)
        results.append({
            'name': n,
            'display_name': ing.display if ing else n.capitalize(),
            'matched': ing is not None,
            'ingredient_ids': [ing.id] if ing else [],
        })
    return results
