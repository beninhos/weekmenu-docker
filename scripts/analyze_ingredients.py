#!/usr/bin/env python3
"""
Ingredient quality analysis for weekmenu-planner.
Run:  python3 scripts/analyze_ingredients.py [--db /path/to/weekmenu.db]

Read-only: does not modify the database.
"""

import argparse
import re
import sqlite3
from collections import defaultdict

# ── Copied from app.py to avoid Flask initialization ──

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
    'tablespoon': 'el', 'tablespoons': 'el', 'tbsp': 'el', 'tbs': 'el',
    'teaspoon': 'tl', 'teaspoons': 'tl', 'tsp': 'tl',
    'pound': 'pond', 'pounds': 'pond', 'lb': 'pond', 'lbs': 'pond',
    'ounce': 'oz', 'ounces': 'oz',
    'clove': 'teen', 'cloves': 'teen',
    'bunch': 'bosje', 'handful': 'handvol', 'pinch': 'snufje', 'dash': 'scheutje',
    'can': 'blik', 'slice': 'plak', 'slices': 'plak',
    'piece': 'stuks', 'pieces': 'stuks',
}

# Extended unit prefixes that may appear as first word of ingredient name
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

# Preparation prefixes that may appear as first word
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

PRODUCT_CATEGORIES = [
    'Groente & Aardappelen', 'Fruit', 'Vlees', 'Vis',
    'Vegetarisch & Vegan', 'Vleeswaren', 'Kaas', 'Zuivel & Eieren',
    'Bakkerij', 'Pasta, Rijst & Wereldkeuken', 'Blikken & Potten',
    'Soepen, Sauzen & Kruiden', 'Bakken', 'Ontbijt & Beleg',
    'Snacks & Noten', 'Koek, Snoep & Chocolade', 'Koffie & Thee',
    'Frisdrank & Water', 'Bier, Wijn & Aperitieven', 'Diepvries', 'Overig',
]

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


# ── Dutch singularization (food ingredients) ──

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
    'paprika\'s': 'paprika',
    'courgettes': 'courgette',
    'sjalotten': 'sjalot',
    'olijven': 'olijf',
    'linzen': 'linze',
    'bonen': 'boon',
    'noten': 'noot',
    'garnalen': 'garnaal',
    'mosselen': 'mossel',
    'spruitjes': 'spruitje',
}


def dutch_singularize(word):
    """Simple Dutch singularization for food ingredients."""
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    # Don't touch short words
    if len(word) <= 3:
        return word
    # -tjes suffix (diminutive plural)
    if word.endswith('tjes') and len(word) > 5:
        return word[:-1]  # snufjes -> snufje
    # -jes suffix
    if word.endswith('jes') and not word.endswith('tjes') and len(word) > 4:
        return word[:-1]  # bosuitjes -> bosuitje
    # -'s suffix (paprika's)
    if word.endswith("'s") and len(word) > 3:
        return word[:-2]
    # -s suffix (champignons)
    if word.endswith('s') and not word.endswith(('us', 'is', 'as', 'ss', 'ks')):
        return word[:-1]
    return word


# ── Analysis functions ──

def load_data(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    ingredients = conn.execute('''
        SELECT i.id, i.name, i.category, i.ah_product_id, i.ah_product_name,
               COUNT(ri.id) as ri_count
        FROM ingredient i
        LEFT JOIN recipe_ingredient ri ON ri.ingredient_id = i.id
        GROUP BY i.id
    ''').fetchall()

    recipe_ingredients = conn.execute('''
        SELECT ri.id, ri.recipe_id, ri.ingredient_id, ri.amount, ri.unit,
               i.name as ingredient_name, r.name as recipe_name
        FROM recipe_ingredient ri
        JOIN ingredient i ON i.id = ri.ingredient_id
        JOIN recipe r ON r.id = ri.recipe_id
    ''').fetchall()

    custom_items = conn.execute('''
        SELECT ci.id, ci.ingredient_id, i.name as ingredient_name
        FROM custom_shopping_ingredient ci
        JOIN ingredient i ON i.id = ci.ingredient_id
    ''').fetchall()

    conn.close()
    return ingredients, recipe_ingredients, custom_items


def find_case_duplicates(ingredients):
    """Group ingredients that differ only by case."""
    groups = defaultdict(list)
    for ing in ingredients:
        groups[ing['name'].lower()].append(ing)
    return {k: v for k, v in groups.items() if len(v) > 1}


def find_semantic_duplicates(ingredients):
    """Find ingredients that are likely the same after normalization + singularization."""
    groups = defaultdict(list)
    for ing in ingredients:
        norm = _normalize_ingredient(ing['name'].lower().strip())
        singular = dutch_singularize(norm)
        groups[singular].append(ing)
    return {k: v for k, v in groups.items() if len(v) > 1}


def find_unit_in_name(ingredients):
    """Detect ingredients where the name starts with a unit word."""
    results = []
    all_unit_prefixes = {**UNIT_PREFIXES}
    # Also check DUTCH_UNITS keys
    for k, v in DUTCH_UNITS.items():
        if k not in all_unit_prefixes and len(k) > 1:
            all_unit_prefixes[k] = v

    for ing in ingredients:
        words = ing['name'].strip().split()
        if len(words) >= 2:
            first = words[0].lower()
            if first in all_unit_prefixes:
                results.append({
                    'id': ing['id'],
                    'name': ing['name'],
                    'detected_unit': all_unit_prefixes[first],
                    'suggested_name': ' '.join(words[1:]),
                    'ri_count': ing['ri_count'],
                })
    return results


def find_preparation_in_name(ingredients):
    """Detect ingredients with preparation info embedded in the name."""
    results = []

    for ing in ingredients:
        name = ing['name'].strip()
        detected = []

        # Parenthetical content
        paren = re.search(r'\(([^)]+)\)', name)
        if paren:
            detected.append(f"parenthetical: ({paren.group(1)})")

        # Comma-separated (ui, gesnipperd)
        if ',' in name:
            after_comma = name.split(',', 1)[1].strip().lower()
            detected.append(f"comma-prep: {after_comma}")

        # Preparation prefix
        words = name.split()
        if len(words) >= 2:
            first = words[0].lower()
            if first in PREP_PREFIXES:
                detected.append(f"prefix: {first} -> prep={PREP_PREFIXES[first]}")

        # Qualifier suffixes
        lower = name.lower()
        for pattern in ['naar smaak', 'op sap', 'minder zout', 'zonder bot', 'zonder vel']:
            if pattern in lower:
                detected.append(f"suffix: {pattern}")

        if detected:
            results.append({
                'id': ing['id'],
                'name': name,
                'issues': detected,
                'ri_count': ing['ri_count'],
            })

    return results


def find_category_mismatches(ingredients):
    """Compare stored category with what _guess_ingredient_category would assign."""
    results = []
    for ing in ingredients:
        guessed = _guess_ingredient_category(ing['name'])
        if guessed != ing['category']:
            results.append({
                'id': ing['id'],
                'name': ing['name'],
                'stored': ing['category'],
                'guessed': guessed,
            })
    return results


def find_orphans(ingredients, custom_items):
    """Find ingredients with zero FK references anywhere."""
    custom_ids = {ci['ingredient_id'] for ci in custom_items}
    return [
        ing for ing in ingredients
        if ing['ri_count'] == 0 and ing['id'] not in custom_ids
    ]


def print_report(db_path):
    ingredients, recipe_ingredients, custom_items = load_data(db_path)

    print("=" * 70)
    print("INGREDIENTEN ANALYSE RAPPORT")
    print(f"Database: {db_path}")
    print(f"Totaal ingredienten: {len(ingredients)}")
    print(f"Totaal recipe_ingredients: {len(recipe_ingredients)}")
    print(f"AH-gekoppeld: {sum(1 for i in ingredients if i['ah_product_id'])}")
    print("=" * 70)

    # 1. Case duplicates
    case_dups = find_case_duplicates(ingredients)
    print(f"\n## 1. CASE-DUPLICATEN ({len(case_dups)} groepen)\n")
    if case_dups:
        for key, group in sorted(case_dups.items()):
            print(f"  Groep: '{key}'")
            for ing in group:
                ah = f" [AH#{ing['ah_product_id']}]" if ing['ah_product_id'] else ""
                print(f"    id={ing['id']:>3}  name='{ing['name']}'  cat={ing['category']}  refs={ing['ri_count']}{ah}")
    else:
        print("  Geen gevonden.")

    # 2. Semantic duplicates (broader than case)
    sem_dups = find_semantic_duplicates(ingredients)
    # Filter out groups that are already covered by case duplicates
    new_sem = {}
    for key, group in sem_dups.items():
        names_lower = set(i['name'].lower() for i in group)
        if len(names_lower) > 1:  # Actually different names, not just case
            new_sem[key] = group
    print(f"\n## 2. SEMANTISCHE DUPLICATEN ({len(new_sem)} groepen)\n")
    if new_sem:
        for key, group in sorted(new_sem.items()):
            print(f"  Canonical: '{key}'")
            for ing in group:
                ah = f" [AH#{ing['ah_product_id']}]" if ing['ah_product_id'] else ""
                print(f"    id={ing['id']:>3}  name='{ing['name']}'  refs={ing['ri_count']}{ah}")
    else:
        print("  Geen gevonden.")

    # 3. Unit in name
    unit_in_name = find_unit_in_name(ingredients)
    print(f"\n## 3. UNIT-IN-NAAM ({len(unit_in_name)} gevonden)\n")
    for item in unit_in_name:
        print(f"  id={item['id']:>3}  '{item['name']}' -> unit={item['detected_unit']}, name='{item['suggested_name']}'  refs={item['ri_count']}")

    # 4. Preparation in name
    prep_in_name = find_preparation_in_name(ingredients)
    print(f"\n## 4. BEREIDING-IN-NAAM ({len(prep_in_name)} gevonden)\n")
    for item in prep_in_name:
        issues = '; '.join(item['issues'])
        print(f"  id={item['id']:>3}  '{item['name']}' -> {issues}  refs={item['ri_count']}")

    # 5. Category mismatches
    cat_mismatches = find_category_mismatches(ingredients)
    print(f"\n## 5. CATEGORIE-MISMATCHES ({len(cat_mismatches)} gevonden)\n")
    for item in cat_mismatches:
        print(f"  id={item['id']:>3}  '{item['name']}'  opgeslagen={item['stored']}  verwacht={item['guessed']}")

    # 6. Orphan ingredients
    orphans = find_orphans(ingredients, custom_items)
    print(f"\n## 6. ORPHAN INGREDIENTEN ({len(orphans)} gevonden)\n")
    for ing in orphans:
        ah = f" [AH#{ing['ah_product_id']}]" if ing['ah_product_id'] else ""
        print(f"  id={ing['id']:>3}  '{ing['name']}'  cat={ing['category']}{ah}")

    # 7. All ingredient names (sorted, for overview)
    print(f"\n## 7. ALLE INGREDIENTEN (gesorteerd op naam)\n")
    for ing in sorted(ingredients, key=lambda x: x['name'].lower()):
        ah = f" [AH#{ing['ah_product_id']}]" if ing['ah_product_id'] else ""
        print(f"  id={ing['id']:>3}  '{ing['name']}'  cat={ing['category']}  refs={ing['ri_count']}{ah}")

    # Summary
    print("\n" + "=" * 70)
    print("SAMENVATTING")
    print(f"  Totaal ingredienten:     {len(ingredients)}")
    print(f"  Case-duplicaat groepen:  {len(case_dups)}")
    print(f"  Semantische dup groepen: {len(new_sem)}")
    print(f"  Unit-in-naam:            {len(unit_in_name)}")
    print(f"  Bereiding-in-naam:       {len(prep_in_name)}")
    print(f"  Categorie-mismatches:    {len(cat_mismatches)}")
    print(f"  Orphans:                 {len(orphans)}")
    print(f"  AH-gekoppeld:            {sum(1 for i in ingredients if i['ah_product_id'])}")
    print("=" * 70)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze ingredient quality')
    parser.add_argument('--db', default='/pool/apps/weekmenu-planner/data/weekmenu.db',
                        help='Path to SQLite database')
    args = parser.parse_args()
    print_report(args.db)
