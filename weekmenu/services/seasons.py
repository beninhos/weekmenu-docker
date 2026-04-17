"""NL-seizoens-advies: welke groente/fruit is deze maand in seizoen,
en welke recepten gebruiken die ingrediënten.

Statische lookup op basis van groentefruit.nl. Namen zijn gekozen zodat ze
matchen met de canonical `Ingredient.name` (lowercase, enkelvoud).
"""
from datetime import date

from weekmenu.models import Ingredient, IngredientAlias


SEASONAL_NL = {
    1:  ['boerenkool', 'knolselderij', 'pastinaak', 'prei', 'rode kool',
         'witte kool', 'spruitjes', 'winterwortel', 'witlof', 'aardappel',
         'appel', 'peer'],
    2:  ['boerenkool', 'knolselderij', 'pastinaak', 'prei', 'rode kool',
         'spruitjes', 'winterwortel', 'witlof', 'appel', 'peer'],
    3:  ['prei', 'spruitjes', 'winterwortel', 'witlof', 'pastinaak',
         'rabarber', 'veldsla'],
    4:  ['radijs', 'rabarber', 'asperge', 'spinazie', 'veldsla',
         'postelein', 'witlof'],
    5:  ['asperge', 'radijs', 'rabarber', 'spinazie', 'tuinbonen',
         'doperwten', 'komkommer', 'aardbei', 'postelein'],
    6:  ['asperge', 'aardbei', 'courgette', 'tuinbonen', 'doperwten',
         'radijs', 'tomaat', 'bloemkool', 'sla', 'komkommer', 'spinazie'],
    7:  ['courgette', 'bloemkool', 'tomaat', 'aardbei', 'framboos',
         'bosbes', 'komkommer', 'paprika', 'sla', 'sperziebonen',
         'bleekselderij'],
    8:  ['tomaat', 'courgette', 'paprika', 'aubergine', 'sperziebonen',
         'mais', 'pruim', 'braam', 'framboos', 'bloemkool', 'komkommer',
         'perzik'],
    9:  ['pompoen', 'courgette', 'paprika', 'aubergine', 'tomaat', 'appel',
         'peer', 'druif', 'pruim', 'braam', 'spinazie', 'prei', 'rode kool'],
    10: ['pompoen', 'knolselderij', 'pastinaak', 'boerenkool', 'prei',
         'rode kool', 'witte kool', 'appel', 'peer', 'witlof', 'spruitjes'],
    11: ['pompoen', 'boerenkool', 'knolselderij', 'pastinaak', 'rode kool',
         'spruitjes', 'witte kool', 'witlof', 'winterwortel', 'appel', 'peer'],
    12: ['boerenkool', 'knolselderij', 'pastinaak', 'prei', 'rode kool',
         'spruitjes', 'winterwortel', 'witlof', 'appel', 'peer'],
}

MONTH_NAMES_NL = [
    'januari', 'februari', 'maart', 'april', 'mei', 'juni',
    'juli', 'augustus', 'september', 'oktober', 'november', 'december',
]


def current_month():
    return date.today().month


def seasonal_names(month=None):
    return SEASONAL_NL.get(month or current_month(), [])


def resolve_seasonal_ingredients(month=None):
    """Zoek voor elke seizoens-naam bijbehorende ingrediënten.

    Matcht op exacte name, alias én substring (zodat "asperge" ook
    "verse witte asperges" matcht en "spinazie" ook "bladspinazie").

    Returns:
        list[dict]: `[{name, display_name, matched, ingredient_ids}]` per
        seizoens-term. `ingredient_ids` is een lijst — een seizoens-term kan
        meerdere varianten (wit/groen asperges) matchen.
    """
    names = seasonal_names(month)
    if not names:
        return []

    results = []
    for n in names:
        ids = set()

        exact = Ingredient.query.filter(Ingredient.name == n).first()
        if exact:
            ids.add(exact.id)

        alias = IngredientAlias.query.filter(IngredientAlias.alias == n).first()
        if alias:
            ids.add(alias.ingredient_id)

        like_hits = Ingredient.query.filter(Ingredient.name.like(f'%{n}%')).all()
        for h in like_hits:
            ids.add(h.id)

        results.append({
            'name': n,
            'display_name': n.capitalize(),
            'matched': bool(ids),
            'ingredient_ids': sorted(ids),
        })
    return results
