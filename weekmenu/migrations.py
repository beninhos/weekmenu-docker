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

        target = 5
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
