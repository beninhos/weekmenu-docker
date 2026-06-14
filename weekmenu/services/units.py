import re
import math

from weekmenu.constants import (
    _UNIT_NORMALIZE, _UNIT_CONVERSIONS, _UNIT_BUY_ONE, _SIZE_UNIT_MAP,
    DUTCH_UNITS, _INGREDIENT_RE, _AMOUNT_ONLY_RE, _CATEGORY_KEYWORDS,
)
from weekmenu.extensions import db


def format_amount(amount):
    """Format numbers smart: integers without decimals, decimals when needed."""
    rounded = round(amount, 2)
    if rounded == int(rounded):
        return int(rounded)
    return f"{rounded:g}"


def _parse_product_size(size_str):
    """Parse AH product size string naar (qty, unit) tuple."""
    if not size_str or not size_str.strip():
        return None
    s = size_str.strip().lower()
    s = re.sub(r'^ca\.?\s*', '', s)

    if s in ('per stuk', 'per st', 'stuk'):
        return (1.0, 'stuks')
    if s in ('per bosje', 'per bos', 'bosje'):
        return (1.0, 'bosje')

    m = re.match(r'(\d+(?:[.,]\d+)?)\s*x\s*(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)', s)
    if m:
        count = float(m.group(1).replace(',', '.'))
        per   = float(m.group(2).replace(',', '.'))
        unit_raw = m.group(3).strip()
        unit = _SIZE_UNIT_MAP.get(unit_raw, unit_raw)
        return (count * per, unit)

    m = re.match(r'(\d+(?:[.,]\d+)?)\s*([a-zA-Z]+)', s)
    if m:
        qty = float(m.group(1).replace(',', '.'))
        unit_raw = m.group(2).strip()
        unit = _SIZE_UNIT_MAP.get(unit_raw, unit_raw)
        return (qty, unit)

    return None


def price_per_unit(price, size_str):
    """Prijs per genormaliseerde eenheid uit prijs (float) + AH-maat.

    Geeft (waarde, eenheid) met gewicht→kg en volume→l, of None als de
    maat niet te parsen valt. Stuk-achtige eenheden (stuks/plak/bosje…)
    blijven per-stuk en zijn dus niet 1-op-1 met kg/l te vergelijken.
    """
    if not price or price <= 0:
        return None
    parsed = _parse_product_size(size_str)
    if not parsed:
        return None
    qty, unit = parsed
    if qty <= 0:
        return None
    if unit == 'g':
        qty, unit = qty / 1000.0, 'kg'
    elif unit == 'ml':
        qty, unit = qty / 1000.0, 'l'
    elif unit == 'cl':
        qty, unit = qty / 100.0, 'l'
    elif unit == 'dl':
        qty, unit = qty / 10.0, 'l'
    return (price / qty, unit)


def _norm_unit(u):
    """Normaliseer unit string via _UNIT_NORMALIZE lookup."""
    return _UNIT_NORMALIZE.get((u or '').lower().strip(), (u or '').lower().strip())


def _normalize_ri_unit(ingredient, unit, amount):
    """Normaliseer unit + amount bij opslaan van RecipeIngredient/CustomShoppingIngredient."""
    from weekmenu.models import IngredientUnitConversion

    norm = _norm_unit(unit)

    if not ingredient.preferred_unit and norm:
        ingredient.preferred_unit = norm

    if not ingredient.preferred_unit or norm == ingredient.preferred_unit:
        return norm, amount

    conv = IngredientUnitConversion.query.filter_by(
        ingredient_id=ingredient.id, from_unit=norm
    ).first()
    if conv:
        return conv.to_unit, amount * conv.factor

    gfactor = _UNIT_CONVERSIONS.get((norm, ingredient.preferred_unit))
    if gfactor:
        return ingredient.preferred_unit, amount * gfactor

    return norm, amount


def _calc_multiplier(recipe_serves, people_count):
    """Bereken portie-multiplier."""
    if recipe_serves and people_count:
        try:
            return people_count / recipe_serves
        except ZeroDivisionError:
            return 1
    return 1


def _convert_unit_for_agg(ing_id, norm, amount, conversions, preferred_units):
    """Pas unit-conversie toe voor aggregatie (vangnet voor historische data)."""
    conv_key = (ing_id, norm)
    if conv_key in conversions:
        to_unit, factor = conversions[conv_key]
        return to_unit, amount * factor
    if ing_id in preferred_units:
        pref = preferred_units[ing_id]
        if norm != pref:
            gfactor = _UNIT_CONVERSIONS.get((norm, pref))
            if gfactor:
                return pref, amount * gfactor
    return norm, amount


def _calc_ah_qty(ing, amount, unit):
    """Bereken AH qty op basis van verpakkingsinhoud."""
    if not ing or not ing.ah_pkg_qty or not ing.ah_pkg_unit:
        return _calc_default_qty(amount, unit)

    pkg_qty = ing.ah_pkg_qty
    if pkg_qty <= 0:
        return _calc_default_qty(amount, unit)

    norm_recipe = _UNIT_NORMALIZE.get((unit or '').lower().strip(), (unit or '').lower().strip())
    norm_pkg    = _UNIT_NORMALIZE.get(ing.ah_pkg_unit.lower().strip(), ing.ah_pkg_unit.lower().strip())

    if ing.ah_conv_factor and ing.ah_conv_factor > 0 and ing.ah_conv_unit:
        norm_conv = _UNIT_NORMALIZE.get(ing.ah_conv_unit.lower().strip(), ing.ah_conv_unit.lower().strip())
        if norm_recipe == norm_conv:
            amount_in_pkg_unit = amount / ing.ah_conv_factor
            return max(1, math.ceil(amount_in_pkg_unit / pkg_qty))

    if norm_recipe == norm_pkg:
        return max(1, math.ceil(amount / pkg_qty))

    factor = _UNIT_CONVERSIONS.get((norm_recipe, norm_pkg))
    if factor:
        return max(1, math.ceil(amount * factor / pkg_qty))

    return _calc_default_qty(amount, unit)


def _calc_default_qty(amount, unit):
    """Bereken standaard AH-winkelwagenaantal."""
    norm = _UNIT_NORMALIZE.get((unit or '').lower().strip(), (unit or '').lower().strip())
    if norm in _UNIT_BUY_ONE:
        return 1
    qty = max(1, math.ceil(amount or 1))
    return 1 if qty > 20 else qty


def _parse_amount(amount_str):
    """Convert fraction strings like '1/2', '¼' to float."""
    if not amount_str:
        return None
    unicode_fractions = {'½': 0.5, '⅓': 1/3, '⅔': 2/3, '¼': 0.25, '¾': 0.75,
                         '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8, '⅙': 1/6,
                         '⅚': 5/6, '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875}
    s = str(amount_str).strip()
    for char, val in unicode_fractions.items():
        s = s.replace(char, str(val))
    mixed = re.match(r'^(\d+)[,. ](\d+/\d+)$', s)
    if mixed:
        whole = float(mixed.group(1))
        num, den = mixed.group(2).split('/')
        try:
            return whole + float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    if '/' in s:
        parts = s.split('/')
        try:
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return None
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_ingredient(s):
    """Lowercase + strip common Dutch/French diacritics to ASCII."""
    return (s.lower()
        .replace('ï', 'i').replace('ë', 'e').replace('é', 'e').replace('è', 'e')
        .replace('ü', 'u').replace('ö', 'o').replace('ä', 'a')
        .replace('â', 'a').replace('ê', 'e').replace('î', 'i')
        .replace('ô', 'o').replace('û', 'u').replace('à', 'a')
    )


def _guess_ingredient_category(name):
    """Guess supermarket category by keyword-matching ingredient name."""
    norm = _normalize_ingredient(name)
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            kw_n = _normalize_ingredient(kw)
            if len(kw_n) <= 3:
                if re.search(r'(^|[^a-z])' + re.escape(kw_n), norm):
                    return category
            else:
                if kw_n in norm:
                    return category
    return 'Overig'


def _parse_dutch_ingredient(raw):
    """Dutch-first regex ingredient parser: amount + unit + name."""
    s = raw.strip()
    m = _INGREDIENT_RE.match(s)
    if m:
        name = m.group(3).strip()
        return {
            'amount': _parse_amount(m.group(1)),
            'unit': DUTCH_UNITS.get(m.group(2).lower(), m.group(2).lower()),
            'name': name,
            'category': _guess_ingredient_category(name),
            'raw': raw,
        }
    m2 = _AMOUNT_ONLY_RE.match(s)
    if m2:
        name = m2.group(2).strip()
        return {
            'amount': _parse_amount(m2.group(1)),
            'unit': 'stuks',
            'name': name,
            'category': _guess_ingredient_category(name),
            'raw': raw,
        }
    try:
        from ingredient_parser import parse_ingredient
        parsed = parse_ingredient(raw)
        amount = None
        unit = ''
        if parsed.amount:
            first = parsed.amount[0]
            amount = _parse_amount(str(first.quantity)) if first.quantity else None
            raw_unit = str(first.unit).lower().strip() if first.unit else ''
            unit = DUTCH_UNITS.get(raw_unit, raw_unit)
        name = parsed.name.text if parsed.name else s
        if name and name != s:
            name = name.strip()
            return {'amount': amount, 'unit': unit or ('stuks' if amount is not None else ''), 'name': name, 'category': _guess_ingredient_category(name), 'raw': raw}
    except Exception:
        pass
    return {'amount': None, 'unit': '', 'name': s, 'category': _guess_ingredient_category(s), 'raw': raw}


def parse_ingredients_from_list(ingredient_strings):
    return [_parse_dutch_ingredient(raw) for raw in ingredient_strings if raw and raw.strip()]
