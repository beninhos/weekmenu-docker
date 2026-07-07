import json
from datetime import date, datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for

from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, Recipe, ShoppingListOverride,
    ShoppingListExclusion, CustomShoppingIngredient,
    ShoppingCheck, QuickAddItem,
)
from weekmenu.constants import CATEGORY_ORDER_SUPERMARKET
from weekmenu.services.shopping import (
    _build_shopping_dict, send_dict_to_ah, build_combined_shopping_list,
)
from weekmenu.services.units import _normalize_ri_unit
from weekmenu.services.menu import clear_shopping_list as _clear_shopping_list

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
    return render_template('boodschappen.html',
                           grouped_open=_grouped(data['open']),
                           checked_items=sorted(data['checked'],
                                                key=lambda x: x['checked_at'] or datetime.min,
                                                reverse=True),
                           quick_add=data['quick_add'],
                           recipes_json=recipes_json,
                           weeks_by_ingredient_json=weeks_json,
                           current_year=iso_now[0],
                           current_week=iso_now[1])


def _set_checks(ingredient_id, checked, via_ah=False):
    data = build_combined_shopping_list()
    weeks = data['weeks_by_ingredient'].get(ingredient_id)
    if not weeks:
        return False
    for (y, w) in weeks:
        existing = ShoppingCheck.query.filter_by(
            year=y, week_number=w, ingredient_id=ingredient_id).first()
        if checked and not existing:
            db.session.add(ShoppingCheck(year=y, week_number=w,
                                         ingredient_id=ingredient_id, via_ah=via_ah))
        elif not checked and existing:
            db.session.delete(existing)
    db.session.commit()
    return True


@bp.route('/api/boodschappen/item/<int:ingredient_id>/check', methods=['POST'])
def boodschappen_check(ingredient_id):
    body = request.get_json(silent=True) or {}
    if not _set_checks(ingredient_id, bool(body.get('checked', True))):
        return jsonify({'status': 'error', 'message': 'Item niet gevonden'}), 404
    return jsonify({'status': 'success'})


@bp.route('/api/boodschappen/check-all', methods=['POST'])
def boodschappen_check_all():
    data = build_combined_shopping_list()
    for row in data['open']:
        _set_checks(row['ingredient_id'], True)
    return jsonify({'status': 'success', 'checked': len(data['open'])})


@bp.route('/api/boodschappen/send-to-ah', methods=['POST'])
def boodschappen_send_to_ah():
    body = request.get_json(silent=True) or {}
    qty_overrides = {int(k): v for k, v in body.get('qty_overrides', {}).items()}
    data = build_combined_shopping_list()
    open_dict = {}
    for row in data['open']:
        open_dict[(row['ingredient_id'], row['unit'])] = row['amount']
    payload, status, sent_ids = send_dict_to_ah(open_dict, qty_overrides)
    if status == 200 and payload.get('status') == 'ok' and sent_ids:
        for ing_id in sent_ids:
            _set_checks(ing_id, True, via_ah=True)
    return jsonify(payload), status


@bp.route('/api/boodschappen/extra', methods=['POST'])
def boodschappen_extra_add():
    body = request.get_json(silent=True) or {}
    recipe = Recipe.query.get(body.get('recipe_id') or 0)
    if not recipe:
        return jsonify({'status': 'error', 'message': 'Recept niet gevonden'}), 404
    iso = date.today().isocalendar()
    qi = QuickAddItem(recipe_id=recipe.id,
                      people_count=body.get('people_count') or recipe.serves or 4,
                      year=iso[0], week_number=iso[1])
    db.session.add(qi)
    db.session.commit()
    return jsonify({'status': 'success', 'id': qi.id})


@bp.route('/api/boodschappen/extra/<int:id>', methods=['DELETE'])
def boodschappen_extra_delete(id):
    qi = QuickAddItem.query.get_or_404(id)
    db.session.delete(qi)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    return redirect(url_for('shopping.boodschappen'), code=301)


@bp.route('/api/shopping-list/<int:year>/<int:week>/clear', methods=['POST'])
def clear_shopping_list(year, week):
    try:
        _clear_shopping_list(week, year)
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


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
        return jsonify({'ok': True, 'qty': new_qty, 'is_default': True})

    if override:
        override.qty = new_qty
    else:
        db.session.add(ShoppingListOverride(
            year=year, week_number=week,
            ingredient_id=ingredient_id, qty=new_qty
        ))
    db.session.commit()
    return jsonify({'ok': True, 'qty': new_qty})


@bp.route('/api/shopping-list/<int:year>/<int:week>/item/<int:ingredient_id>/exclude',
           methods=['POST'])
def exclude_shopping_item(year, week, ingredient_id):
    existing = ShoppingListExclusion.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).first()
    if not existing:
        db.session.add(ShoppingListExclusion(
            year=year, week_number=week, ingredient_id=ingredient_id
        ))
        db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/api/shopping-list/<int:year>/<int:week>/add-item', methods=['POST'])
def add_shopping_item(year, week):
    data = request.get_json(force=True) or {}
    ingredient_id = data.get('ingredient_id')
    if not ingredient_id:
        return jsonify({'status': 'error', 'message': 'ingredient_id is verplicht'}), 400

    ing = Ingredient.query.get(ingredient_id)
    if not ing:
        return jsonify({'status': 'error', 'message': 'Ingrediënt niet gevonden'}), 404

    raw_amount = float(data.get('amount', 1))
    raw_unit = data.get('unit', 'stuks')
    unit, amount = _normalize_ri_unit(ing, raw_unit, raw_amount)

    ShoppingListExclusion.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).delete()

    existing = CustomShoppingIngredient.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
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
        'status': 'ok',
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


@bp.route('/api/shopping-list/<int:year>/<int:week>/send-to-ah', methods=['POST'])
def send_to_ah(year, week):
    _body = request.get_json(force=True) or {}
    qty_overrides = {int(k): v for k, v in _body.get('qty_overrides', {}).items()}
    payload, status, _sent = send_dict_to_ah(_build_shopping_dict(year, week), qty_overrides)
    return jsonify(payload), status
