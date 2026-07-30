"""Localisation for the app's user interface.

Design note — there are two languages in play here and they must not be confused:

  * the **interface** language, which is what this module switches, and
  * the **domain** language, which is always Dutch and must stay that way.

Ingredient names, the category keys in constants.py, and unit tokens ('el',
'tl', 'stuks') are matched against Albert Heijn's catalogue and stored in the
database. Translating those would break product search and categorisation, so
they are never touched. What this module does is render Dutch domain values
with a localised *label* while keeping the underlying value Dutch.

Message ids are English, so an untranslated string falls back to English and
the Dutch catalogue is what carries the original wording.
"""
from flask import g, has_request_context, request, session
from flask_babel import Babel
from flask_babel import gettext, lazy_gettext as _l

# Interface languages, code -> name shown in the language picker.
LANGUAGES = {
    'en': 'English',
    'nl': 'Nederlands',
}
DEFAULT_LANGUAGE = 'en'

# Dutch category key -> localisable label. The keys are the values stored in
# the database and returned by Gemini; only the label is translated. The Dutch
# catalogue maps each of these back to the original Dutch wording, so nl users
# see exactly what they saw before.
CATEGORY_LABELS = {
    'Groente, Fruit & Aardappelen':         _l('Fruit, Veg & Potatoes'),
    'Vlees & Gevogelte':                    _l('Meat & Poultry'),
    'Vis & Schaaldieren':                   _l('Fish & Seafood'),
    'Vegetarisch & Plantaardig':            _l('Vegetarian & Plant-Based'),
    'Zuivel, Plantaardige Zuivel & Eieren': _l('Dairy, Plant-Based & Eggs'),
    'Kaas & Vleeswaren':                    _l('Cheese & Deli'),
    'Kruiden & Specerijen':                 _l('Herbs & Spices'),
    'Oliën, Sauzen & Smaakmakers':          _l('Oils, Sauces & Condiments'),
    'Pasta, Rijst & Granen':                _l('Pasta, Rice & Grains'),
    'Conserven & Peulvruchten':             _l('Tinned Goods & Pulses'),
    'Noten, Zaden & Gedroogd Fruit':        _l('Nuts, Seeds & Dried Fruit'),
    'Brood & Bakkerij':                     _l('Bread & Bakery'),
    'Ontbijt, Bakken & Desserts':           _l('Breakfast, Baking & Desserts'),
    'Diepvries':                            _l('Frozen'),
    'Dranken':                              _l('Drinks'),
    'Snacks & Zoetwaren':                   _l('Snacks & Confectionery'),
    'Non-Food & Huishouden':                _l('Non-Food & Household'),
    'Overig':                               _l('Other'),
}

# Dutch unit token -> localisable abbreviation. Same rule: the stored value
# stays Dutch because services/units.py and the AH package-size maths depend
# on it; only the rendering changes.
UNIT_LABELS = {
    'stuks':   _l('pcs'),
    'stuk':    _l('pc'),
    'el':      _l('tbsp'),
    'tl':      _l('tsp'),
    'snee':    _l('slice'),
    'sneetjes': _l('slices'),
    'teen':    _l('clove'),
    'tenen':   _l('cloves'),
    'bosje':   _l('bunch'),
    'blikje':  _l('tin'),
    'blik':    _l('tin'),
    'pak':     _l('pack'),
    'zak':     _l('bag'),
    'pot':     _l('jar'),
    'fles':    _l('bottle'),
    'snuf':    _l('pinch'),
    'scheutje': _l('splash'),
    'handje':  _l('handful'),
}

WEEKDAYS = [
    _l('Monday'), _l('Tuesday'), _l('Wednesday'), _l('Thursday'),
    _l('Friday'), _l('Saturday'), _l('Sunday'),
]


def category_label(value):
    """Render a Dutch category key in the interface language."""
    if not value:
        return ''
    label = CATEGORY_LABELS.get(value)
    return str(label) if label is not None else value


def unit_label(value):
    """Render a Dutch unit token in the interface language."""
    if not value:
        return ''
    label = UNIT_LABELS.get(str(value).strip().lower())
    return str(label) if label is not None else value


def get_locale():
    """Resolve the interface language for this request.

    Order: explicit ?lang= override, then the session, then the stored
    preference in Settings, then the browser's Accept-Language, then English.
    """
    if not has_request_context():
        return DEFAULT_LANGUAGE

    requested = request.args.get('lang')
    if requested in LANGUAGES:
        session['lang'] = requested
        return requested

    if session.get('lang') in LANGUAGES:
        return session['lang']

    # Stored preference. Guarded because this runs for every request including
    # ones raised before the database is usable.
    if 'app_language' not in g:
        stored = None
        try:
            from weekmenu.models import Settings
            row = Settings.query.filter_by(key='language').first()
            if row and row.value in LANGUAGES:
                stored = row.value
        except Exception:
            stored = None
        g.app_language = stored
    if g.app_language:
        return g.app_language

    return request.accept_languages.best_match(list(LANGUAGES)) or DEFAULT_LANGUAGE


def set_stored_language(code):
    """Persist the interface language and apply it to the current session."""
    if code not in LANGUAGES:
        return False
    from weekmenu.extensions import db
    from weekmenu.models import Settings
    row = Settings.query.filter_by(key='language').first()
    if row:
        row.value = code
    else:
        db.session.add(Settings(key='language', value=code))
    db.session.commit()
    session['lang'] = code
    g.app_language = code
    return True


def init_app(app):
    babel = Babel(app, locale_selector=get_locale)
    app.jinja_env.filters['category_label'] = category_label
    app.jinja_env.filters['unit_label'] = unit_label
    app.jinja_env.globals.update(
        get_locale=get_locale,
        LANGUAGES=LANGUAGES,
        WEEKDAYS=WEEKDAYS,
    )
    return babel


__all__ = [
    'gettext', '_l', 'LANGUAGES', 'DEFAULT_LANGUAGE', 'WEEKDAYS',
    'category_label', 'unit_label', 'get_locale', 'set_stored_language', 'init_app',
]
