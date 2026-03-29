#!/usr/bin/env python3
"""
Ingrediënt unit-normalisatie script voor weekmenu-planner.

Usage:
  python3 scripts/normalize_units.py --analyze                # Toon conflicten (read-only)
  python3 scripts/normalize_units.py --fix-spelling           # Normaliseer spelling in DB
  python3 scripts/normalize_units.py --interactive            # Train conversieregels
  python3 scripts/normalize_units.py --merge-duplicates       # Merge duplicate ingrediënten
  python3 scripts/normalize_units.py --apply rules.json       # Batch-apply conversieregels

Vereist: draai vanuit project root, met database op data/weekmenu.db
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

# In Docker: /data/weekmenu.db, lokaal: ./data/weekmenu.db
_LOCAL_DB = os.path.join(os.path.dirname(__file__), '..', 'data', 'weekmenu.db')
_DOCKER_DB = '/data/weekmenu.db'
DB_PATH = _DOCKER_DB if os.path.exists(_DOCKER_DB) else _LOCAL_DB

# Kopie van _UNIT_NORMALIZE uit app.py
UNIT_NORMALIZE = {
    'gram': 'g', 'gr': 'g',
    'kilogram': 'kg', 'kilo': 'kg',
    'liter': 'l', 'litre': 'l',
    'milliliter': 'ml',
    'eetlepel': 'el', 'eetlepels': 'el',
    'theelepel': 'tl', 'theelepels': 'tl',
    'stuk': 'stuks', 'st': 'stuks',
    'bollen': 'bol', 'tenen': 'teen', 'teentjes': 'teen', 'teentje': 'teen',
    'bos': 'bosje', 'tros': 'bosje',
    'plakken': 'plak', 'plakje': 'plak', 'plakjes': 'plak',
    'takjes': 'takje', 'takken': 'takje',
    'stengels': 'stengel', 'stelen': 'steel',
    'blad': 'blad', 'blaadjes': 'blad', 'blaadje': 'blad', 'bladeren': 'blad',
    'blikje': 'blik', 'blikjes': 'blik',
    'blokjes': 'blokje',
}

UNIT_CONVERSIONS = {
    ('g', 'kg'): 0.001, ('kg', 'g'): 1000,
    ('ml', 'l'): 0.001, ('l', 'ml'): 1000,
    ('cl', 'l'): 0.01, ('dl', 'l'): 0.1,
    ('cl', 'ml'): 10, ('dl', 'ml'): 100,
}


def norm_unit(u):
    raw = (u or '').lower().strip()
    return UNIT_NORMALIZE.get(raw, raw)


def backup_db(db_path):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = f'{db_path}.backup_{ts}'
    shutil.copy2(db_path, backup)
    print(f'Backup: {backup}')
    return backup


def get_multi_unit_ingredients(conn):
    """Vind ingrediënten met meerdere genormaliseerde units in recipe_ingredient."""
    rows = conn.execute('''
        SELECT ri.ingredient_id, i.name, i.display_name, i.preferred_unit,
               ri.unit, COUNT(*) as cnt, SUM(ri.amount) as total
        FROM recipe_ingredient ri
        JOIN ingredient i ON ri.ingredient_id = i.id
        GROUP BY ri.ingredient_id, ri.unit
        ORDER BY i.display_name, ri.unit
    ''').fetchall()

    by_ing = defaultdict(list)
    for r in rows:
        normalized = norm_unit(r['unit'])
        by_ing[r['ingredient_id']].append({
            'raw_unit': r['unit'],
            'norm_unit': normalized,
            'count': r['cnt'],
            'total': r['total'],
            'name': r['display_name'] or r['name'],
            'preferred_unit': r['preferred_unit'],
        })

    # Alleen ingrediënten met >1 genormaliseerde unit
    conflicts = {}
    for ing_id, entries in by_ing.items():
        norm_units = set(e['norm_unit'] for e in entries)
        if len(norm_units) > 1:
            conflicts[ing_id] = entries

    return conflicts


def get_spelling_variants(conn):
    """Vind units die anders geschreven zijn maar hetzelfde normaliseren."""
    rows = conn.execute('''
        SELECT ri.id, ri.unit, ri.ingredient_id
        FROM recipe_ingredient ri
        WHERE ri.unit != ''
    ''').fetchall()

    variants = []
    for r in rows:
        raw = r['unit']
        normalized = norm_unit(raw)
        if raw != normalized:
            variants.append({
                'ri_id': r['id'],
                'ingredient_id': r['ingredient_id'],
                'raw': raw,
                'normalized': normalized,
            })
    return variants


# ── Commands ──

def cmd_analyze(conn):
    """Analyseer en toon unit-conflicten."""
    print('\n=== SPELLING-VARIANTEN ===')
    print('Units die anders geschreven zijn maar hetzelfde normaliseren:\n')
    variants = get_spelling_variants(conn)
    by_pair = defaultdict(int)
    for v in variants:
        by_pair[(v['raw'], v['normalized'])] += 1
    if by_pair:
        for (raw, norm), cnt in sorted(by_pair.items(), key=lambda x: -x[1]):
            print(f'  "{raw}" → "{norm}"  ({cnt}×)')
        print(f'\n  Totaal: {len(variants)} records met spelling-varianten')
        print('  Fix met: --fix-spelling')
    else:
        print('  Geen spelling-varianten gevonden.')

    print('\n=== UNIT-CONFLICTEN ===')
    print('Ingrediënten met meerdere genormaliseerde units:\n')
    conflicts = get_multi_unit_ingredients(conn)
    if not conflicts:
        print('  Geen conflicten gevonden!')
        return

    for ing_id, entries in sorted(conflicts.items(), key=lambda x: x[1][0]['name']):
        name = entries[0]['name']
        pref = entries[0]['preferred_unit']
        pref_str = f' [preferred: {pref}]' if pref else ''
        print(f'  {name} (id={ing_id}){pref_str}:')

        # Groepeer per genormaliseerde unit
        by_norm = defaultdict(lambda: {'count': 0, 'total': 0, 'raw_units': set()})
        for e in entries:
            g = by_norm[e['norm_unit']]
            g['count'] += e['count']
            g['total'] += e['total']
            g['raw_units'].add(e['raw_unit'])

        for norm, data in sorted(by_norm.items(), key=lambda x: -x[1]['count']):
            raws = ', '.join(sorted(data['raw_units']))
            print(f'    {norm} ({data["count"]}× recepten, totaal {data["total"]:.1f}) [opgeslagen als: {raws}]')

        # Check of globale conversie beschikbaar is
        norms = list(by_norm.keys())
        for i, a in enumerate(norms):
            for b in norms[i+1:]:
                if (a, b) in UNIT_CONVERSIONS or (b, a) in UNIT_CONVERSIONS:
                    print(f'    → Globale conversie beschikbaar: {a} ↔ {b}')
        print()

    print(f'  Totaal: {len(conflicts)} ingrediënten met unit-conflicten')
    print('  Fix met: --interactive')

    # Check bestaande conversieregels
    existing = conn.execute('SELECT * FROM ingredient_unit_conversion').fetchall()
    if existing:
        print(f'\n=== BESTAANDE CONVERSIEREGELS ({len(existing)}) ===')
        for r in existing:
            ing = conn.execute('SELECT display_name, name FROM ingredient WHERE id = ?', (r['ingredient_id'],)).fetchone()
            name = ing['display_name'] or ing['name'] if ing else f'id={r["ingredient_id"]}'
            print(f'  {name}: {r["from_unit"]} → {r["to_unit"]} (×{r["factor"]})')


def cmd_fix_spelling(conn, dry_run=False):
    """Normaliseer spelling-varianten in recipe_ingredient.unit."""
    variants = get_spelling_variants(conn)
    if not variants:
        print('Geen spelling-varianten om te fixen.')
        return

    by_pair = defaultdict(list)
    for v in variants:
        by_pair[(v['raw'], v['normalized'])].append(v['ri_id'])

    print(f'{"[DRY RUN] " if dry_run else ""}Spelling-normalisatie:')
    for (raw, norm), ri_ids in sorted(by_pair.items(), key=lambda x: -len(x[1])):
        print(f'  "{raw}" → "{norm}"  ({len(ri_ids)} records)')
        if not dry_run:
            conn.execute(
                'UPDATE recipe_ingredient SET unit = ? WHERE id IN ({})'.format(
                    ','.join('?' * len(ri_ids))
                ),
                [norm] + ri_ids
            )

    # Ook custom_shopping_ingredient normaliseren
    csi_rows = conn.execute('SELECT id, unit FROM custom_shopping_ingredient WHERE unit != ""').fetchall()
    csi_fixes = []
    for r in csi_rows:
        normalized = norm_unit(r['unit'])
        if r['unit'] != normalized:
            csi_fixes.append((normalized, r['id']))

    if csi_fixes:
        print(f'\n  custom_shopping_ingredient: {len(csi_fixes)} records')
        if not dry_run:
            for norm_val, csi_id in csi_fixes:
                conn.execute('UPDATE custom_shopping_ingredient SET unit = ? WHERE id = ?', (norm_val, csi_id))

    if not dry_run:
        conn.commit()
        total = sum(len(ids) for ids in by_pair.values()) + len(csi_fixes)
        print(f'\n✓ {total} records genormaliseerd.')
    else:
        print('\n  Gebruik --fix-spelling zonder --dry-run om toe te passen.')


def cmd_interactive(conn):
    """Interactieve modus: stel preferred_unit en conversieregels in."""
    conflicts = get_multi_unit_ingredients(conn)
    if not conflicts:
        print('Geen unit-conflicten gevonden. Draai eerst --fix-spelling.')
        return

    # Filter al geconfigureerde ingrediënten
    existing_prefs = {}
    for row in conn.execute('SELECT id, preferred_unit FROM ingredient WHERE preferred_unit IS NOT NULL').fetchall():
        existing_prefs[row['id']] = row['preferred_unit']

    existing_convs = set()
    for row in conn.execute('SELECT ingredient_id, from_unit FROM ingredient_unit_conversion').fetchall():
        existing_convs.add((row['ingredient_id'], row['from_unit']))

    unconfigured = {
        ing_id: entries for ing_id, entries in conflicts.items()
        if ing_id not in existing_prefs
    }

    if not unconfigured:
        print('Alle conflicten zijn al geconfigureerd.')
        # Toon status
        for ing_id, entries in conflicts.items():
            name = entries[0]['name']
            pref = existing_prefs.get(ing_id, '?')
            print(f'  ✓ {name}: preferred_unit={pref}')
        return

    print(f'\n{len(unconfigured)} ingrediënten met unit-conflicten te configureren.\n')
    print('Voor elk ingrediënt: kies een voorkeurseenheid of typ "skip".\n')

    configured = 0
    for ing_id, entries in sorted(unconfigured.items(), key=lambda x: x[1][0]['name']):
        name = entries[0]['name']

        # Groepeer per genormaliseerde unit
        by_norm = defaultdict(lambda: {'count': 0, 'total': 0})
        for e in entries:
            g = by_norm[e['norm_unit']]
            g['count'] += e['count']
            g['total'] += e['total']

        norms = sorted(by_norm.keys(), key=lambda u: -by_norm[u]['count'])

        print(f'─── {name} (id={ing_id}) ───')
        for u in norms:
            d = by_norm[u]
            print(f'  {u} ({d["count"]} recepten, totaal {d["total"]:.1f})')

        options = '/'.join(norms) + '/skip'
        while True:
            choice = input(f'  Voorkeurseenheid [{options}]: ').strip().lower()
            if choice == 'skip':
                print('  → Overgeslagen\n')
                break
            if choice in by_norm:
                # Sla preferred_unit op
                conn.execute(
                    'UPDATE ingredient SET preferred_unit = ? WHERE id = ?',
                    (choice, ing_id)
                )

                # Vraag conversieregels voor andere units
                other_units = [u for u in norms if u != choice]
                for other in other_units:
                    if (ing_id, other) in existing_convs:
                        print(f'  Conversie {other}→{choice} bestaat al, overgeslagen.')
                        continue

                    # Check globale conversie
                    gfactor = UNIT_CONVERSIONS.get((other, choice))
                    default = gfactor if gfactor else 1.0

                    while True:
                        raw = input(f'  1 {other} {name} = ? {choice} [{default}]: ').strip()
                        if not raw:
                            factor = default
                            break
                        try:
                            factor = float(raw.replace(',', '.'))
                            break
                        except ValueError:
                            print('  Ongeldig getal, probeer opnieuw.')

                    conn.execute(
                        '''INSERT OR REPLACE INTO ingredient_unit_conversion
                           (ingredient_id, from_unit, to_unit, factor)
                           VALUES (?, ?, ?, ?)''',
                        (ing_id, other, choice, factor)
                    )
                    print(f'  ✓ Conversie: {other}→{choice} (×{factor})')

                    # Converteer bestaande recipe_ingredients
                    affected = conn.execute(
                        '''SELECT id, amount FROM recipe_ingredient
                           WHERE ingredient_id = ? AND unit = ?''',
                        (ing_id, other)
                    ).fetchall()
                    # Ook rijen met spelling-varianten die naar 'other' normaliseren
                    raw_variants = [k for k, v in UNIT_NORMALIZE.items() if v == other]
                    for rv in raw_variants:
                        more = conn.execute(
                            '''SELECT id, amount FROM recipe_ingredient
                               WHERE ingredient_id = ? AND unit = ?''',
                            (ing_id, rv)
                        ).fetchall()
                        affected.extend(more)

                    if affected:
                        for row in affected:
                            new_amount = row['amount'] * factor
                            conn.execute(
                                'UPDATE recipe_ingredient SET unit = ?, amount = ? WHERE id = ?',
                                (choice, new_amount, row['id'])
                            )
                        print(f'  ✓ {len(affected)} bestaande records geconverteerd: {other}→{choice}')

                conn.commit()
                configured += 1
                print(f'  ✓ {name}: preferred_unit={choice}\n')
                break
            else:
                print(f'  Ongeldige keuze. Kies uit: {options}')

    print(f'\n{"═" * 40}')
    print(f'✓ {configured} ingrediënten geconfigureerd.')


def cmd_merge_duplicates(conn, dry_run=False):
    """Vind en merge mogelijke duplicate ingrediënten."""
    rows = conn.execute('''
        SELECT i.id, i.name, i.display_name, i.category, i.ah_product_id,
               COUNT(ri.id) as ri_count
        FROM ingredient i
        LEFT JOIN recipe_ingredient ri ON i.id = ri.ingredient_id
        GROUP BY i.id
        ORDER BY i.name
    ''').fetchall()

    # Groepeer per genormaliseerde naam (simpele substring-match)
    by_name = defaultdict(list)
    for r in rows:
        by_name[r['name']].append(dict(r))

    # Vind namen die substring zijn van andere namen
    all_names = sorted(by_name.keys())
    candidates = []
    for i, a in enumerate(all_names):
        for b in all_names[i+1:]:
            # Check of a een substring is van b of omgekeerd
            if a in b or b in a:
                ings_a = by_name[a]
                ings_b = by_name[b]
                candidates.append((ings_a, ings_b))

    if not candidates:
        print('Geen mogelijke duplicaten gevonden.')
        return

    print(f'\n{"[DRY RUN] " if dry_run else ""}{len(candidates)} mogelijke duplicaat-paren gevonden:\n')

    merged = 0
    for group_a, group_b in candidates:
        a = group_a[0]
        b = group_b[0]
        print(f'  Mogelijk duplicaat:')
        print(f'    A: "{a["display_name"] or a["name"]}" (id={a["id"]}, {a["ri_count"]} recepten, AH: {"ja" if a["ah_product_id"] else "nee"})')
        print(f'    B: "{b["display_name"] or b["name"]}" (id={b["id"]}, {b["ri_count"]} recepten, AH: {"ja" if b["ah_product_id"] else "nee"})')

        if dry_run:
            print()
            continue

        while True:
            choice = input(f'  Merge? [a=behoud A, b=behoud B, skip]: ').strip().lower()
            if choice == 'skip':
                print('  → Overgeslagen\n')
                break
            if choice in ('a', 'b'):
                winner = a if choice == 'a' else b
                loser = b if choice == 'a' else a

                # Re-point recipe_ingredients
                conn.execute(
                    'UPDATE recipe_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                    (winner['id'], loser['id'])
                )
                # Re-point custom_shopping_ingredient
                conn.execute(
                    'UPDATE custom_shopping_ingredient SET ingredient_id = ? WHERE ingredient_id = ?',
                    (winner['id'], loser['id'])
                )
                # Re-point shopping_list_override (delete conflicts)
                conn.execute(
                    'DELETE FROM shopping_list_override WHERE ingredient_id = ?',
                    (loser['id'],)
                )
                # Re-point shopping_list_exclusion (delete conflicts)
                conn.execute(
                    'DELETE FROM shopping_list_exclusion WHERE ingredient_id = ?',
                    (loser['id'],)
                )
                # Add alias for loser name
                try:
                    conn.execute(
                        'INSERT OR IGNORE INTO ingredient_alias (alias, ingredient_id) VALUES (?, ?)',
                        (loser['name'], winner['id'])
                    )
                except Exception:
                    pass
                # Delete loser aliases
                conn.execute('UPDATE ingredient_alias SET ingredient_id = ? WHERE ingredient_id = ?',
                             (winner['id'], loser['id']))
                # Delete unit conversions for loser
                conn.execute('DELETE FROM ingredient_unit_conversion WHERE ingredient_id = ?', (loser['id'],))
                # Delete loser
                conn.execute('DELETE FROM ingredient WHERE id = ?', (loser['id'],))

                conn.commit()
                merged += 1
                w_name = winner['display_name'] or winner['name']
                l_name = loser['display_name'] or loser['name']
                print(f'  ✓ "{l_name}" gemerged in "{w_name}"\n')
                break
            else:
                print('  Ongeldige keuze.')

    print(f'\n✓ {merged} merges uitgevoerd.')


def cmd_apply(conn, rules_path):
    """Batch-apply conversieregels uit JSON-bestand."""
    with open(rules_path) as f:
        rules = json.load(f)

    for rule in rules.get('conversions', []):
        ing_id = rule['ingredient_id']
        pref = rule['preferred_unit']
        ing = conn.execute('SELECT display_name, name FROM ingredient WHERE id = ?', (ing_id,)).fetchone()
        name = (ing['display_name'] or ing['name']) if ing else f'id={ing_id}'

        conn.execute('UPDATE ingredient SET preferred_unit = ? WHERE id = ?', (pref, ing_id))
        print(f'{name}: preferred_unit={pref}')

        for r in rule.get('rules', []):
            conn.execute(
                '''INSERT OR REPLACE INTO ingredient_unit_conversion
                   (ingredient_id, from_unit, to_unit, factor) VALUES (?, ?, ?, ?)''',
                (ing_id, r['from'], pref, r['factor'])
            )
            print(f'  {r["from"]}→{pref} (×{r["factor"]})')

            # Converteer bestaande records
            affected = conn.execute(
                'SELECT id, amount FROM recipe_ingredient WHERE ingredient_id = ? AND unit = ?',
                (ing_id, r['from'])
            ).fetchall()
            for row in affected:
                conn.execute(
                    'UPDATE recipe_ingredient SET unit = ?, amount = ? WHERE id = ?',
                    (pref, row['amount'] * r['factor'], row['id'])
                )
            if affected:
                print(f'  ✓ {len(affected)} records geconverteerd')

    for merge in rules.get('merges', []):
        winner_id = merge['winner_id']
        for loser_id in merge.get('loser_ids', []):
            conn.execute('UPDATE recipe_ingredient SET ingredient_id = ? WHERE ingredient_id = ?', (winner_id, loser_id))
            conn.execute('UPDATE custom_shopping_ingredient SET ingredient_id = ? WHERE ingredient_id = ?', (winner_id, loser_id))
            conn.execute('DELETE FROM shopping_list_override WHERE ingredient_id = ?', (loser_id,))
            conn.execute('DELETE FROM shopping_list_exclusion WHERE ingredient_id = ?', (loser_id,))
            conn.execute('INSERT OR IGNORE INTO ingredient_alias (alias, ingredient_id) SELECT name, ? FROM ingredient WHERE id = ?', (winner_id, loser_id))
            conn.execute('UPDATE ingredient_alias SET ingredient_id = ? WHERE ingredient_id = ?', (winner_id, loser_id))
            conn.execute('DELETE FROM ingredient_unit_conversion WHERE ingredient_id = ?', (loser_id,))
            conn.execute('DELETE FROM ingredient WHERE id = ?', (loser_id,))
            print(f'  Merge: id={loser_id} → id={winner_id}')

    conn.commit()
    print('\n✓ Regels toegepast.')


def main():
    parser = argparse.ArgumentParser(description='Ingrediënt unit-normalisatie')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--analyze', action='store_true', help='Toon conflicten (read-only)')
    group.add_argument('--fix-spelling', action='store_true', help='Normaliseer unit-spelling in DB')
    group.add_argument('--interactive', action='store_true', help='Interactief conversieregels instellen')
    group.add_argument('--merge-duplicates', action='store_true', help='Merge duplicate ingrediënten')
    group.add_argument('--apply', metavar='FILE', help='Batch-apply regels uit JSON')
    parser.add_argument('--dry-run', action='store_true', help='Toon wat er zou gebeuren')
    parser.add_argument('--db', default=DB_PATH, help='Pad naar database')
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f'Database niet gevonden: {args.db}')
        sys.exit(1)

    # Backup bij schrijf-operaties
    if not args.analyze and not args.dry_run:
        backup_db(args.db)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        if args.analyze:
            cmd_analyze(conn)
        elif args.fix_spelling:
            cmd_fix_spelling(conn, dry_run=args.dry_run)
        elif args.interactive:
            if args.dry_run:
                print('--dry-run niet ondersteund voor --interactive')
                sys.exit(1)
            cmd_interactive(conn)
        elif args.merge_duplicates:
            cmd_merge_duplicates(conn, dry_run=args.dry_run)
        elif args.apply:
            if args.dry_run:
                print('--dry-run niet ondersteund voor --apply')
                sys.exit(1)
            cmd_apply(conn, args.apply)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
