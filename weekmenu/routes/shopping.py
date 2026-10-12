import json
from datetime import date, datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, Recipe, ShoppingListOverride, CustomShoppingIngredient, QuickAddItem,
)
from weekmenu.constants import CATEGORY_ORDER_SUPERMARKET, BRONNEN
from weekmenu.services.shopping import (
    send_dict_to_ah, build_combined_shopping_list, huidige_uitgang,
)
from weekmenu.services import afgehandeld
from weekmenu.services.units import _normalize_ri_unit

bp = Blueprint('shopping', __name__)


def _grouped(items):
    category_order = {cat: i for i, cat in enumerate(CATEGORY_ORDER_SUPERMARKET)}
    items = sorted(items, key=lambda x: (category_order.get(x['category'], 999), x['name']))
    grouped = []
    for item in items:
        if not grouped or grouped[-1]['category'] != item['category']:
            grouped.append({'category': item['category'], 'producten': []})
        grouped[-1]['producten'].append(item)
    return grouped


@bp.route('/boodschappen')
def boodschappen():
    data = build_combined_shopping_list()
    recipes = Recipe.query.order_by(Recipe.name).all()
    recipes_json = json.dumps([{'id': r.id, 'name': r.name, 'serves': r.serves}
                               for r in recipes])
    weeks_json = json.dumps({str(k): v for k, v in data['weeks_by_ingredient'].items()})
    iso_now = date.today().isocalendar()
    # Wat je niet bij de AH haalt komt in een eigen blok onderaan, zodat je
    # het op papier los kunt afscheuren.
    ah_items = [i for i in data['open'] if (i.get('bron') or 'ah') == 'ah']
    elders_items = [i for i in data['open'] if (i.get('bron') or 'ah') != 'ah']
    elders = []
    for code, label in BRONNEN:
        if code == 'ah':
            continue
        producten = sorted((i for i in elders_items if i['bron'] == code),
                           key=lambda x: x['name'])
        if producten:
            elders.append({'category': label, 'producten': producten})

    return render_template('boodschappen.html',
                           grouped_open=_grouped(ah_items),
                           grouped_elders=elders,
                           bronnen=BRONNEN,
                           uitgang=huidige_uitgang(),
                           checked_items=sorted(data['checked'],
                                                key=lambda x: x['checked_at'] or datetime.min,
                                                reverse=True),
                           quick_add=data['quick_add'],
                           losse_recepten_json=json.dumps(data['quick_add']),
                           recipes_json=recipes_json,
                           weeks_by_ingredient_json=weeks_json,
                           current_year=iso_now[0],
                           current_week=iso_now[1])


def _vink_af(ingredient_id, data, via_ah=False):
    """Vink af wat er van dit ingredient open staat; geeft de weken terug.

    `data` is de al gebouwde lijst: bulk-aanroepers (alles afvinken, naar de
    AH sturen) bouwen hem één keer en committen één keer. Per regel opnieuw
    bouwen kostte zes seconden op de echte data. De aantal-override van die
    week hoort bij wat nu gekocht is en vervalt: anders bepaalt hij straks het
    aantal voor iets wat er later bij komt.
    """
    weken = data['open_per_week'].get(ingredient_id, {})
    for (y, w), per_eenheid in weken.items():
        afgehandeld.vink_af(y, w, ingredient_id, per_eenheid, via_ah=via_ah)
        ShoppingListOverride.query.filter_by(
            year=y, week_number=w, ingredient_id=ingredient_id).delete()
    return list(weken)


def _log_handmatig(row, weken):
    """Wat je zelf afvinkt gaat in dezelfde pot als de AH-order van die week.

    Anders mist het log juist de slager, de markt en alles wat nooit aan een
    AH-product is gekoppeld -- en dat is de helft van de vraag 'wat kocht ik nou'.
    """
    from weekmenu.services.bestellingen import leg_handmatig_vast
    for (y, w) in weken:
        leg_handmatig_vast(y, w, row['ingredient_id'], row['amount'],
                           row['unit'], row.get('bron'))


@bp.route('/api/boodschappen/item/<int:ingredient_id>/check', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_check(ingredient_id):
    body = request.get_json(silent=True) or {}
    data = build_combined_shopping_list()
    if body.get('checked', True):
        row = next((r for r in data['open'] if r['ingredient_id'] == ingredient_id), None)
        weken = _vink_af(ingredient_id, data)
        if not weken:
            return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
        db.session.commit()
        if row:
            _log_handmatig(row, weken)
        return jsonify({'status': 'success'})
    # Uitzetten in het afgevinkt-blok: alleen de weken die het blok toont. Alle
    # weken wissen zette op de live-data ook week 13, 18 en 33 weer open.
    weken = data['afgevinkt_weken'].get(ingredient_id, [])
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w) in weken:
        afgehandeld.vinkje_eraf(y, w, ingredient_id)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/item/<int:ingredient_id>/remove', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_remove(ingredient_id):
    """✕: wat nu open staat hoeft niet gekocht te worden.

    Losse items blijven bestaan; het getal dekt ze, en wat er later bij komt
    staat gewoon open. Weg is weg (Rutger, 4 okt 2026); terugzetten kan via
    het afgevinkt-blok.
    """
    weken = build_combined_shopping_list()['open_per_week'].get(ingredient_id, {})
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w), per_eenheid in weken.items():
        afgehandeld.haal_weg(y, w, ingredient_id, per_eenheid)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/item/<int:ingredient_id>/terugzetten', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_terugzetten(ingredient_id):
    """Een weggehaalde regel terug op de lijst; alleen de weken die het blok toont."""
    weken = build_combined_shopping_list()['weggehaald_weken'].get(ingredient_id, [])
    if not weken:
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    for (y, w) in weken:
        afgehandeld.kruisje_eraf(y, w, ingredient_id)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/check-all', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_check_all():
    data = build_combined_shopping_list()
    per_ingredient = {}
    for row in data['open']:
        per_ingredient.setdefault(row['ingredient_id'], row)
    per_regel = [(row, _vink_af(ing_id, data)) for ing_id, row in per_ingredient.items()]
    db.session.commit()
    for row, weken in per_regel:
        if weken:
            _log_handmatig(row, weken)
    return jsonify({'status': 'success', 'checked': len(data['open'])})


@bp.route('/api/boodschappen/send-to-ah', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_send_to_ah():
    body = request.get_json(silent=True) or {}
    qty_overrides = {int(k): v for k, v in body.get('qty_overrides', {}).items()}
    data = build_combined_shopping_list()
    open_dict = {}
    for row in data['open']:
        # Wat je bij de toko of de slager haalt hoort niet in het AH-mandje,
        # en mag daarna ook niet als 'via AH besteld' worden afgevinkt.
        if (row.get('bron') or 'ah') != 'ah':
            continue
        open_dict[(row['ingredient_id'], row['unit'])] = row['amount']
    weken = {wk for row in data['open']
             for wk in data['weeks_by_ingredient'].get(row['ingredient_id'], [])}
    payload, status, sent_ids = send_dict_to_ah(open_dict, qty_overrides)
    if status == 200 and payload.get('status') == 'success' and sent_ids:
        for ing_id in sent_ids:
            _vink_af(ing_id, data, via_ah=True)
        db.session.commit()
        _leg_de_bestelling_vast(payload.get('order_id'), weken)
    return jsonify(payload), status


def _leg_de_bestelling_vast(order_id, weken):
    """Lees terug wat er nu echt in de order staat en bewaar dat per week.

    Niet wat de app heeft doorgestuurd: zodra het magazijn iets niet heeft wijkt
    de order af, en juist die werkelijkheid is waar je achteraf naar kijkt. De
    snapshot wordt later nog ververst als je de winkelmand opent, want tot de
    sluitingstijd kan de order nog veranderen.
    """
    if not order_id or not weken:
        return
    from weekmenu.services.ah import ah_get_order
    from weekmenu.services.bestellingen import leg_ah_order_vast
    order = ah_get_order(order_id)
    if not order:
        return
    for (y, w) in weken:
        leg_ah_order_vast(y, w, order)


@bp.route('/api/boodschappen/extra', methods=['POST'])
@afgehandeld.een_tegelijk
def boodschappen_extra_add():
    body = request.get_json(silent=True) or {}
    recipe = db.session.get(Recipe, body.get('recipe_id') or 0)
    if not recipe:
        return jsonify({'status': 'error', 'message': 'Recept niet gevonden'}), 404
    iso = date.today().isocalendar()
    personen = body.get('people_count') or recipe.serves or 4
    # Staat het recept deze week al als los recept op de lijst, dan vroeg de
    # client of het dezelfde maaltijd is: ja past het aantal personen aan, nee
    # (erbij) maakt een tweede los recept. Toevoegen zet alleen het nieuwe op
    # de lijst; wat al afgevinkt of weggehaald is blijft dat.
    qi = None if body.get('erbij') else QuickAddItem.query.filter_by(
        recipe_id=recipe.id, year=iso[0], week_number=iso[1]).first()
    if qi:
        qi.people_count = personen
    else:
        qi = QuickAddItem(recipe_id=recipe.id, people_count=personen,
                          year=iso[0], week_number=iso[1])
        db.session.add(qi)
    db.session.commit()
    return jsonify({'status': 'success', 'id': qi.id})


@bp.route('/api/boodschappen/extra/<int:id>', methods=['DELETE'])
def boodschappen_extra_delete(id):
    qi = db.get_or_404(QuickAddItem, id)
    db.session.delete(qi)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    return redirect(url_for('shopping.boodschappen'), code=301)


@bp.route('/api/shopping-list/<int:year>/<int:week>/item/<int:ingredient_id>/qty',
           methods=['POST'])
def update_shopping_qty(year, week, ingredient_id):
    data = request.get_json(force=True) or {}
    try:
        new_qty = int(data['qty'])
    except (KeyError, ValueError, TypeError):
        return jsonify({'ok': False, 'error': 'qty must be an integer'}), 400
    if new_qty < 1:
        return jsonify({'ok': False, 'error': 'qty must be >= 1'}), 400

    override = ShoppingListOverride.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).first()

    if data.get('is_default'):
        if override:
            db.session.delete(override)
            db.session.commit()
        return jsonify({'status': 'success', 'qty': new_qty, 'is_default': True})

    if override:
        override.qty = new_qty
    else:
        db.session.add(ShoppingListOverride(
            year=year, week_number=week,
            ingredient_id=ingredient_id, qty=new_qty
        ))
    db.session.commit()
    return jsonify({'status': 'success', 'qty': new_qty})


@bp.route('/api/shopping-list/<int:year>/<int:week>/add-item', methods=['POST'])
@afgehandeld.een_tegelijk
def add_shopping_item(year, week):
    data = request.get_json(force=True) or {}
    ingredient_id = data.get('ingredient_id')
    if not ingredient_id:
        return jsonify({'status': 'error', 'message': 'ingredient_id is verplicht'}), 400

    ing = db.session.get(Ingredient, ingredient_id)
    if not ing:
        return jsonify({'status': 'error', 'message': 'Ingrediënt niet gevonden'}), 404

    raw_amount = float(data.get('amount', 1))
    raw_unit = data.get('unit', 'stuks')
    unit, amount = _normalize_ri_unit(ing, raw_unit, raw_amount)

    # Alleen optellen bij een los item in dezelfde eenheid: 2 stuks sjalot plus
    # 500 g werd anders '502 stuks'. De tabel staat twee rijen per week toe.
    existing = CustomShoppingIngredient.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id, unit=unit
    ).first()
    if existing:
        existing.amount = existing.amount + amount
    else:
        db.session.add(CustomShoppingIngredient(
            year=year, week_number=week,
            ingredient_id=ingredient_id,
            amount=amount, unit=unit
        ))
    db.session.commit()

    return jsonify({
        'status': 'success',
        'item': {
            'ingredient_id': ing.id,
            'name': ing.display,
            'category': ing.category,
            'amount': amount,
            'unit': unit,
            'ah_product_id': ing.ah_product_id,
            'ah_product_name': ing.ah_product_name or '',
            'ah_product_size': ing.ah_product_size or '',
            'ah_product_price': ing.ah_product_price or '',
            'ah_product_image': ing.ah_product_image or '',
            'ah_product_bonus': ing.ah_product_bonus or False,
            'ah_product_color': ing.ah_product_color or '',
        }
    })


