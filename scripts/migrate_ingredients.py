#!/usr/bin/env python3
"""
Ingredient normalization migration for weekmenu-planner.

Usage:
  python3 scripts/migrate_ingredients.py --dry-run          # Preview changes
  python3 scripts/migrate_ingredients.py --apply             # Apply changes
  python3 scripts/migrate_ingredients.py --apply --review review_map.json  # Apply with reviewed map

Read the analysis report first:
  python3 scripts/analyze_ingredients.py
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime

# ── Constants (from app.py) ──

DUTCH_UNITS = {
    'el': 'el', 'eetlepel': 'el', 'eetlepels': 'el',
    'tl': 'tl', 'theelepel': 'tl', 'theelepels': 'tl',
    'kl': 'kl', 'koffielepel': 'kl', 'koffielepels': 'kl',
    'dl': 'dl', 'deciliter': 'dl',
    'ml': 'ml', 'milliliter': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l',
    'g': 'g', 'gr': 'g', 'gram': 'g', 'grams': 'g',
    'kg': 'kg', 'kilogram': 'kg',
    'stuks': 'stuks', 'stuk': 'stuks',
    'snuf': 'snufje', 'snufje': 'snufje', 'snufjes': 'snufje',
    'scheutje': 'scheutje', 'scheut': 'scheutje',
    'teen': 'teen', 'tenen': 'teen',
    'blik': 'blik', 'blikje': 'blik',
    'pakje': 'pakje', 'pak': 'pakje', 'zakje': 'zakje',
    'bosje': 'bosje', 'bos': 'bosje',
    'plak': 'plak', 'plakken': 'plak',
    'bol': 'bol', 'bollen': 'bol',
    'takje': 'takje', 'takjes': 'takje',
    'blaadje': 'blaadje', 'blaadjes': 'blaadje',
    'cup': 'cup', 'cups': 'cup',
}

UNIT_PREFIXES = {
    'teen': 'teen', 'teentje': 'teen', 'teentjes': 'teen', 'tenen': 'teen',
    'stengel': 'stengel', 'stengels': 'stengel',
    'takje': 'takje', 'takjes': 'takje',
    'blaadje': 'blaadje', 'blaadjes': 'blaadje', 'bladeren': 'blaadje',
    'bosje': 'bosje', 'bos': 'bosje',
    'blik': 'blik', 'blikje': 'blik', 'blikjes': 'blik',
    'plak': 'plak', 'plakken': 'plak', 'plakje': 'plak', 'plakjes': 'plak',
    'snufje': 'snufje', 'snuf': 'snufje',
    'scheutje': 'scheutje', 'scheut': 'scheutje',
    'handvol': 'handvol',
    'pot': 'pot', 'potje': 'pot',
    'fles': 'fles',
    'pak': 'pakje', 'pakje': 'pakje',
    'zakje': 'zakje', 'zak': 'zakje',
    'stuk': 'stuks', 'stuks': 'stuks',
}

PREP_PREFIXES = {
    'geperste': 'geperst', 'geperst': 'geperst',
    'gesnipperde': 'gesnipperd', 'gesnipperd': 'gesnipperd',
    'gesneden': 'gesneden',
    'verse': 'vers', 'vers': 'vers',
    'gedroogd': 'gedroogd', 'gedroogde': 'gedroogd',
    'geroosterde': 'geroosterd', 'geroosterd': 'geroosterd',
    'fijngesneden': 'fijngesneden',
    'grof': 'grof', 'grove': 'grof',
    'fijne': 'fijn', 'fijn': 'fijn',
    'geraspte': 'geraspt', 'geraspt': 'geraspt',
    'gehakte': 'gehakt',
    'gebakken': 'gebakken',
    'gekookte': 'gekookt', 'gekookt': 'gekookt',
    'ingeblikt': 'ingeblikt', 'ingelegde': 'ingelegd',
}

IRREGULAR_PLURALS = {
    'tomaten': 'tomaat',
    'aardappelen': 'aardappel', 'aardappels': 'aardappel',
    'uien': 'ui',
    'eieren': 'ei',
    'augurken': 'augurk',
    'bananen': 'banaan',
    'wortels': 'wortel', 'wortelen': 'wortel',
    'winterpenen': 'winterpeen',
    'bosuitjes': 'bosui',
    'champignons': 'champignon',
    'citroenen': 'citroen',
    'courgettes': 'courgette',
    'sjalotten': 'sjalot',
    'olijven': 'olijf',
    'linzen': 'linze',
    'bonen': 'boon',
    'noten': 'noot',
    'garnalen': 'garnaal',
    'mosselen': 'mossel',
    'spruitjes': 'spruitje',
    'kersen': 'kers',
    'bolletjes': 'bolletje',
    'doperwten': 'doperwt',
    'sperziebonen': 'sperzieboon',
    'kippendijen': 'kippendij',
    'papadums': 'papadum',
    'uitjes': 'uitje',
}

# Known synonyms that can't be detected by simple rules
KNOWN_SYNONYMS = {
    'tomatenpuree': ['tomatenpurree'],
    'lente-ui': ['lente ui', 'lenteui'],
    'paprika': ['paparika'],
    'maizena': ['maïzena', 'maizena'],
}

_CATEGORY_KEYWORDS = [
    ('Groente & Aardappelen', ['vleestomaat', 'vleestomaten', 'bladspinazie', 'sperziebonen', 'sperzieboon', 'winterpeen', 'winterpenen', 'puntpaprika', 'bosui', 'bosuitje', 'bleekselderij', 'augurk']),
    ('Soepen, Sauzen & Kruiden', ['satésaus', 'sesamolie', 'ahornsiroop', 'boemboe', 'garam', 'massala', 'jus', 'saus']),
    ('Bakken', ['maizena', 'maïzena', 'zelfrijzend']),
    ('Bakkerij', ['volkoren bolletje', 'bolletje', 'papadum', 'chapati', 'wraps']),
    ('Vleeswaren', ['ontbijtspek', 'ontbijtspekje']),
    ('Kaas', ['burrata']),
    ('Pasta, Rijst & Wereldkeuken', ['basmatirijst', 'zilvervliesrijst', 'zilvervlies', 'conchiglie', 'bami goreng', 'nasi goreng', 'papadums']),
    ('Frisdrank & Water', ['bronwater', 'kraanwater']),
    ('Vlees', ['kipfilet', 'kippendij', 'kip', 'gehakt', 'varkensvlees', 'varken', 'rundvlees', 'rund', 'lamsrack', 'lam', 'biefstuk', 'tartaar', 'ossenhaas', 'entrecote', 'speklap', 'kalkoen', 'eend', 'konijn', 'wild', 'hert', 'klapstuk', 'riblap', 'cordon bleu', 'saté ajam', 'saté', 'vlees']),
    ('Vleeswaren', ['ham', 'salami', 'rookworst', 'cervelaat', 'leverworst', 'worst', 'chorizo', 'pancetta', 'prosciutto', 'spek', 'bacon', 'rookvlees', 'pastrami']),
    ('Vis', ['zalm', 'tonijn', 'vis', 'garnaal', 'mossel', 'inktvis', 'forel', 'haring', 'makreel', 'ansjovis', 'kabeljauw', 'tilapia', 'kreeft', 'krab', 'schol', 'sardine', 'zeebaars', 'dorade', 'paling', 'sint-jakobsschelp']),
    ('Vegetarisch & Vegan', ['tofu', 'tempeh', 'tahoe', 'seitan', 'quorn', 'soja', 'lupine']),
    ('Kaas', ['kaas', 'parmezaan', 'mozzarella', 'feta', 'ricotta', 'mascarpone', 'grana', 'pecorino', 'emmentaler', 'gorgonzola', 'brie', 'camembert', 'cheddar', 'gouda', 'edam', 'gruyère']),
    ('Zuivel & Eieren', ['slagroom', 'karnemelk', 'volle melk', 'melk', 'yoghurt', 'kwark', 'boter', 'margarine', 'crème fraîche', 'fromage frais', 'zure room', 'room', 'ei', 'quark']),
    ('Bakkerij', ['stokbrood', 'ciabatta', 'baguette', 'croissant', 'focaccia', 'brioche', 'tortilla', 'pitabrood', 'naan', 'brood']),
    ('Pasta, Rijst & Wereldkeuken', ['spaghetti', 'penne', 'rigatoni', 'fusilli', 'lasagne', 'tagliatelle', 'fettuccine', 'noodle', 'noedel', 'couscous', 'bulgur', 'quinoa', 'polenta', 'gnocchi', 'tortellini', 'ravioli', 'macaroni', 'pasta', 'rijst', 'risotto', 'mie', 'orzo']),
    ('Blikken & Potten', ['tomatenblokje', 'tomatenstukje', 'passata', 'kikkererwt', 'linzen', 'bruine bonen', 'witte bonen', 'kidneybonen', 'bonen', 'maïs', 'artisjok', 'olijf']),
    ('Soepen, Sauzen & Kruiden', ['tomatenpuree', 'olijfolie', 'zonnebloemolie', 'koolzaadolie', 'bouillon', 'fond', 'soep', 'ketchup', 'mosterd', 'mayonaise', 'sojasaus', 'worcester', 'tabasco', 'pesto', 'sambal', 'harissa', 'hoisin', 'misopasta', 'tahini', 'paprikapoeder', 'komijn', 'kaneel', 'kurkuma', 'oregano', 'laurier', 'honing', 'siroop', 'stroop', 'azijn', 'olie', 'zout', 'peper', 'nootmuskaat', 'kardemom', 'kruidnagel', 'steranijs', 'kerrie', 'curry', 'ras el hanout', 'five spice', "za'atar", 'sumak']),
    ('Bakken', ['bloem', 'zelfrijzend', 'bakpoeder', 'maizena', 'gist', 'baksoda', 'vanille', 'vanillesuiker', 'amandelpoeder', 'amandelmeel', 'suiker', 'poedersuiker', 'basterdsuiker', 'rietsuiker', 'cacaopoeder', 'cacao']),
    ('Koek, Snoep & Chocolade', ['chocolade', 'pure chocolade', 'melkchocolade', 'witte chocolade', 'koek', 'stroopwafel', 'biscuit', 'marshmallow']),
    ('Ontbijt & Beleg', ['jam', 'marmelade', 'pindakaas', 'notenpasta', 'hagelslag', 'vlokken', 'muesli', 'havermout', 'granola', 'cornflakes', 'honing op brood']),
    ('Snacks & Noten', ['amandel', 'walnoot', 'cashew', 'hazelnoot', 'pistache', 'pijnboompit', 'sesamzaad', 'lijnzaad', 'chiazaad', 'zonnebloempit', 'pompoenpit', 'rozijn', 'cranberry', 'sultana', 'gedroogd fruit', 'dadel', 'vijg', 'abrikoos', 'pinda']),
    ('Koffie & Thee', ['koffie', 'espresso', 'thee', 'groene thee', 'cacao poeder']),
    ('Bier, Wijn & Aperitieven', ['wijn', 'rode wijn', 'witte wijn', 'rosé', 'bier', 'cognac', 'rum', 'wodka', 'gin', 'whisky', 'port', 'marsala', 'sherry', 'champagne', 'prosecco', 'likeur', 'calvados', 'armagnac']),
    ('Frisdrank & Water', ['limonade', 'cola', 'spa', 'mineraalwater', 'appelsap', 'sinaasappelsap', 'tomatensap', 'kokosmelk', 'amandelmelk', 'havermelk', 'sojamelk', 'water']),
    ('Groente & Aardappelen', ['ui', 'rode ui', 'sjalot', 'knoflook', 'wortel', 'aardappel', 'zoete aardappel', 'bataat', 'prei', 'courgette', 'paprika', 'paparika', 'champignon', 'paddenstoel', 'shiitake', 'broccoli', 'bloemkool', 'romanesco', 'spinazie', 'komkommer', 'tomaat', 'tomaten', 'tomat', 'venkel', 'asperge', 'doperwt', 'erwt', 'biet', 'radijs', 'spruitje', 'kool', 'rode kool', 'witlof', 'paksoi', 'aubergine', 'chilipeper', 'gember', 'andijvie', 'sla', 'ijsbergsla', 'peterselie', 'basilicum', 'rozemarijn', 'tijm', 'bieslook', 'selderij', 'dragon', 'koriander', 'munt', 'salie', 'dille', 'mais', 'maïs', 'artisjok', 'palmhart', 'radicchio', 'rucola', 'rucolo', 'waterkers', 'knolselderij', 'pastinaak', 'rettich', 'raap', 'avocado', 'peen', 'groente']),
    ('Fruit', ['appel', 'peer', 'citroen', 'limoen', 'sinaasappel', 'mandarijn', 'grapefruit', 'banaan', 'banan', 'aardbei', 'framboos', 'blauwe bes', 'bosbes', 'braambes', 'kiwi', 'mango', 'ananas', 'papaja', 'passievrucht', 'granaatappel', 'pruim', 'kers', 'abrikoos', 'nectarine', 'vijg', 'meloen', 'watermeloen', 'lychee', 'kokos']),
    ('Diepvries', ['diepvries', 'ingevroren', 'bevroren']),
]


def _normalize_ingredient(s):
    return (s.lower()
        .replace('ï', 'i').replace('ë', 'e').replace('é', 'e').replace('è', 'e')
        .replace('ü', 'u').replace('ö', 'o').replace('ä', 'a')
        .replace('â', 'a').replace('ê', 'e').replace('î', 'i')
        .replace('ô', 'o').replace('û', 'u').replace('à', 'a')
    )


def _guess_ingredient_category(name):
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


def _singularize_word(word):
    """Singularize a single Dutch word."""
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    if len(word) <= 3:
        return word
    if word.endswith("'s") and len(word) > 3:
        return word[:-2]
    if word.endswith('tjes') and len(word) > 5:
        return word[:-1]
    if word.endswith('jes') and not word.endswith('tjes') and len(word) > 4:
        return word[:-1]
    # Don't strip -s from words ending in double vowel+s (vlees, kaas, raas)
    if word.endswith('s') and not word.endswith(('us', 'is', 'as', 'ss', 'ks', 'es')):
        # Only strip if the result doesn't end with a double vowel
        candidate = word[:-1]
        if len(candidate) > 2 and not re.search(r'[aeiou]{2}$', candidate):
            return candidate
    return word


def dutch_singularize(phrase):
    """Singularize a Dutch ingredient phrase. Applies to last word for compounds."""
    if phrase in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[phrase]
    words = phrase.split()
    if len(words) <= 1:
        return _singularize_word(phrase)
    # Singularize last word of compound
    words[-1] = _singularize_word(words[-1])
    return ' '.join(words)


# ── Name cleaning pipeline ──

def clean_ingredient_name(raw_name):
    """
    Clean an ingredient name and extract embedded metadata.
    Returns: {
        'canonical': str,       # lowercase, singular, no unit/prep
        'display_name': str,    # human-readable with proper casing
        'preparation': str|None,# extracted preparation
        'extracted_unit': str|None,  # unit that was embedded in name
        'old_name': str,        # original name for reference
    }
    """
    name = raw_name.strip()
    preparation = None
    extracted_unit = None
    original = name

    # 1. Handle leading parenthetical: "(mafaldine) pasta" -> "mafaldine pasta"
    leading_paren = re.match(r'^\(([^)]+)\)\s*(.+)$', name)
    if leading_paren:
        name = f"{leading_paren.group(1)} {leading_paren.group(2)}"

    # 2. Handle trailing parenthetical qualifiers
    trailing_paren = re.search(r'\s*\(([^)]+)\)\s*$', name)
    if trailing_paren:
        content = trailing_paren.group(1).strip().lower()
        # Preparation qualifiers
        if content in ('vers', 'gedroogd', 'grof', 'fijn', 'fijngehakt',
                       'gesnipperd', 'in ringen', 'gesneden'):
            preparation = content
            name = re.sub(r'\s*\([^)]+\)\s*$', '', name).strip()
        # Unit qualifiers
        elif content in ('stuk', 'stuks'):
            extracted_unit = 'stuks'
            name = re.sub(r'\s*\([^)]+\)\s*$', '', name).strip()
        # Clarification like "(wortel)" for bospeen -> keep as-is (it's the actual name)
        elif content == 'wortel':
            name = content  # "bospeen (wortel)" -> "wortel"
        # Descriptive like "(of riblappen)" -> keep original but note
        # Don't extract, it's context

    # 3. Comma-separated preparation: "ui, gesnipperd"
    if ',' in name:
        parts = name.split(',', 1)
        potential_prep = parts[1].strip().lower()
        prep_keywords = ['gesnipperd', 'gesneden', 'gehakt', 'geraspt', 'in blokjes',
                         'in ringen', 'in plakjes', 'fijngesneden', 'grof gehakt',
                         'klein gesneden', 'dun gesneden', 'geroosterd', 'vers',
                         'gedroogd', 'fijngehakt']
        if any(kw in potential_prep for kw in prep_keywords):
            name = parts[0].strip()
            preparation = potential_prep

    # 4. Unit prefix: "teentjes knoflook" -> unit=teen, name=knoflook
    words = name.split()
    if len(words) >= 2:
        first = words[0].lower()
        if first in UNIT_PREFIXES:
            extracted_unit = UNIT_PREFIXES[first]
            name = ' '.join(words[1:])
        elif first in PREP_PREFIXES:
            preparation = PREP_PREFIXES[first]
            name = ' '.join(words[1:])

    # 5. Qualifier suffixes
    qualifier_patterns = [
        (r'\s+naar smaak$', None),     # drop it entirely
        (r'\s+op sap$', 'op sap'),
        (r'\s+minder zout$', 'minder zout'),
        (r'\s+zonder bot$', 'zonder bot'),
        (r'\s+zonder vel$', 'zonder vel'),
    ]
    for pattern, prep_val in qualifier_patterns:
        if re.search(pattern, name, re.IGNORECASE):
            name = re.sub(pattern, '', name, flags=re.IGNORECASE).strip()
            if prep_val and not preparation:
                preparation = prep_val

    # 6. Normalize to canonical form
    canonical = _normalize_ingredient(name.strip())

    # 7. Singularize
    canonical = dutch_singularize(canonical)

    # 8. Strip trailing/leading whitespace
    canonical = canonical.strip()

    # 9. Build display name
    display_name = canonical.title()
    # Fix common Dutch casing issues
    display_name = re.sub(r'\bEn\b', 'en', display_name)
    display_name = re.sub(r'\bOp\b', 'op', display_name)
    display_name = re.sub(r'\bVan\b', 'van', display_name)
    display_name = re.sub(r'\bDe\b', 'de', display_name)
    display_name = re.sub(r'\bHet\b', 'het', display_name)

    return {
        'canonical': canonical,
        'display_name': display_name,
        'preparation': preparation,
        'extracted_unit': extracted_unit,
        'old_name': original,
    }


# ── Duplicate detection ──

def build_canonical_groups(ingredients):
    """Group ingredients by their canonical name. Returns {canonical: [ingredient_rows]}"""
    groups = defaultdict(list)
    for ing in ingredients:
        cleaned = clean_ingredient_name(ing['name'])
        groups[cleaned['canonical']].append({
            **dict(ing),
            'cleaned': cleaned,
        })

    # Also group by known synonyms
    synonym_map = {}  # alias -> canonical
    for canonical, aliases in KNOWN_SYNONYMS.items():
        canonical_norm = _normalize_ingredient(canonical)
        for alias in aliases:
            alias_norm = _normalize_ingredient(alias.lower().strip())
            synonym_map[alias_norm] = canonical_norm

    # Merge synonym groups
    merged = defaultdict(list)
    assigned = {}  # original canonical -> merged canonical
    for canonical, ings in groups.items():
        # Check if this canonical is a known synonym
        target = synonym_map.get(canonical, canonical)
        merged[target].extend(ings)
        assigned[canonical] = target

    return merged


def select_winner(group):
    """Select the best ingredient to keep from a duplicate group."""
    # Sort by: has AH product (desc), ri_count (desc), id (asc)
    sorted_group = sorted(group, key=lambda x: (
        -1 if x.get('ah_product_id') else 0,
        -(x.get('ri_count') or 0),
        x['id'],
    ))
    return sorted_group[0]


# ── Migration logic ──

def migrate_schema(conn):
    """Add new columns and tables if they don't exist."""
    # Check ingredient columns
    ing_cols = [row[1] for row in conn.execute('PRAGMA table_info(ingredient)').fetchall()]
    for col, col_def in [
        ('display_name', "VARCHAR(100) NOT NULL DEFAULT ''"),
        ('preparation', 'VARCHAR(100)'),
    ]:
        if col not in ing_cols:
            conn.execute(f'ALTER TABLE ingredient ADD COLUMN {col} {col_def}')
            print(f"  ALTER TABLE ingredient ADD COLUMN {col}")

    # Check recipe_ingredient columns
    ri_cols = [row[1] for row in conn.execute('PRAGMA table_info(recipe_ingredient)').fetchall()]
    if 'preparation' not in ri_cols:
        conn.execute('ALTER TABLE recipe_ingredient ADD COLUMN preparation VARCHAR(100)')
        print("  ALTER TABLE recipe_ingredient ADD COLUMN preparation")

    # Create ingredient_alias table
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ingredient_alias (
            id INTEGER PRIMARY KEY,
            alias VARCHAR(100) NOT NULL UNIQUE,
            ingredient_id INTEGER NOT NULL REFERENCES ingredient(id)
        )
    ''')
    print("  CREATE TABLE IF NOT EXISTS ingredient_alias")

    conn.commit()


def run_migration(db_path, dry_run=True, review_path=None):
    """Run the full migration."""

    # Load review map if provided
    review_map = None
    if review_path and os.path.exists(review_path):
        with open(review_path) as f:
            review_map = json.load(f)
        print(f"Loaded review map from {review_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # ── Phase 1: Schema ──
    print("\n=== PHASE 1: Schema Migration ===")
    if dry_run:
        print("  [DRY RUN] Would add columns: display_name, preparation")
        print("  [DRY RUN] Would create table: ingredient_alias")
    else:
        migrate_schema(conn)

    # ── Load data ──
    ingredients = conn.execute('''
        SELECT i.id, i.name, i.category,
               i.ah_product_id, i.ah_product_name, i.ah_product_size,
               i.ah_product_price, i.ah_product_image, i.ah_product_bonus,
               i.ah_product_updated, i.ah_product_color,
               COUNT(ri.id) as ri_count
        FROM ingredient i
        LEFT JOIN recipe_ingredient ri ON ri.ingredient_id = i.id
        GROUP BY i.id
    ''').fetchall()

    print(f"\nLoaded {len(ingredients)} ingredients")

    # ── Phase 2: Clean names ──
    print("\n=== PHASE 2: Name Cleaning ===")
    name_changes = []
    for ing in ingredients:
        cleaned = clean_ingredient_name(ing['name'])
        if cleaned['canonical'] != ing['name'] or cleaned['preparation'] or cleaned['extracted_unit']:
            name_changes.append({
                'id': ing['id'],
                'old_name': ing['name'],
                'new_canonical': cleaned['canonical'],
                'display_name': cleaned['display_name'],
                'preparation': cleaned['preparation'],
                'extracted_unit': cleaned['extracted_unit'],
            })

    for change in name_changes:
        parts = []
        parts.append(f"'{change['old_name']}' -> canonical='{change['new_canonical']}'")
        if change['preparation']:
            parts.append(f"prep='{change['preparation']}'")
        if change['extracted_unit']:
            parts.append(f"unit='{change['extracted_unit']}'")
        print(f"  id={change['id']:>3}  {', '.join(parts)}")

    print(f"\n  Total name changes: {len(name_changes)}")

    # ── Phase 3: Find and merge duplicates ──
    print("\n=== PHASE 3: Duplicate Merging ===")
    canonical_groups = build_canonical_groups(ingredients)

    # Separate auto-merge from needs-review
    auto_merges = []
    needs_review = []

    for canonical, group in canonical_groups.items():
        if len(group) <= 1:
            continue

        winner = select_winner(group)
        losers = [g for g in group if g['id'] != winner['id']]

        # Auto-merge: case-only duplicates or simple plural/diacritics
        names_lower = set(g['name'].lower().strip() for g in group)
        if len(names_lower) == 1:
            # Pure case duplicate
            auto_merges.append({
                'canonical': canonical,
                'winner_id': winner['id'],
                'winner_name': winner['name'],
                'loser_ids': [l['id'] for l in losers],
                'loser_names': [l['name'] for l in losers],
                'reason': 'case_duplicate',
            })
        else:
            # Check if it's a simple plural/diacritics difference
            canonicals = set(clean_ingredient_name(g['name'])['canonical'] for g in group)
            if len(canonicals) == 1:
                auto_merges.append({
                    'canonical': canonical,
                    'winner_id': winner['id'],
                    'winner_name': winner['name'],
                    'loser_ids': [l['id'] for l in losers],
                    'loser_names': [l['name'] for l in losers],
                    'reason': 'plural_or_variant',
                })
            else:
                needs_review.append({
                    'canonical': canonical,
                    'ids': [g['id'] for g in group],
                    'names': [g['name'] for g in group],
                    'suggestion': f"Merge to '{canonical}'? Winner would be id={winner['id']} ('{winner['name']}')",
                })

    # Apply review map overrides
    if review_map:
        if 'skip_merges' in review_map:
            skip_ids = set(tuple(sorted(s)) for s in review_map['skip_merges'])
            auto_merges = [m for m in auto_merges
                          if tuple(sorted([m['winner_id']] + m['loser_ids'])) not in skip_ids]
        if 'force_merges' in review_map:
            for fm in review_map['force_merges']:
                auto_merges.append({
                    'canonical': fm.get('canonical', ''),
                    'winner_id': fm['winner_id'],
                    'winner_name': fm.get('winner_name', ''),
                    'loser_ids': fm['loser_ids'],
                    'loser_names': fm.get('loser_names', []),
                    'reason': 'review_approved',
                })

    print(f"\n  Auto-merges: {len(auto_merges)}")
    for merge in auto_merges:
        print(f"    '{merge['canonical']}': keep id={merge['winner_id']} ('{merge['winner_name']}'), "
              f"merge {merge['loser_ids']} ({merge['loser_names']}) [{merge['reason']}]")

    print(f"\n  Needs review: {len(needs_review)}")
    for nr in needs_review:
        print(f"    '{nr['canonical']}': ids={nr['ids']}, names={nr['names']}")
        print(f"      -> {nr['suggestion']}")

    # Generate review_map.json
    review_output = {
        'auto_merge': auto_merges,
        'needs_review': needs_review,
    }
    review_file = os.path.join(os.path.dirname(db_path), 'review_map.json')
    if dry_run:
        review_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'review_map.json')
    with open(review_file, 'w') as f:
        json.dump(review_output, f, indent=2, ensure_ascii=False)
    print(f"\n  Review map saved to: {review_file}")

    if dry_run:
        # Show what aliases would be created
        print("\n=== PHASE 4: Alias Preview ===")
        alias_count = 0
        for canonical, group in canonical_groups.items():
            aliases = {canonical}
            for g in group:
                norm = _normalize_ingredient(g['name'].lower().strip())
                aliases.add(norm)
                singular = dutch_singularize(norm)
                aliases.add(singular)
            # Add known synonym aliases
            for syn_canonical, syn_aliases in KNOWN_SYNONYMS.items():
                if _normalize_ingredient(syn_canonical) == canonical:
                    for sa in syn_aliases:
                        aliases.add(_normalize_ingredient(sa))
            alias_count += len(aliases)
        print(f"  Would create ~{alias_count} aliases for {len(canonical_groups)} ingredients")

        print("\n=== DRY RUN COMPLETE ===")
        print("Run with --apply to execute these changes.")
        conn.close()
        return

    # ── Execute changes ──
    print("\n=== EXECUTING CHANGES ===")

    # Phase 3: Execute merges
    print("\n  Merging duplicates...")
    for merge in auto_merges:
        winner_id = merge['winner_id']
        for loser_id in merge['loser_ids']:
            # Move recipe_ingredient references
            conn.execute('UPDATE recipe_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                        (winner_id, loser_id))

            # Move custom_shopping_ingredient references
            conn.execute('UPDATE custom_shopping_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                        (winner_id, loser_id))

            # Move shopping_list_override references (handle unique constraint)
            conn.execute('UPDATE OR IGNORE shopping_list_override SET ingredient_id = ? WHERE ingredient_id = ?',
                        (winner_id, loser_id))
            conn.execute('DELETE FROM shopping_list_override WHERE ingredient_id = ?', (loser_id,))

            # Transfer AH product link if winner doesn't have one
            winner = conn.execute('SELECT ah_product_id FROM ingredient WHERE id = ?', (winner_id,)).fetchone()
            loser = conn.execute(
                'SELECT ah_product_id, ah_product_name, ah_product_size, ah_product_price, '
                'ah_product_image, ah_product_bonus, ah_product_updated, ah_product_color '
                'FROM ingredient WHERE id = ?', (loser_id,)
            ).fetchone()
            if not winner['ah_product_id'] and loser and loser['ah_product_id']:
                conn.execute(
                    'UPDATE ingredient SET '
                    'ah_product_id=?, ah_product_name=?, ah_product_size=?, '
                    'ah_product_price=?, ah_product_image=?, ah_product_bonus=?, '
                    'ah_product_updated=?, ah_product_color=? '
                    'WHERE id = ?',
                    (loser['ah_product_id'], loser['ah_product_name'], loser['ah_product_size'],
                     loser['ah_product_price'], loser['ah_product_image'], loser['ah_product_bonus'],
                     loser['ah_product_updated'], loser['ah_product_color'], winner_id)
                )
                print(f"    Transferred AH link from id={loser_id} to id={winner_id}")

            # Delete loser
            conn.execute('DELETE FROM ingredient WHERE id = ?', (loser_id,))
            print(f"    Merged id={loser_id} into id={winner_id}")

    conn.commit()

    # Check for duplicate (recipe_id, ingredient_id) pairs after merge
    dups = conn.execute('''
        SELECT recipe_id, ingredient_id, unit, COUNT(*) as cnt
        FROM recipe_ingredient
        GROUP BY recipe_id, ingredient_id, unit
        HAVING cnt > 1
    ''').fetchall()
    if dups:
        print(f"\n  WARNING: Found {len(dups)} duplicate (recipe, ingredient, unit) combos after merge!")
        for d in dups:
            # Sum amounts and keep one
            rows = conn.execute(
                'SELECT id, amount FROM recipe_ingredient '
                'WHERE recipe_id = ? AND ingredient_id = ? AND unit = ? '
                'ORDER BY id',
                (d['recipe_id'], d['ingredient_id'], d['unit'])
            ).fetchall()
            total = sum(r['amount'] for r in rows)
            keep_id = rows[0]['id']
            delete_ids = [r['id'] for r in rows[1:]]
            conn.execute('UPDATE recipe_ingredient SET amount = ? WHERE id = ?', (total, keep_id))
            conn.execute(f'DELETE FROM recipe_ingredient WHERE id IN ({",".join("?" * len(delete_ids))})',
                        delete_ids)
            print(f"    Combined {len(rows)} rows into one (total amount={total})")
        conn.commit()

    # Phase 2: Update names to canonical form
    print("\n  Updating ingredient names to canonical form...")
    remaining = conn.execute('SELECT id, name FROM ingredient').fetchall()
    for ing in remaining:
        cleaned = clean_ingredient_name(ing['name'])
        new_category = _guess_ingredient_category(cleaned['canonical'])
        conn.execute(
            'UPDATE ingredient SET name=?, display_name=?, category=? WHERE id=?',
            (cleaned['canonical'], cleaned['display_name'], new_category, ing['id'])
        )

    # Set preparation on recipe_ingredients where we extracted it from the name
    for change in name_changes:
        if change['preparation']:
            conn.execute(
                'UPDATE recipe_ingredient SET preparation = ? '
                'WHERE ingredient_id = ? AND (preparation IS NULL OR preparation = "")',
                (change['preparation'], change['id'])
            )

        # Update unit on recipe_ingredients where we extracted unit from name
        if change['extracted_unit']:
            conn.execute(
                'UPDATE recipe_ingredient SET unit = ? '
                'WHERE ingredient_id = ? AND (unit = "stuks" OR unit = "")',
                (change['extracted_unit'], change['id'])
            )

    conn.commit()

    # Handle unique constraint violations on ingredient.name after rename
    # (two different old ingredients might map to the same canonical)
    name_counts = conn.execute(
        'SELECT name, COUNT(*) as cnt FROM ingredient GROUP BY name HAVING cnt > 1'
    ).fetchall()
    if name_counts:
        print(f"\n  Resolving {len(name_counts)} name collisions after canonicalization...")
        for row in name_counts:
            dupes = conn.execute(
                'SELECT id, name, ah_product_id FROM ingredient WHERE name = ? ORDER BY '
                'CASE WHEN ah_product_id IS NOT NULL THEN 0 ELSE 1 END, id',
                (row['name'],)
            ).fetchall()
            winner_id = dupes[0]['id']
            for loser in dupes[1:]:
                conn.execute('UPDATE recipe_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                            (winner_id, loser['id']))
                conn.execute('UPDATE custom_shopping_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                            (winner_id, loser['id']))
                conn.execute('UPDATE OR IGNORE shopping_list_override SET ingredient_id = ? WHERE ingredient_id = ?',
                            (winner_id, loser['id']))
                conn.execute('DELETE FROM shopping_list_override WHERE ingredient_id = ?', (loser['id'],))
                # Transfer AH link
                if not dupes[0]['ah_product_id'] and loser['ah_product_id']:
                    conn.execute(
                        'UPDATE ingredient SET ah_product_id = (SELECT ah_product_id FROM ingredient WHERE id = ?), '
                        'ah_product_name = (SELECT ah_product_name FROM ingredient WHERE id = ?), '
                        'ah_product_size = (SELECT ah_product_size FROM ingredient WHERE id = ?), '
                        'ah_product_price = (SELECT ah_product_price FROM ingredient WHERE id = ?), '
                        'ah_product_image = (SELECT ah_product_image FROM ingredient WHERE id = ?), '
                        'ah_product_bonus = (SELECT ah_product_bonus FROM ingredient WHERE id = ?), '
                        'ah_product_updated = (SELECT ah_product_updated FROM ingredient WHERE id = ?), '
                        'ah_product_color = (SELECT ah_product_color FROM ingredient WHERE id = ?) '
                        'WHERE id = ?',
                        (loser['id'], loser['id'], loser['id'], loser['id'],
                         loser['id'], loser['id'], loser['id'], loser['id'], winner_id)
                    )
                conn.execute('DELETE FROM ingredient WHERE id = ?', (loser['id'],))
                print(f"    Resolved collision: merged id={loser['id']} into id={winner_id} for name='{row['name']}'")
        conn.commit()

    # Phase 4: Create aliases
    print("\n  Creating aliases...")
    remaining = conn.execute('SELECT id, name FROM ingredient').fetchall()
    alias_count = 0

    # Build reverse synonym map: canonical -> all known aliases
    reverse_synonyms = defaultdict(set)
    for canonical, aliases in KNOWN_SYNONYMS.items():
        cn = _normalize_ingredient(canonical)
        for a in aliases:
            reverse_synonyms[cn].add(_normalize_ingredient(a))

    for ing in remaining:
        canonical = ing['name']
        aliases = {canonical}

        # Add common plurals
        aliases.add(canonical + 'en')
        aliases.add(canonical + 's')
        if canonical.endswith(('el', 'er', 'em', 'en')):
            aliases.add(canonical + 's')
        if not canonical.endswith(('en', 's')):
            aliases.add(canonical + 'en')

        # Add known synonyms
        if canonical in reverse_synonyms:
            aliases.update(reverse_synonyms[canonical])

        # Find old names that mapped to this ingredient (from the merge phase)
        for merge in auto_merges:
            if merge['winner_id'] == ing['id']:
                for old_name in merge['loser_names']:
                    aliases.add(_normalize_ingredient(old_name.lower().strip()))

        for alias in aliases:
            normalized = _normalize_ingredient(alias.strip())
            if not normalized:
                continue
            try:
                conn.execute(
                    'INSERT OR IGNORE INTO ingredient_alias (alias, ingredient_id) VALUES (?, ?)',
                    (normalized, ing['id'])
                )
                alias_count += 1
            except Exception:
                pass

    conn.commit()
    print(f"  Created {alias_count} aliases for {len(remaining)} ingredients")

    # ── Final stats ──
    print("\n=== MIGRATION COMPLETE ===")
    final_count = conn.execute('SELECT COUNT(*) FROM ingredient').fetchone()[0]
    alias_total = conn.execute('SELECT COUNT(*) FROM ingredient_alias').fetchone()[0]
    ah_count = conn.execute('SELECT COUNT(*) FROM ingredient WHERE ah_product_id IS NOT NULL').fetchone()[0]
    orphan_fks = conn.execute(
        'SELECT COUNT(*) FROM recipe_ingredient WHERE ingredient_id NOT IN (SELECT id FROM ingredient)'
    ).fetchone()[0]
    print(f"  Ingredients: {len(ingredients)} -> {final_count}")
    print(f"  Aliases: {alias_total}")
    print(f"  AH-linked: {ah_count}")
    print(f"  Orphaned FKs: {orphan_fks}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Migrate ingredient data')
    parser.add_argument('--db', default='/pool/apps/weekmenu-planner/data/weekmenu.db',
                        help='Path to SQLite database')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview changes without writing')
    parser.add_argument('--apply', action='store_true',
                        help='Apply changes to database')
    parser.add_argument('--review', help='Path to reviewed review_map.json')
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("Error: specify --dry-run or --apply")
        return

    if args.apply:
        # Create backup
        backup_path = args.db + f'.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(args.db, backup_path)
        print(f"Backup created: {backup_path}")

    run_migration(args.db, dry_run=args.dry_run, review_path=args.review)


if __name__ == '__main__':
    main()
