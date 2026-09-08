from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from weekmenu.extensions import db
from weekmenu.services.units import _parse_product_size, _guess_ingredient_category


def _migrate_v1(conn):
    """Alle historische migraties, geconsolideerd. Idempotent via PRAGMA-checks."""
    recipe_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe)')).fetchall()]
    for col, col_def in [('url', 'TEXT'), ('instructions', 'TEXT'), ('serves', 'INTEGER')]:
        if col not in recipe_cols:
            try:
                conn.execute(text(f'ALTER TABLE recipe ADD COLUMN {col} {col_def}'))
            except OperationalError:
                pass

    menu_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(menu_item)')).fetchall()]
    if 'people_count' not in menu_cols:
        try:
            conn.execute(text('ALTER TABLE menu_item ADD COLUMN people_count INTEGER'))
        except OperationalError:
            pass
    if 'skip_shopping_list' not in menu_cols:
        try:
            conn.execute(text('ALTER TABLE menu_item ADD COLUMN skip_shopping_list BOOLEAN NOT NULL DEFAULT 0'))
        except OperationalError:
            pass

    cookbook_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(cookbook)')).fetchall()]
    if 'is_archived' not in cookbook_cols:
        try:
            conn.execute(text('ALTER TABLE cookbook ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0'))
        except OperationalError:
            pass

    ingredient_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(ingredient)')).fetchall()]
    for col, col_def in [
        ('ah_product_id', 'INTEGER'),
        ('ah_product_name', 'VARCHAR(200)'),
        ('ah_product_size', 'VARCHAR(50)'),
        ('ah_product_price', 'VARCHAR(20)'),
        ('ah_product_image', 'VARCHAR(500)'),
        ('ah_product_bonus', 'BOOLEAN DEFAULT 0'),
        ('ah_product_updated', 'INTEGER'),
        ('ah_product_color', 'VARCHAR(20)'),
        ('display_name', "VARCHAR(100) NOT NULL DEFAULT ''"),
        ('preparation', 'VARCHAR(100)'),
        ('ah_pkg_qty', 'REAL'),
        ('ah_pkg_unit', 'VARCHAR(20)'),
        ('ah_conv_factor', 'REAL'),
        ('ah_conv_unit', 'VARCHAR(20)'),
    ]:
        if col not in ingredient_cols:
            try:
                conn.execute(text(f'ALTER TABLE ingredient ADD COLUMN {col} {col_def}'))
            except OperationalError:
                pass

    ri_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe_ingredient)')).fetchall()]
    if 'preparation' not in ri_cols:
        try:
            conn.execute(text('ALTER TABLE recipe_ingredient ADD COLUMN preparation VARCHAR(100)'))
        except OperationalError:
            pass

    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS ingredient_alias (
            id INTEGER PRIMARY KEY,
            alias VARCHAR(100) NOT NULL UNIQUE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id)
        )
    '''))

    conn.execute(text("""
        UPDATE ingredient SET display_name = name
        WHERE display_name = '' OR display_name IS NULL
    """))

    unparsed = conn.execute(text("""
        SELECT id, ah_product_size FROM ingredient
        WHERE ah_product_size IS NOT NULL AND ah_product_size != ''
          AND ah_pkg_qty IS NULL
    """)).fetchall()
    for ing_id, size_str in unparsed:
        parsed = _parse_product_size(size_str)
        if parsed:
            conn.execute(
                text('UPDATE ingredient SET ah_pkg_qty = :qty, ah_pkg_unit = :unit WHERE id = :id'),
                {'qty': parsed[0], 'unit': parsed[1], 'id': ing_id}
            )

    overig_ingredients = conn.execute(
        text("SELECT id, name FROM ingredient WHERE category = 'Overig' OR category IS NULL")
    ).fetchall()
    for ing_id, ing_name in overig_ingredients:
        new_cat = _guess_ingredient_category(ing_name)
        if new_cat != 'Overig':
            conn.execute(
                text('UPDATE ingredient SET category = :cat WHERE id = :id'),
                {'cat': new_cat, 'id': ing_id}
            )

    conn.execute(text('DELETE FROM shopping_list_override'))

    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS shopping_list_exclusion (
            id INTEGER PRIMARY KEY,
            year INTEGER NOT NULL,
            week_number INTEGER NOT NULL,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id),
            UNIQUE(year, week_number, ingredient_id)
        )
    '''))


def _migrate_v2(conn):
    """Ingrediënt unit-normalisatie: preferred_unit kolom + conversietabel."""
    ing_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(ingredient)')).fetchall()]
    if 'preferred_unit' not in ing_cols:
        conn.execute(text('ALTER TABLE ingredient ADD COLUMN preferred_unit VARCHAR(20)'))

    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS ingredient_unit_conversion (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id),
            from_unit VARCHAR(20) NOT NULL,
            to_unit VARCHAR(20) NOT NULL,
            factor REAL NOT NULL,
            UNIQUE(ingredient_id, from_unit)
        )
    '''))


def _migrate_v3(conn):
    """unit_type + display_unit kolommen, confidence/reasoning op conversietabel."""
    ing_cols = [row[1] for row in conn.execute(
        text('PRAGMA table_info(ingredient)')).fetchall()]
    for col, col_def in [
        ('unit_type',    'VARCHAR(20)'),
        ('display_unit', 'VARCHAR(20)'),
    ]:
        if col not in ing_cols:
            conn.execute(text(f'ALTER TABLE ingredient ADD COLUMN {col} {col_def}'))

    conv_cols = [row[1] for row in conn.execute(
        text('PRAGMA table_info(ingredient_unit_conversion)')).fetchall()]
    for col, col_def in [
        ('confidence', 'REAL'),
        ('reasoning',  'TEXT'),
    ]:
        if col not in conv_cols:
            conn.execute(text(
                f'ALTER TABLE ingredient_unit_conversion ADD COLUMN {col} {col_def}'))


def _migrate_v4(conn):
    """Migratie naar app-native categorieën (Source of Truth)."""
    CATEGORY_MAP = {
        'Groente & Aardappelen':       'Groente, Fruit & Aardappelen',
        'Fruit':                       'Groente, Fruit & Aardappelen',
        'Vlees':                       'Vlees & Gevogelte',
        'Vis':                         'Vis & Schaaldieren',
        'Vegetarisch & Vegan':         'Vegetarisch & Plantaardig',
        'Vleeswaren':                  'Kaas & Vleeswaren',
        'Kaas':                        'Kaas & Vleeswaren',
        'Zuivel & Eieren':             'Zuivel, Plantaardige Zuivel & Eieren',
        'Bakkerij':                    'Brood & Bakkerij',
        'Pasta, Rijst & Wereldkeuken': 'Pasta, Rijst & Granen',
        'Blikken & Potten':            'Conserven & Peulvruchten',
        'Bakken':                      'Ontbijt, Bakken & Desserts',
        'Ontbijt & Beleg':             'Ontbijt, Bakken & Desserts',
        'Koek, Snoep & Chocolade':     'Snacks & Zoetwaren',
        'Koffie & Thee':               'Dranken',
        'Frisdrank & Water':           'Dranken',
        'Bier, Wijn & Aperitieven':    'Dranken',
        'Diepvries':                   'Diepvries',
        'Overig':                      'Overig',
    }
    SPLIT_CATEGORIES = {'Soepen, Sauzen & Kruiden', 'Snacks & Noten'}

    rows = conn.execute(text('SELECT id, name, category FROM ingredient')).fetchall()
    for ing_id, ing_name, old_cat in rows:
        if old_cat in SPLIT_CATEGORIES:
            new_cat = _guess_ingredient_category(ing_name)
        else:
            new_cat = CATEGORY_MAP.get(old_cat, _guess_ingredient_category(ing_name))
        conn.execute(
            text('UPDATE ingredient SET category = :cat WHERE id = :id'),
            {'cat': new_cat, 'id': ing_id}
        )


def _migrate_v5(conn):
    """Pantry-ingrediënten tabel voor Ecobooster."""
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS pantry_ingredient (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL UNIQUE REFERENCES ingredient(id)
        )
    '''))


def _migrate_v6(conn):
    """Extra AH-productvelden: was-prijs, bonusmechanisme, merk, AH-categorie."""
    ing_cols = [row[1] for row in conn.execute(
        text('PRAGMA table_info(ingredient)')).fetchall()]
    for col, col_def in [
        ('ah_product_was_price',       'VARCHAR(20)'),
        ('ah_product_bonus_mechanism', 'VARCHAR(100)'),
        ('ah_product_brand',           'VARCHAR(100)'),
        ('ah_product_category',        'VARCHAR(100)'),
    ]:
        if col not in ing_cols:
            conn.execute(text(f'ALTER TABLE ingredient ADD COLUMN {col} {col_def}'))


def _migrate_v7(conn):
    """Crop-functie: original_image_path op recipe_draft."""
    cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe_draft)')).fetchall()]
    if 'original_image_path' not in cols:
        try:
            conn.execute(text('ALTER TABLE recipe_draft ADD COLUMN original_image_path VARCHAR(200)'))
        except OperationalError:
            pass


def _migrate_v8(conn):
    """Crop in receptformulier: original_image_path op recipe."""
    cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe)')).fetchall()]
    if 'original_image_path' not in cols:
        try:
            conn.execute(text('ALTER TABLE recipe ADD COLUMN original_image_path VARCHAR(200)'))
        except OperationalError:
            pass


def _migrate_v9(conn):
    """Maaltijdtype-tags per recept (ontbijt/lunch/diner/tussendoor)."""
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS recipe_meal_type (
            id INTEGER PRIMARY KEY,
            recipe_id INTEGER NOT NULL REFERENCES recipe(id),
            meal_type VARCHAR(20) NOT NULL,
            UNIQUE(recipe_id, meal_type)
        )
    '''))


def _migrate_v10(conn):
    """Universele schapindeling: v4-samenvoegingen teruggedraaid.

    Groente/Fruit, Kaas/Vleeswaren en Ontbijt&Beleg/Bakken zijn weer gesplitst,
    'Verse Kruiden' is nieuw. Alleen rijen in gesplitste of hernoemde categorieën
    worden aangeraakt; de guesser mag daarbij uitsluitend binnen de doelen van
    die splitsing kiezen, zodat bewuste keuzes elders intact blijven.
    """
    RENAMES = {
        'Soepen, Sauzen & Kruiden': 'Oliën, Sauzen & Smaakmakers',
    }
    # bron -> (default, toegestane doelen voor de guesser). De doelen zijn
    # per bron begrensd zodat bewuste keuzes buiten de splitsing intact
    # blijven, maar ruim genoeg om oude gokfouten binnen de bron te herstellen
    # (pita bij de groente, eiernoedels bij de zuivel, manchego bij de zuivel).
    GF = {'Groente & Aardappelen', 'Fruit', 'Verse Kruiden', 'Brood & Bakkerij',
          'Conserven & Peulvruchten', 'Diepvries', 'Oliën, Sauzen & Smaakmakers'}
    SPLITS = {
        'Groente, Fruit & Aardappelen': ('Groente & Aardappelen', GF),
        'Groente & Aardappelen':        ('Groente & Aardappelen', GF),   # wees uit v4
        'Kaas & Vleeswaren': ('Kaas',
            {'Kaas', 'Vleeswaren', 'Vlees & Gevogelte', 'Ontbijt & Beleg'}),
        'Zuivel, Plantaardige Zuivel & Eieren': ('Zuivel & Eieren',
            {'Zuivel & Eieren', 'Kaas', 'Pasta, Rijst & Granen'}),
        'Ontbijt, Bakken & Desserts': ('Bakken & Desserts',
            {'Ontbijt & Beleg', 'Bakken & Desserts', 'Groente & Aardappelen'}),
        'Kruiden & Specerijen': ('Kruiden & Specerijen',
            {'Kruiden & Specerijen', 'Verse Kruiden', 'Groente & Aardappelen'}),
    }

    # De guesser draait op het HUIDIGE vocabulaire, dat na v12 andere namen
    # heeft. Een doel is dus ook geldig onder zijn latere naam, anders valt
    # een verse database hier terug op de default.
    LATER = {
        'Groente & Aardappelen':         'Groente, Fruit & Aardappelen',
        'Fruit':                         'Groente, Fruit & Aardappelen',
        'Verse Kruiden':                 'Groente, Fruit & Aardappelen',
        'Kaas':                          'Kaas & Vleeswaren',
        'Vleeswaren':                    'Kaas & Vleeswaren',
        'Vlees & Gevogelte':             'Vlees & Vis',
        'Vis & Schaaldieren':            'Vlees & Vis',
        'Noten, Zaden & Gedroogd Fruit': 'Noten & Snacks',
        'Snacks & Zoetwaren':            'Noten & Snacks',
        'Pasta, Rijst & Granen':         'Pasta, Rijst & Wereldkeuken',
    }
    SPLITS = {src: (default, allowed | {LATER[a] for a in allowed if a in LATER})
              for src, (default, allowed) in SPLITS.items()}

    rows = conn.execute(text('SELECT id, name, category FROM ingredient')).fetchall()
    for ing_id, ing_name, old_cat in rows:
        if old_cat in RENAMES:
            new_cat = RENAMES[old_cat]
        elif old_cat in SPLITS:
            default, allowed = SPLITS[old_cat]
            guess = _guess_ingredient_category(ing_name)
            new_cat = guess if guess in allowed else default
        else:
            continue
        if new_cat != old_cat:
            conn.execute(
                text('UPDATE ingredient SET category = :cat WHERE id = :id'),
                {'cat': new_cat, 'id': ing_id}
            )


# Een migratie moet toetsen tegen het vocabulaire van HAAR EIGEN tijdperk.
# Tegen het levende PRODUCT_CATEGORIES toetsen laat v11 alle v10-tussennamen
# ongeldig verklaren en opnieuw raden, waarmee v12 zijn deterministische map
# nooit meer te zien krijgt.
_V11_CATEGORIES = frozenset({
    'Groente & Aardappelen', 'Fruit', 'Verse Kruiden', 'Vlees & Gevogelte',
    'Vis & Schaaldieren', 'Vegetarisch & Plantaardig', 'Vleeswaren', 'Kaas',
    'Zuivel & Eieren', 'Brood & Bakkerij', 'Ontbijt & Beleg', 'Bakken & Desserts',
    'Kruiden & Specerijen', 'Oliën, Sauzen & Smaakmakers', 'Pasta, Rijst & Granen',
    'Conserven & Peulvruchten', 'Noten, Zaden & Gedroogd Fruit',
    'Snacks & Zoetwaren', 'Dranken', 'Diepvries', 'Non-Food & Huishouden', 'Overig',
})

_V12_CATEGORIES = frozenset({
    'Groente, Fruit & Aardappelen', 'Brood & Bakkerij', 'Kaas & Vleeswaren',
    'Vlees & Vis', 'Zuivel & Eieren', 'Vegetarisch & Plantaardig', 'Diepvries',
    'Pasta, Rijst & Wereldkeuken', 'Conserven & Peulvruchten',
    'Oliën, Sauzen & Smaakmakers', 'Kruiden & Specerijen', 'Bakken & Desserts',
    'Ontbijt & Beleg', 'Noten & Snacks', 'Dranken', 'Non-Food & Huishouden', 'Overig',
})


def _migrate_v11(conn):
    """Restanten van de oude taxonomie opruimen.

    Twee bronnen lekten na v10 nog oude categorienamen binnen: de
    '(verouderd)'-optie in de receptdropdown, en de ingredients_json van
    drafts die voor de migratie zijn ingelezen. De guesser draait hier
    lokaal, dus dit kost geen enkele Gemini-aanroep.
    """
    import json

    valid = _V11_CATEGORIES

    rows = conn.execute(text('SELECT id, name, category FROM ingredient')).fetchall()
    for ing_id, ing_name, cat in rows:
        if cat not in valid:
            conn.execute(
                text('UPDATE ingredient SET category = :c WHERE id = :i'),
                {'c': _guess_ingredient_category(ing_name), 'i': ing_id})

    drafts = conn.execute(text(
        "SELECT id, ingredients_json FROM recipe_draft WHERE status = 'pending'"
    )).fetchall()
    for draft_id, raw in drafts:
        try:
            items = json.loads(raw or '[]')
        except (ValueError, TypeError):
            continue
        changed = False
        for item in items:
            if item.get('category') not in valid:
                item['category'] = _guess_ingredient_category(item.get('name') or '')
                changed = True
        if changed:
            conn.execute(
                text('UPDATE recipe_draft SET ingredients_json = :j WHERE id = :i'),
                {'j': json.dumps(items, ensure_ascii=False), 'i': draft_id})


def _migrate_v12(conn):
    """Vier samenvoegingen, puur op naam — geen gokwerk.

    Gemeten over 16 echte weeklijsten waren Fruit, Verse Kruiden, Vis, Kaas,
    Vleeswaren en Noten stuk voor stuk kopjes met gemiddeld een of twee regels,
    terwijl je er in de winkel op dezelfde plek staat. Deze map is deterministisch:
    de guesser wordt niet aangeroepen, dus er kan niets onverwachts verschuiven.
    """
    import json

    MAP = {
        'Groente & Aardappelen':        'Groente, Fruit & Aardappelen',
        'Fruit':                        'Groente, Fruit & Aardappelen',
        'Verse Kruiden':                'Groente, Fruit & Aardappelen',
        'Kaas':                         'Kaas & Vleeswaren',
        'Vleeswaren':                   'Kaas & Vleeswaren',
        'Vlees & Gevogelte':            'Vlees & Vis',
        'Vis & Schaaldieren':           'Vlees & Vis',
        'Noten, Zaden & Gedroogd Fruit':'Noten & Snacks',
        'Snacks & Zoetwaren':           'Noten & Snacks',
        'Pasta, Rijst & Granen':        'Pasta, Rijst & Wereldkeuken',
    }

    for old_cat, new_cat in MAP.items():
        conn.execute(
            text('UPDATE ingredient SET category = :new WHERE category = :old'),
            {'new': new_cat, 'old': old_cat})

    # Wachtende drafts dragen hun categorie in JSON, dus die moeten mee.
    drafts = conn.execute(text(
        "SELECT id, ingredients_json FROM recipe_draft WHERE status = 'pending'"
    )).fetchall()
    for draft_id, raw in drafts:
        try:
            items = json.loads(raw or '[]')
        except (ValueError, TypeError):
            continue
        changed = False
        for item in items:
            if item.get('category') in MAP:
                item['category'] = MAP[item['category']]
                changed = True
        if changed:
            conn.execute(
                text('UPDATE recipe_draft SET ingredients_json = :j WHERE id = :i'),
                {'j': json.dumps(items, ensure_ascii=False), 'i': draft_id})

    # Alles wat na de samenvoeging nog buiten het vocabulaire valt, opnieuw raden.
    valid = _V12_CATEGORIES
    rows = conn.execute(text('SELECT id, name, category FROM ingredient')).fetchall()
    for ing_id, ing_name, cat in rows:
        if cat not in valid:
            conn.execute(
                text('UPDATE ingredient SET category = :c WHERE id = :i'),
                {'c': _guess_ingredient_category(ing_name), 'i': ing_id})


def _migrate_v13(conn):
    """Herkomst per ingredient: waar haal je het, als het niet de AH is."""
    cols = [r[1] for r in conn.execute(text('PRAGMA table_info(ingredient)'))]
    if 'bron' not in cols:
        conn.execute(text('ALTER TABLE ingredient ADD COLUMN bron VARCHAR(20)'))


def _migrate_v14(conn):
    """Spookingredienten opruimen die de parser met 'stuk(s)' heeft gemaakt.

    De parser liet de meervoudsstaart van de eenheid in de naam staan, zodat
    'stuk(s) tomaat' als apart ingredient naast 'tomaat' belandde. De regex is
    gerepareerd; deze migratie ruimt op wat er al stond.

    Behoudend: alleen samenvoegen als het schone doel al bestaat en de bron
    nergens anders aan hangt. Blijft er iets over, dan hernoemen we het zodat
    het tenminste leesbaar is en op /twijfelgevallen opvalt.
    """
    import re

    ghosts = conn.execute(text(
        "SELECT id, name FROM ingredient "
        "WHERE name LIKE '%(s) %' OR name LIKE '%(tjes) %' OR name LIKE '%(en) %'"
    )).fetchall()

    for ghost_id, ghost_name in ghosts:
        schoon = re.sub(r'^\w+\((?:s|tjes|en|je|jes)\)\s+', '', ghost_name).strip()
        if not schoon or schoon == ghost_name:
            continue

        doel = conn.execute(
            text('SELECT id FROM ingredient WHERE name = :n'), {'n': schoon}).fetchone()

        if doel:
            doel_id = doel[0]
            # Receptregels overzetten, daarna de dubbele rijen die daardoor
            # zouden ontstaan in de UNIQUE-tabellen eerst weghalen.
            conn.execute(text(
                'UPDATE recipe_ingredient SET ingredient_id = :d WHERE ingredient_id = :g'),
                {'d': doel_id, 'g': ghost_id})
            for tabel in ('pantry_ingredient', 'ingredient_alias',
                          'ingredient_unit_conversion', 'custom_shopping_ingredient',
                          'shopping_list_exclusion', 'shopping_list_override',
                          'shopping_check'):
                try:
                    conn.execute(
                        text(f'DELETE FROM {tabel} WHERE ingredient_id = :g'),
                        {'g': ghost_id})
                except Exception:
                    pass        # tabel bestaat niet in deze database
            conn.execute(text('DELETE FROM ingredient WHERE id = :g'), {'g': ghost_id})
        else:
            conn.execute(
                text('UPDATE ingredient SET name = :n, display_name = :d WHERE id = :g'),
                {'n': schoon, 'd': schoon, 'g': ghost_id})


def _migrate_v15(conn):
    """Een importbatch onthoudt hoeveel pagina's erin gingen en wat er misging.

    Zonder die twee velden eindigt een batch waarvan het model maar de helft
    teruggaf gewoon op 'klaar', met minder recepten dan pagina's en niets dat
    daarop wijst. Wie zestien pagina's aanlevert en elf kaarten terugkrijgt
    hoort dat te zien.
    """
    cols = [row[1] for row in conn.execute(text('PRAGMA table_info(dump_job)')).fetchall()]
    for col, col_def in [('page_count', 'INTEGER'), ('warning', 'TEXT')]:
        if col not in cols:
            try:
                conn.execute(text(f'ALTER TABLE dump_job ADD COLUMN {col} {col_def}'))
            except OperationalError:
                pass


def _migrate_v16(conn):
    """Receptkaart-modus en bereidingstijd.

    `dump_job.mode` zegt of een batch kookboekpagina's ('boek') of
    receptkaarten ('kaart', twee pagina's per recept) bevat; de vlag staat op
    de job omdat een retry in een achtergrondthread draait zonder request.
    `prep_time` wordt al jaren aan het model gevraagd maar bestond nergens.
    `back_image_path` is de achterkant van een kaart, alleen voor de
    nakijkkaart: daar staan de hoeveelheden die je wilt controleren.
    """
    for tabel, kolommen in [
        ('dump_job', [('mode', "VARCHAR(10) DEFAULT 'boek'")]),
        ('recipe', [('prep_time', 'INTEGER')]),
        ('recipe_draft', [('prep_time', 'INTEGER'), ('back_image_path', 'VARCHAR(200)')]),
    ]:
        cols = [row[1] for row in conn.execute(text(f'PRAGMA table_info({tabel})')).fetchall()]
        for col, col_def in kolommen:
            if col not in cols:
                try:
                    conn.execute(text(f'ALTER TABLE {tabel} ADD COLUMN {col} {col_def}'))
                except OperationalError:
                    pass


def _migrate_v17(conn):
    """Meldingen per concept.

    Wat over één recept gaat ('na de laatste stap stond nog ...', 'tabelrij
    ontbreekt') stond in één blok op de job; twaalf kaarten gaven een halve
    pagina tekst die niemand las. Het staat nu op het concept zelf.
    """
    cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe_draft)')).fetchall()]
    if 'meldingen_json' not in cols:
        try:
            conn.execute(text('ALTER TABLE recipe_draft ADD COLUMN meldingen_json TEXT'))
        except OperationalError:
            pass


def _migrate_v18(conn):
    """'Toch apart' vasthouden.

    De vraag 'Lijkt op X, die in je voorraad staat' kwam bij elke import terug,
    ook nadat je 'Toch apart' had gekozen: er was niets dat dat besluit
    bewaarde. Een alias naar jezelf werkt niet, want de vraag komt van de
    gelijkende voorraadnaam en niet van de eigen naam.

    Deze tabel voegt niets samen — samenvoegen blijft een klik op
    /twijfelgevallen. Hij onthoudt alleen waar je 'nee' hebt gezegd, zodat
    dezelfde vraag en hetzelfde voorstel niet blijven terugkomen.
    """
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS variant_apart (
            id INTEGER PRIMARY KEY,
            sleutel VARCHAR(100) NOT NULL,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id),
            UNIQUE(sleutel, ingredient_id)
        )
    '''))


def _migrate_v19(conn):
    """'Niet vragen' vasthouden bij de verpakkingsmaat.

    Het scherm op /ah-producten vraagt wat één stuk is zodra een telbare
    receptmaat tegenover een verpakking staat die weegt. Zonder deze tabel
    zou dezelfde vraag elke week terugkomen voor ingredienten waarvan je het
    antwoord niet weet. Hij verandert niets aan de berekening.
    """
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS maat_overslaan (
            id INTEGER PRIMARY KEY,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id),
            eenheid VARCHAR(20) NOT NULL,
            UNIQUE(ingredient_id, eenheid)
        )
    '''))


def migrate_db():
    with db.engine.connect() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                key VARCHAR(50) NOT NULL UNIQUE,
                value VARCHAR(200)
            )
        '''))

        row = conn.execute(
            text("SELECT value FROM settings WHERE key = 'schema_version'")
        ).fetchone()
        current = int(row[0]) if row else 0

        if current < 1:
            _migrate_v1(conn)
        if current < 2:
            _migrate_v2(conn)
        if current < 3:
            _migrate_v3(conn)
        if current < 4:
            _migrate_v4(conn)
        if current < 5:
            _migrate_v5(conn)
        if current < 6:
            _migrate_v6(conn)
        if current < 7:
            _migrate_v7(conn)
        if current < 8:
            _migrate_v8(conn)
        if current < 9:
            _migrate_v9(conn)
        if current < 10:
            _migrate_v10(conn)
        if current < 11:
            _migrate_v11(conn)
        if current < 12:
            _migrate_v12(conn)
        if current < 13:
            _migrate_v13(conn)
        if current < 14:
            _migrate_v14(conn)
        if current < 15:
            _migrate_v15(conn)
        if current < 16:
            _migrate_v16(conn)
        if current < 17:
            _migrate_v17(conn)
        if current < 18:
            _migrate_v18(conn)
        if current < 19:
            _migrate_v19(conn)

        target = 19
        if current < target:
            if row:
                conn.execute(
                    text("UPDATE settings SET value = :v WHERE key = 'schema_version'"),
                    {'v': str(target)}
                )
            else:
                conn.execute(
                    text("INSERT INTO settings (key, value) VALUES ('schema_version', :v)"),
                    {'v': str(target)}
                )

        conn.commit()
