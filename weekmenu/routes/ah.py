import json as _json
import os
import time

from flask import Blueprint, request, jsonify, render_template

from weekmenu.extensions import db
from weekmenu.models import Ingredient, Settings
from weekmenu.constants import _AH_TOKEN_URL, _AH_HEADERS, _AH_CLIENT_ID
from weekmenu.services.ah import (
    _ah_setting, ah_get_access_token, ah_search_products,
    ah_login_with_password, ah_price_advice,
)
from weekmenu.services.units import _parse_product_size, _calc_ah_qty

bp = Blueprint('ah', __name__)


@bp.route('/api/ah/connect', methods=['POST'])
def ah_connect():
    import requests as _req
    from weekmenu.services.ah import _ah_extract_code
    raw = (request.json or {}).get('code', '').strip()
    code = _ah_extract_code(raw)
    if not code:
        return jsonify({'status': 'error', 'message': 'Geen code opgegeven'}), 400
    try:
        resp = _req.post(
            _AH_TOKEN_URL,
            json={'clientId': _AH_CLIENT_ID, 'code': code},
            headers=_AH_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _ah_setting('ah_access_token', data['access_token'])
        _ah_setting('ah_refresh_token', data['refresh_token'])
        expires_at = int(time.time()) + data.get('expires_in', 604798)
        _ah_setting('ah_token_expires', str(expires_at))
        return jsonify({'status': 'ok', 'expires_at': expires_at})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Koppelen mislukt: {e}'}), 400


@bp.route('/api/ah/status')
def ah_status():
    refresh = _ah_setting('ah_refresh_token')
    expires = _ah_setting('ah_token_expires')
    connected = bool(refresh)
    expires_ts = int(expires) if expires else None
    return jsonify({
        'connected': connected,
        'expires_at': expires_ts,
        'expired': connected and expires_ts is not None and int(time.time()) > expires_ts,
    })


@bp.route('/api/ah/disconnect', methods=['POST'])
def ah_disconnect():
    for key in ('ah_access_token', 'ah_refresh_token', 'ah_token_expires'):
        s = Settings.query.filter_by(key=key).first()
        if s:
            db.session.delete(s)
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/api/ah/start-login', methods=['POST'])
def ah_start_login():
    token_file = '/tmp/appie-tokens.json'
    if os.path.exists(token_file):
        os.remove(token_file)
    return jsonify({'ok': True})


@bp.route('/api/ah/poll-token')
def ah_poll_token():
    token_file = '/tmp/appie-tokens.json'
    if not os.path.exists(token_file):
        return jsonify({'ready': False})
    try:
        with open(token_file) as f:
            data = _json.load(f)
        access = data.get('access_token', '')
        refresh = data.get('refresh_token', '')
        expires = data.get('expires_at', int(time.time()) + 604798)
        if not access or not refresh:
            return jsonify({'ready': False})
        _ah_setting('ah_access_token', access)
        _ah_setting('ah_refresh_token', refresh)
        _ah_setting('ah_token_expires', str(expires))
        os.remove(token_file)
        return jsonify({'ready': True})
    except Exception as e:
        return jsonify({'ready': False, 'error': str(e)})


@bp.route('/api/ah/login-password', methods=['POST'])
def ah_login_password():
    data = request.json or {}
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    capsolver_key = data.get('capsolver_key', '').strip()
    if not email or not password:
        return jsonify({'status': 'error', 'message': 'E-mail en wachtwoord zijn verplicht'}), 400
    if capsolver_key:
        _ah_setting('capsolver_key', capsolver_key)
    try:
        access, refresh, expires = ah_login_with_password(email, password, capsolver_key or None)
        _ah_setting('ah_access_token', access)
        _ah_setting('ah_refresh_token', refresh)
        _ah_setting('ah_token_expires', str(expires))
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 401


@bp.route('/api/ah/verify')
def ah_verify():
    import requests as _req
    from weekmenu.constants import _AH_GRAPHQL_URL
    token = ah_get_access_token()
    if not token:
        return jsonify({'ok': False, 'reason': 'Geen token opgeslagen'})
    # AH heeft member-info verplaatst van de REST-route
    # (mobile-services/v1/member/profile → 404) naar GraphQL.
    query = (
        'query FetchMember { member { id emailAddress '
        'name { first last } } }'
    )
    try:
        r = _req.post(
            _AH_GRAPHQL_URL,
            json={'query': query},
            headers={**_AH_HEADERS, 'Authorization': f'Bearer {token}'},
            timeout=8,
        )
        if r.status_code != 200:
            return jsonify({'ok': False, 'reason': f'HTTP {r.status_code}'})
        body = r.json()
        if body.get('errors'):
            msg = body['errors'][0].get('message', 'GraphQL-fout')
            return jsonify({'ok': False, 'reason': msg})
        member = (body.get('data') or {}).get('member') or {}
        if not member.get('emailAddress'):
            return jsonify({'ok': False, 'reason': 'Niet ingelogd (anoniem token)'})
        name = (member.get('name') or {}).get('first') or ''
        return jsonify({'ok': True, 'name': name})
    except Exception as e:
        return jsonify({'ok': False, 'reason': str(e)})


@bp.route('/api/ah/product-search')
def ah_product_search():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify([])
    size = min(int(request.args.get('size', 8)), 20)
    return jsonify(ah_search_products(q, size=size))


@bp.route('/api/ah/advice')
def ah_advice():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'cheapest': None, 'mid': None, 'organic': None,
                        'unit': '', 'products': []})
    return jsonify(ah_price_advice(q))


# ── AH winkelmand (order-commandocentrum) ────────────────────────────────

@bp.route('/ah-winkelmand')
def ah_winkelmand():
    import datetime
    iso = datetime.date.today().isocalendar()
    return render_template('ah_winkelmand.html', year=iso[0], week=iso[1])


@bp.route('/api/ah/orders')
def ah_orders():
    from weekmenu.services.ah import ah_list_orders
    return jsonify(ah_list_orders())


@bp.route('/api/ah/order/<int:order_id>')
def ah_order_detail(order_id):
    from weekmenu.services.ah import ah_get_order
    from weekmenu.services.shopping import _build_shopping_dict
    order = ah_get_order(order_id)
    if order is None:
        return jsonify({'error': 'Order niet bereikbaar'}), 502

    needed, unlinked = [], []
    week = request.args.get('week', type=int)
    year = request.args.get('year', type=int)
    if week and year:
        in_order = set(order['productIds'])
        seen = set()
        for (ing_id, unit), amount in _build_shopping_dict(year, week).items():
            ing = Ingredient.query.get(ing_id)
            if not ing:
                continue
            if not ing.ah_product_id:
                if ing.display not in unlinked:
                    unlinked.append(ing.display)
                continue
            if ing.ah_product_id in in_order or ing.ah_product_id in seen:
                continue
            seen.add(ing.ah_product_id)
            needed.append({
                'ingredientId': ing.id,
                'productId':    ing.ah_product_id,
                'name':         ing.display,
                'productName':  ing.ah_product_name or '',
                'size':         ing.ah_product_size or '',
                'price':        ing.ah_product_price or '',
                'image':        ing.ah_product_image or '',
                'isBonus':      ing.ah_product_bonus or False,
                'qty':          _calc_ah_qty(ing, amount, unit),
            })
    return jsonify({'order': order, 'needed': needed, 'unlinked': unlinked,
                    'week': week, 'year': year})


# Toevoegen aan een door de gebruiker geopende order. De app opent of zet
# zelf nooit een order door — dat doet de gebruiker in de AH-app.
_AH_ORDER_WRITE_ENABLED = True


@bp.route('/api/ah/order/<int:order_id>/apply', methods=['POST'])
def ah_order_apply(order_id):
    from weekmenu.services.ah import ah_add_to_open_order, ah_get_order
    if not _AH_ORDER_WRITE_ENABLED:
        return jsonify({'status': 'error',
                        'message': 'Bewerken van bestellingen staat uit.'}), 403
    data = request.get_json(force=True) or {}
    items = data.get('items', [])
    if not items:
        return jsonify({'status': 'error', 'message': 'Geen wijzigingen opgegeven'}), 400
    try:
        ah_add_to_open_order(order_id, items)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 502
    return jsonify({'status': 'ok', 'order': ah_get_order(order_id)})


@bp.route('/api/ah/ingredient/<int:ingredient_id>/link', methods=['POST'])
def ah_link_ingredient(ingredient_id):
    data = request.json or {}
    ing = Ingredient.query.get_or_404(ingredient_id)
    old_product_id = ing.ah_product_id
    ing.ah_product_id = data.get('productId')
    ing.ah_product_name = data.get('title', '')
    ing.ah_product_size = data.get('size', '')
    ing.ah_product_price = data.get('price', '')
    ing.ah_product_image = data.get('image', '')
    ing.ah_product_bonus = bool(data.get('isBonus', False))
    ing.ah_product_color = data.get('bgColor', '')
    ing.ah_product_was_price = data.get('wasPrice', '')
    ing.ah_product_bonus_mechanism = data.get('bonusMechanism', '')
    ing.ah_product_brand = data.get('brand', '')
    ing.ah_product_category = data.get('category', '')
    ing.ah_product_updated = int(time.time())
    parsed = _parse_product_size(data.get('size', ''))
    if parsed:
        ing.ah_pkg_qty, ing.ah_pkg_unit = parsed
    else:
        ing.ah_pkg_qty = None
        ing.ah_pkg_unit = None
    if ing.ah_product_id != old_product_id:
        ing.ah_conv_factor = None
        ing.ah_conv_unit = None
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/api/ah/ingredient/<int:ingredient_id>/refresh', methods=['POST'])
def ah_refresh_ingredient(ingredient_id):
    ing = Ingredient.query.get_or_404(ingredient_id)
    if not ing.ah_product_id:
        return jsonify({'status': 'error', 'message': 'Geen product gekoppeld'}), 400
    products = ah_search_products(ing.name, size=1)
    if not products:
        return jsonify({'status': 'error', 'message': 'Geen resultaten'}), 404
    p = products[0]
    ing.ah_product_name = p['title']
    ing.ah_product_size = p['size']
    ing.ah_product_price = p['price']
    ing.ah_product_image = p['image']
    ing.ah_product_bonus = p['isBonus']
    ing.ah_product_was_price = p.get('wasPrice', '')
    ing.ah_product_bonus_mechanism = p.get('bonusMechanism', '')
    ing.ah_product_brand = p.get('brand', '')
    ing.ah_product_category = p.get('category', '')
    ing.ah_product_updated = int(time.time())
    parsed = _parse_product_size(p['size'])
    if parsed:
        ing.ah_pkg_qty, ing.ah_pkg_unit = parsed
    db.session.commit()
    return jsonify({'status': 'ok', 'product': p})


@bp.route('/api/ah/ingredient/<int:ingredient_id>/pkg-config', methods=['POST'])
def ah_pkg_config(ingredient_id):
    data = request.get_json(force=True) or {}
    ing = Ingredient.query.get_or_404(ingredient_id)
    ing.ah_pkg_qty = data.get('ah_pkg_qty') or None
    ing.ah_pkg_unit = data.get('ah_pkg_unit') or None
    ing.ah_conv_factor = data.get('ah_conv_factor') or None
    ing.ah_conv_unit = data.get('ah_conv_unit') or None
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/ah-producten')
def ah_products():
    ingredients = Ingredient.query.order_by(Ingredient.name).all()
    return render_template('ah_products.html', ingredients=ingredients)
