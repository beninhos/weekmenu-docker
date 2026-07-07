from flask import Blueprint, render_template, request, jsonify

from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, Recipe, ShoppingListOverride,
    ShoppingListExclusion, CustomShoppingIngredient,
)
from weekmenu.constants import (
    CATEGORY_ORDER_SUPERMARKET, CATEGORY_BG,
    _AH_HEADERS, _AH_SHOPPINGLIST_URL,
)
from weekmenu.services.shopping import _build_shopping_dict
from weekmenu.services.units import (
    _calc_ah_qty, _calc_multiplier, _norm_unit,
    format_amount, _normalize_ri_unit,
)
from weekmenu.services.ah import ah_get_access_token
from weekmenu.services.menu import clear_shopping_list as _clear_shopping_list

bp = Blueprint('shopping', __name__)


@bp.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    shopping_dict = _build_shopping_dict(year, week)

    # Tijdelijke quick-add items uit URL-parameters (sessie-only)
    recipe_ids = request.args.getlist('recipe_id')
    people_counts = request.args.getlist('people_count')
    for i, recipe_id in enumerate(recipe_ids):
        recipe = Recipe.query.get(recipe_id)
        if recipe:
            people_count = int(people_counts[i]) if i < len(people_counts) else None
            multiplier = _calc_multiplier(recipe.serves, people_count)
            for ri in recipe.ingredients:
                key = (ri.ingredient_id, _norm_unit(ri.unit))
                shopping_dict[key] = shopping_dict.get(key, 0) + ri.amount * multiplier

    overrides = {
        o.ingredient_id: o.qty
        for o in ShoppingListOverride.query.filter_by(year=year, week_number=week).all()
    }

    items = []
    for (ing_id, unit), total_amount in shopping_dict.items():
        ing = Ingredient.query.get(ing_id)
        if not ing:
            continue
        default_qty = _calc_ah_qty(ing, total_amount, unit)
        qty = overrides.get(ing_id, default_qty)
        api_color = ing.ah_product_color or ''
        items.append({
            'name':              ing.display,
            'amount':            total_amount,
            'amount_display':    format_amount(total_amount),
            'unit':              unit,
            'category':          ing.category,
            'ingredient_id':     ing_id,
            'ah_product_id':     ing.ah_product_id,
            'ah_product_name':   ing.ah_product_name,
            'ah_product_size':   ing.ah_product_size,
            'ah_product_image':  ing.ah_product_image,
            'ah_product_price':  ing.ah_product_price,
            'ah_product_bonus':  ing.ah_product_bonus or False,
            'ah_product_bg':     api_color or CATEGORY_BG.get(ing.category, '#f0ede8'),
            'default_qty':       default_qty,
            'qty':               qty,
        })

    category_order = {cat: i for i, cat in enumerate(CATEGORY_ORDER_SUPERMARKET)}
    items.sort(key=lambda x: (
        category_order.get(x['category'], 999),
        x['name']
    ))

    grouped = []
    for item in items:
        if not grouped or grouped[-1]['category'] != item['category']:
            grouped.append({'category': item['category'], 'producten': []})
        grouped[-1]['producten'].append(item)

    return render_template('shopping_list.html',
                         grouped_shopping_list=grouped,
                         week=week,
                         year=year)


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
    import requests as _req
    from collections import defaultdict
    from weekmenu.constants import _AH_ORDER_ACTIVE_URL, _AH_ORDER_ITEMS_URL

    access_token = ah_get_access_token()
    if not access_token:
        return jsonify({'status': 'error', 'message': 'Geen AH-account gekoppeld. Ga naar Instellingen.'}), 401

    shopping_dict = _build_shopping_dict(year, week)
    if not shopping_dict:
        return jsonify({'status': 'ok', 'sent': 0, 'not_linked': [], 'message': 'Boodschappenlijst is leeg'})

    _body = request.get_json(force=True) or {}
    qty_overrides = {int(k): v for k, v in _body.get('qty_overrides', {}).items()}

    headers = {**_AH_HEADERS, 'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}

    # Verzamel gekoppelde producten, samengevoegd per AH-productId
    # (de AH-API weigert dubbele productId's in één request).
    merged = defaultdict(int)
    name_by_pid = {}
    not_linked = []
    for (ing_id, unit), amount in shopping_dict.items():
        ing = Ingredient.query.get(ing_id)
        if not ing:
            continue
        if not ing.ah_product_id:
            not_linked.append(ing.display)
            continue
        qty = qty_overrides.get(ing_id, _calc_ah_qty(ing, amount, unit))
        merged[ing.ah_product_id] += max(int(qty or 1), 1)
        name_by_pid.setdefault(ing.ah_product_id, ing.display)

    if not merged:
        return jsonify({
            'status': 'ok', 'sent': 0, 'not_linked': not_linked,
            'message': 'Geen gekoppelde AH-producten in de lijst. Koppel ze eerst via AH-producten.',
        })

    # Order-mode detecteren: bij een actieve bestelling weigert de
    # boodschappenlijst (412 "Server in order mode") en moeten items
    # naar de order zelf — met de Appie-Current-Order-Id header.
    order_id = None
    try:
        r = _req.get(_AH_ORDER_ACTIVE_URL, headers=headers, timeout=10)
        if r.status_code == 200:
            order_id = (r.json() or {}).get('id')
    except Exception:
        pass

    try:
        if order_id:
            items = [{'productId': pid, 'quantity': qty, 'originCode': 'PRD',
                      'description': '', 'strikethrough': False}
                     for pid, qty in merged.items()]
            resp = _req.put(
                _AH_ORDER_ITEMS_URL,
                json={'items': items},
                headers={**headers, 'Appie-Current-Order-Id': str(order_id)},
                timeout=20,
            )
            target = 'bestelling'
        else:
            items = [{'originCode': 'PRD', 'productId': pid,
                      'quantity': qty, 'type': 'SHOPPABLE',
                      'description': name_by_pid.get(pid, ''),
                      'searchTerm': name_by_pid.get(pid, ''),
                      'strikeThrough': False}
                     for pid, qty in merged.items()]
            resp = _req.patch(
                _AH_SHOPPINGLIST_URL, json={'items': items},
                headers=headers, timeout=20,
            )
            target = 'boodschappenlijst'
        resp.raise_for_status()
    except Exception as e:
        from flask import current_app
        current_app.logger.warning('AH send mislukt: %r', e)
        return jsonify({
            'status': 'error', 'sent': 0, 'not_linked': not_linked,
            'message': f'Versturen naar AH mislukt: {e}',
        }), 502

    sent = len(merged)
    msg = f'{sent} product{"en" if sent != 1 else ""} toegevoegd aan je AH-{target}'
    if not_linked:
        msg += f'. {len(not_linked)} nog niet gekoppeld (overgeslagen): {", ".join(not_linked[:5])}'
    return jsonify({'status': 'ok', 'sent': sent, 'not_linked': not_linked, 'message': msg})
