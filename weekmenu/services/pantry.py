"""Pantry CRUD — items marked as "altijd op voorraad", used by shopping-list filter and Ecobooster."""
import re

from weekmenu.extensions import db
from weekmenu.models import Ingredient, IngredientAlias, PantryIngredient, RecipeIngredient
from weekmenu.services.units import _normalize_ingredient


def list_pantry():
    """Return all pantry items as a list of dicts for the API."""
    items = PantryIngredient.query.order_by(PantryIngredient.id).all()
    return [{
        'id': p.id,
        'ingredient_id': p.ingredient_id,
        'name': p.ingredient.display,
    } for p in items]


def add_to_pantry(ingredient_id):
    """Add an ingredient to the pantry. Returns (result_dict, status_code)."""
    if not ingredient_id:
        return {'status': 'error', 'message': 'ingredient_id verplicht'}, 400

    existing = PantryIngredient.query.filter_by(ingredient_id=ingredient_id).first()
    if existing:
        return {'status': 'exists'}, 200

    p = PantryIngredient(ingredient_id=ingredient_id)
    db.session.add(p)
    db.session.commit()
    return {
        'status': 'ok',
        'id': p.id,
        'ingredient_id': p.ingredient_id,
        'name': p.ingredient.display,
    }, 200


def remove_from_pantry(ingredient_id):
    """Remove an ingredient from the pantry (idempotent)."""
    p = PantryIngredient.query.filter_by(ingredient_id=ingredient_id).first()
    if p:
        db.session.delete(p)
        db.session.commit()
    return {'status': 'ok'}


# ── Voorraadstatus voor geïmporteerde receptregels ───────────────────────

# Categorieën waar kastartikelen in liggen. Verse producten horen hier niet:
# zolang verse kruiden nog in 'Kruiden & Specerijen' zitten vangt _is_dose ze af.
KAST_CATEGORIES = {
    'Kruiden & Specerijen',
    'Oliën, Sauzen & Smaakmakers',
    'Bakken & Desserts',
    'Ontbijt & Beleg',
    'Conserven & Peulvruchten',
    # Oude naam, komt nog voor in ingredients_json van wachtende drafts:
    'Ontbijt, Bakken & Desserts',
}

DOSE_UNITS = {'el', 'tl', 'kl', 'snufje', 'snuf', 'mespunt', 'scheutje', 'scheut'}

# Vangnet voor regels die nog met oude categorienamen zijn opgeslagen
# (ingredients_json van wachtende drafts): verse kruiden horen nooit in de
# kast, ook niet als hun regel nog 'Kruiden & Specerijen' zegt. Nieuwe regels
# vallen al af doordat de guesser ze in 'Verse Kruiden' plaatst.
_VERS_RE = re.compile(r'\b(verse?|takjes?|blaadjes?|bosje)\b')


def _is_dose(unit, amount):
    """True als de receptregel een dosis noemt, geen hele verpakking.

    '1 tl kurkuma' is een kastartikel, '140 g tomatenpuree' koop je per recept.
    """
    unit = (unit or '').strip().lower()
    amount = amount or 0
    if unit in DOSE_UNITS:
        return True
    if unit in ('g', 'ml'):
        return 0 < amount <= 100
    return not unit and not amount


def _variant_key(name):
    """Sleutel die spatiëring en leestekens negeert: 'rode wijnazijn' == 'rodewijnazijn'."""
    return re.sub(r'[^a-z0-9]', '', _normalize_ingredient((name or '').lower()))


def _match_existing(name, alias_map, name_map):
    normalized = _normalize_ingredient((name or '').lower().strip())
    return alias_map.get(normalized) or name_map.get(normalized)


def annotate_pantry_status(ingredients):
    """Verrijk geïmporteerde ingrediëntregels met voorraadinformatie.

    Gemini levert losse namen aan; zonder deze stap weet het formulier niet of
    'olijfolie' al in de voorraadkast staat, en wordt 'extra vierge olijfolie'
    een nieuw ingredient naast het bestaande.

    Per regel komt erbij:
      id           bestaand Ingredient, of None
      in_pantry    staat al op voorraad — bevestigd, geen klik nodig
      pantry_hint  'in_pantry' | 'variant' | 'suggest' | None
      variant_of   {'id', 'name'} als de naam samenvalt met een voorraaditem
                   dat onder een andere id bekend staat
    """
    if not ingredients:
        return ingredients

    names = [(i.get('name') or '').lower().strip() for i in ingredients]
    normalized = [_normalize_ingredient(n) for n in names if n]
    if not normalized:
        return ingredients

    alias_map = {
        a.alias: a.ingredient
        for a in IngredientAlias.query.filter(IngredientAlias.alias.in_(normalized)).all()
    }
    name_map = {
        i.name: i
        for i in Ingredient.query.filter(Ingredient.name.in_(normalized)).all()
    }

    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    pantry_by_key = {}
    if pantry_ids:
        for ing in Ingredient.query.filter(Ingredient.id.in_(pantry_ids)).all():
            pantry_by_key.setdefault(_variant_key(ing.name), ing)

    for row in ingredients:
        name = row.get('name') or ''
        match = _match_existing(name, alias_map, name_map)

        row['id'] = match.id if match else None
        row['in_pantry'] = bool(match and match.id in pantry_ids)
        row['variant_of'] = None

        if row['in_pantry']:
            row['pantry_hint'] = 'in_pantry'
            continue

        twin = pantry_by_key.get(_variant_key(name))
        if twin and (not match or twin.id != match.id):
            row['variant_of'] = {'id': twin.id, 'name': twin.display}
            row['pantry_hint'] = 'variant'
            continue

        category = row.get('category') or ''
        is_fresh = bool(_VERS_RE.search(_normalize_ingredient(name.lower())))
        if category in KAST_CATEGORIES and not is_fresh and _is_dose(row.get('unit'), row.get('amount')):
            row['pantry_hint'] = 'suggest'
        else:
            row['pantry_hint'] = None

    return ingredients


def pantry_hints_for(ingredients):
    """Voorraadhint per bestaand ingredient, afgeleid uit het gebruik in recepten.

    Bij een geimporteerde regel zegt de regel zelf of het een dosis is. Bij typen
    bestaat die regel nog niet, dus kijken we naar hoe het ingredient tot nu toe
    gebruikt is: altijd een dosis, nooit een hele verpakking -> kastartikel.

    Geeft {ingredient_id: 'in_pantry' | 'suggest' | None}.
    """
    if not ingredients:
        return {}

    ids = [i.id for i in ingredients]
    pantry_ids = {
        p.ingredient_id for p in
        PantryIngredient.query.filter(PantryIngredient.ingredient_id.in_(ids)).all()
    }

    uses = {}
    for ri in RecipeIngredient.query.filter(RecipeIngredient.ingredient_id.in_(ids)).all():
        uses.setdefault(ri.ingredient_id, []).append((ri.unit, ri.amount))

    hints = {}
    for ing in ingredients:
        if ing.id in pantry_ids:
            hints[ing.id] = 'in_pantry'
            continue
        rows = uses.get(ing.id)
        is_fresh = bool(_VERS_RE.search(_normalize_ingredient((ing.name or '').lower())))
        if (rows and ing.category in KAST_CATEGORIES and not is_fresh
                and all(_is_dose(u, a) for u, a in rows)):
            hints[ing.id] = 'suggest'
        else:
            hints[ing.id] = None
    return hints


def hints_for_recipe_rows(recipe_ingredients):
    """Voorraadhint + naamvariant per bestaande receptregel.

    Dezelfde vier standen als bij een import, maar dan voor rijen die al in
    de database staan. De regel kent hier zijn eigen hoeveelheid en eenheid,
    dus die wegen mee in plaats van het gemiddelde gebruik.

    Geeft {recipe_ingredient_id: {'hint': ..., 'variant_of': {...}|None}}.
    """
    if not recipe_ingredients:
        return {}

    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    pantry_by_key = {}
    if pantry_ids:
        for ing in Ingredient.query.filter(Ingredient.id.in_(pantry_ids)).all():
            pantry_by_key.setdefault(_variant_key(ing.name), ing)

    out = {}
    for ri in recipe_ingredients:
        ing = ri.ingredient
        if ing.id in pantry_ids:
            out[ri.id] = {'hint': 'in_pantry', 'variant_of': None}
            continue

        twin = pantry_by_key.get(_variant_key(ing.name))
        if twin and twin.id != ing.id:
            out[ri.id] = {'hint': 'variant',
                          'variant_of': {'id': twin.id, 'name': twin.display}}
            continue

        is_fresh = bool(_VERS_RE.search(_normalize_ingredient((ing.name or '').lower())))
        if (ing.category in KAST_CATEGORIES and not is_fresh
                and _is_dose(ri.unit, ri.amount)):
            out[ri.id] = {'hint': 'suggest', 'variant_of': None}
        else:
            out[ri.id] = {'hint': None, 'variant_of': None}
    return out
