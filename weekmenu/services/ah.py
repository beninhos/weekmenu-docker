import re
import time
import threading
from collections import Counter

from weekmenu.extensions import db
from weekmenu.models import Settings
from weekmenu.services.units import _parse_product_size, price_per_unit
from weekmenu.constants import (
    _AH_LOGIN_BASE, _AH_AUTHORIZE_PATH, _AH_ANON_TOKEN_URL,
    _AH_TOKEN_URL, _AH_REFRESH_URL, _AH_SEARCH_URL,
    _AH_SHOPPINGLIST_URL, _AH_HEADERS,
    _AH_CAPTCHA_SITEKEY, _AH_CAPTCHA_PAGE,
    _AH_CLIENT_ID,
)


_ORGANIC_RE = re.compile(r'biologisch|\bbio\b|\beko\b', re.IGNORECASE)


def _is_organic(*texts):
    """True als merk/titel op een biologisch product wijst."""
    return bool(_ORGANIC_RE.search(' '.join(t for t in texts if t)))


def _ah_setting(key, value=None):
    """Get or set a Settings value by key."""
    s = Settings.query.filter_by(key=key).first()
    if value is None:
        return s.value if s else None
    if s:
        s.value = value
    else:
        db.session.add(Settings(key=key, value=value))
    db.session.commit()


def _ah_get_anon_token(force=False):
    """Return a valid anonymous AH access token (for product search)."""
    import requests as _req
    token   = _ah_setting('ah_anon_token')
    expires = _ah_setting('ah_anon_expires')
    if not force and token and expires and int(time.time()) < int(expires) - 60:
        return token
    resp = _req.post(
        _AH_ANON_TOKEN_URL,
        json={'clientId': _AH_CLIENT_ID},
        headers=_AH_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _ah_setting('ah_anon_token', data['access_token'])
    _ah_setting('ah_anon_expires', str(int(time.time()) + data.get('expires_in', 604798)))
    return data['access_token']


# Deel D — token-vangrails. Serialiseer de refresh zodat nooit twee requests
# tegelijk het roterende AH-refresh-token verbranden. De app draait als single
# process (Flask dev-server, threaded), dus een in-process Lock volstaat.
# LET OP: bij meerdere workers (Gunicorn/Uvicorn) spant een in-memory lock niet
# over processen → gebruik dan een DB-guard (SQLite BEGIN IMMEDIATE / een
# ah_refreshing-rij met timestamp).
_refresh_lock = threading.Lock()


def _ah_set_tokens(access, refresh, expires_at):
    """Sla access/refresh/expires atomisch op (één commit), zodat een geroteerd
    refresh-token nooit half/niet wordt weggeschreven."""
    values = {
        'ah_access_token':  access,
        'ah_refresh_token': refresh,
        'ah_token_expires': str(expires_at),
    }
    for key, val in values.items():
        s = Settings.query.filter_by(key=key).first()
        if s:
            s.value = val
        else:
            db.session.add(Settings(key=key, value=val))
    db.session.commit()


def _ah_clear_tokens():
    """Wis de AH-tokens → status valt terug op 'niet verbonden'."""
    for key in ('ah_access_token', 'ah_refresh_token', 'ah_token_expires'):
        s = Settings.query.filter_by(key=key).first()
        if s:
            db.session.delete(s)
    db.session.commit()


def _ah_valid_access_token():
    """Het opgeslagen access-token als het nog ruim geldig is, anders None."""
    token = _ah_setting('ah_access_token')
    expires = _ah_setting('ah_token_expires')
    if token and expires and int(time.time()) < int(expires) - 60:
        return token
    return None


def ah_get_access_token():
    """Geef een geldig user-AH-access-token; ververst atomisch indien nodig."""
    import requests as _req
    from flask import current_app

    # Snel pad: nog geldig token → geen lock nodig.
    valid = _ah_valid_access_token()
    if valid:
        return valid
    if not _ah_setting('ah_refresh_token'):
        return None

    # Serialiseer: maar één thread vernieuwt tegelijk (anders rotatie-race).
    with _refresh_lock:
        # Een andere thread kan net ververst hebben terwijl we wachtten.
        valid = _ah_valid_access_token()
        if valid:
            return valid
        refresh = _ah_setting('ah_refresh_token')
        if not refresh:
            return None
        try:
            resp = _req.post(
                _AH_REFRESH_URL,
                json={'clientId': _AH_CLIENT_ID, 'refreshToken': refresh},
                headers=_AH_HEADERS,
                timeout=10,
            )
        except Exception as e:
            current_app.logger.warning('AH refresh exception: %r', e)
            return None
        if resp.status_code != 200:
            current_app.logger.warning('AH refresh failed: status=%s body=%s',
                                       resp.status_code, resp.text[:300])
            if resp.status_code in (400, 401, 403):
                _ah_clear_tokens()  # token ongeldig → niet verbonden
            return None
        data = resp.json()
        # Sla het (mogelijk geroteerde) refresh-token direct + atomisch op.
        _ah_set_tokens(
            data['access_token'],
            data.get('refresh_token', refresh),
            int(time.time()) + data.get('expires_in', 604798),
        )
        return data['access_token']


def ah_search_products(query, size=8):
    """Search AH product catalog. Returns list of product dicts."""
    import requests as _req

    def _do_search(token):
        headers = {**_AH_HEADERS, 'Authorization': f'Bearer {token}'}
        return _req.get(
            _AH_SEARCH_URL,
            params={'query': query, 'size': size},
            headers=headers,
            timeout=10,
        )

    try:
        token = _ah_get_anon_token()
        resp = _do_search(token)
        if resp.status_code == 401:
            token = _ah_get_anon_token(force=True)
            resp = _do_search(token)
        resp.raise_for_status()
        products = []
        for p in resp.json().get('products', []):
            images = p.get('images') or []
            img_url = next((i['url'] for i in images if i.get('width') == 200), '')
            if not img_url and images:
                img_url = images[0].get('url', '')
            cur_raw = p.get('currentPrice')
            was_raw = p.get('priceBeforeBonus')
            price_raw = cur_raw or was_raw
            # Was-prijs alleen tonen bij een echte afprijzing.
            show_was = bool(was_raw and cur_raw and was_raw > cur_raw)
            size_str = p.get('salesUnitSize', '')
            pu = price_per_unit(price_raw, size_str)
            unit_price = round(pu[0], 4) if pu else None
            unit_price_unit = pu[1] if pu else ''
            unit_price_label = (
                f"€{pu[0]:.2f}/{unit_price_unit}".replace('.', ',') if pu else ''
            )
            bg_color = (
                p.get('highlight') or
                p.get('backgroundColor') or
                p.get('bgColor') or
                (images[0].get('backgroundColor') if images else None) or
                ''
            )
            products.append({
                'productId':      p.get('webshopId'),
                'title':          p.get('title', ''),
                'size':           p.get('salesUnitSize', ''),
                'price':          f"{price_raw:.2f}".replace('.', ',') if price_raw else '',
                'wasPrice':       f"{was_raw:.2f}".replace('.', ',') if show_was else '',
                'isBonus':        bool(p.get('isBonus') or p.get('discountLabels')),
                'bonusMechanism': p.get('bonusMechanism', '') or '',
                'brand':          p.get('brand', '') or '',
                'category':       p.get('mainCategory', '') or '',
                'unitPrice':      unit_price,
                'unitPriceUnit':  unit_price_unit,
                'unitPriceLabel': unit_price_label,
                'isOrganic':      _is_organic(p.get('title', ''), p.get('brand', '')),
                'image':          img_url,
                'bgColor':        bg_color,
            })
        return products
    except Exception:
        return []


def ah_price_advice(query, size=25):
    """Drie keuzes voor één ingrediënt: goedkoopst, tussenin, biologisch.

    Vergelijkt alleen producten met dezelfde (meest voorkomende) eenheid,
    zodat €/kg niet tegen €/stuk wordt afgezet. Geeft ook de volledige
    lijst terug, comparabele producten eerst en op €/eenheid gesorteerd.
    """
    products = ah_search_products(query, size=size)
    result = {'cheapest': None, 'mid': None, 'organic': None,
              'unit': '', 'products': products}

    comparable = [p for p in products if p.get('unitPrice')]
    if not comparable:
        return result

    unit = Counter(p['unitPriceUnit'] for p in comparable).most_common(1)[0][0]
    pool = sorted((p for p in comparable if p['unitPriceUnit'] == unit),
                  key=lambda p: p['unitPrice'])
    result['unit'] = unit

    cheapest = pool[0]
    organic = next((p for p in pool if p.get('isOrganic')), None)
    # "Tussenin": mediaan van de niet-biologische opties, zonder de
    # goedkoopste — zo is het een zinnige middenkeuze en nooit duurder
    # gepresenteerd dan nodig of identiek aan goedkoopst/bio.
    mid_candidates = [p for p in pool if not p.get('isOrganic') and p is not cheapest]
    mid = mid_candidates[len(mid_candidates) // 2] if mid_candidates else None

    result['cheapest'] = cheapest
    result['mid'] = mid
    result['organic'] = organic
    result['products'] = pool + [p for p in products if p not in pool]
    return result


_AH_FULFILLMENTS_QUERY = (
    'query OrderFulfillments { orderFulfillments(status: OPEN) { result { '
    'orderId shoppingType modifiable totalPrice { totalPrice { amount } } '
    'delivery { method slot { date dateDisplay timeDisplay startTime endTime } } } } }'
)


def ah_list_orders():
    """Open (geplande) AH-orders, gesorteerd op bezorgdatum."""
    import requests as _req
    from weekmenu.constants import _AH_GRAPHQL_URL
    token = ah_get_access_token()
    if not token:
        return []
    try:
        resp = _req.post(
            _AH_GRAPHQL_URL,
            json={'query': _AH_FULFILLMENTS_QUERY},
            headers={**_AH_HEADERS, 'Authorization': f'Bearer {token}'},
            timeout=10,
        )
        resp.raise_for_status()
        result = (((resp.json() or {}).get('data') or {}).get('orderFulfillments') or {}).get('result') or []
    except Exception:
        return []
    orders = []
    for o in result:
        slot = (o.get('delivery') or {}).get('slot') or {}
        orders.append({
            'orderId':     o.get('orderId'),
            'shoppingType': o.get('shoppingType', ''),
            'method':      (o.get('delivery') or {}).get('method', ''),
            'modifiable':  bool(o.get('modifiable')),
            'date':        slot.get('date', ''),
            'dateDisplay': slot.get('dateDisplay', ''),
            'timeDisplay': slot.get('timeDisplay', ''),
            'total':       (((o.get('totalPrice') or {}).get('totalPrice') or {}).get('amount')) or 0,
        })
    orders.sort(key=lambda x: x['date'] or '')
    return orders


def ah_get_order(order_id):
    """Inhoud van één order, gegroepeerd per schap, met totaal en bonusvoordeel."""
    import requests as _req
    token = ah_get_access_token()
    if not token:
        return None
    url = f'https://api.ah.nl/mobile-services/order/v1/{int(order_id)}/details-grouped-by-taxonomy'
    try:
        resp = _req.get(
            url,
            headers={**_AH_HEADERS, 'Authorization': f'Bearer {token}'},
            timeout=12,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    groups, total, savings, count = [], 0.0, 0.0, 0
    product_ids = set()
    for g in data.get('groupedProductsInTaxonomy', []):
        items = []
        for op in g.get('orderedProducts', []):
            p = op.get('product') or {}
            qty = op.get('quantity') or op.get('amount') or 1
            was = p.get('priceBeforeBonus') or 0
            cur = p.get('currentPrice', was) or was
            pid = p.get('webshopId')
            if pid:
                product_ids.add(pid)
            images = p.get('images') or []
            img = next((i['url'] for i in images if i.get('width') == 200), '')
            if not img and images:
                img = images[0].get('url', '')
            total += cur * qty
            savings += max(was - cur, 0) * qty
            count += qty
            items.append({
                'productId':  pid,
                'title':      p.get('title', ''),
                'brand':      p.get('brand', ''),
                'size':       p.get('salesUnitSize', ''),
                'quantity':   qty,
                'price':      round(cur, 2),
                'wasPrice':   round(was, 2) if was > cur else None,
                'isBonus':    bool(p.get('isBonus')),
                'image':      img,
            })
        if items:
            groups.append({'taxonomy': g.get('taxonomyName', 'Overig'), 'items': items})

    dtp = data.get('deliveryTimePeriod') or {}
    return {
        'orderId':       data.get('orderId'),
        'orderState':    data.get('orderState', ''),
        'editable':      data.get('orderState') in ('REOPENED', 'UNCONFIRMED', 'OPEN'),
        'deliveryDate':  data.get('deliveryDate', ''),
        'closingTime':   data.get('closingTime', ''),
        'startDateTime': dtp.get('startDateTime', ''),
        'endDateTime':   dtp.get('endDateTime', ''),
        'modifiable':    bool(data.get('reopenable') or data.get('cancellable')),
        'groups':        groups,
        'productIds':    sorted(product_ids),
        'total':         round(total, 2),
        'savings':       round(savings, 2),
        'itemCount':     count,
    }


_AH_REOPEN_MUTATION = 'mutation OrderReopen($id: Int!){ orderReopen(id: $id){ status errorMessage } }'
_AH_REVERT_MUTATION = 'mutation OrderRevert($id: Int!){ orderRevert(id: $id){ status errorMessage } }'


def _ah_graphql(token, query, variables=None):
    import requests as _req
    from weekmenu.constants import _AH_GRAPHQL_URL
    resp = _req.post(
        _AH_GRAPHQL_URL,
        json={'query': query, 'variables': variables or {}},
        headers={**_AH_HEADERS, 'Authorization': f'Bearer {token}',
                 'Content-Type': 'application/json'},
        timeout=12,
    )
    resp.raise_for_status()
    return resp.json()


_AH_RECIPE_QUERY = '''query($id: Int!) {
  recipe(id: $id) {
    id
    title
    description
    cookTime
    servings { number type }
    ingredients { name { singular plural } quantity quantityUnit { singular plural } }
    preparation { steps }
    images { url width }
  }
}'''


def ah_get_recipe(recipe_id):
    """Haal een Allerhande-recept op via de AH GraphQL API (anoniem token, geen login).

    Omzeilt de Akamai bot-detectie die het scrapen van ah.nl-receptpagina's blokkeert.
    Geeft de ruwe recipe-dict terug, of None bij een fout.
    """
    from flask import current_app
    try:
        token = _ah_get_anon_token()
    except Exception as e:
        current_app.logger.warning('AH recipe: anon token mislukt: %r', e)
        return None
    try:
        data = _ah_graphql(token, _AH_RECIPE_QUERY, {'id': int(recipe_id)})
    except Exception as e:
        current_app.logger.warning('AH recipe: GraphQL request mislukt: %r', e)
        return None
    if data.get('errors'):
        current_app.logger.warning('AH recipe: GraphQL errors: %s', data['errors'])
    return (data.get('data') or {}).get('recipe')


def _ah_mutation_status(resp_json, field):
    return (((resp_json.get('data') or {}).get(field)) or {}).get('status')


def ah_add_to_open_order(order_id, items):
    """Voeg/wijzig items in een REEDS DOOR DE GEBRUIKER GEOPENDE order.

    Doet bewust GEEN reopen en GEEN submit — een doorgezette order openen of
    een gewijzigde order definitief maken doet de gebruiker zelf in de AH-app
    (daar handelt AH ook niet-beschikbare producten / alternatieven af).

    Werkt alleen als de order open/bewerkbaar is; bij een doorgezette
    (CONFIRMED) order geeft AH 412 → nette melding. items=[{productId,
    quantity}] met absolute hoeveelheden; 0 = verwijderen.
    """
    import requests as _req
    from weekmenu.constants import _AH_ORDER_ITEMS_URL
    token = ah_get_access_token()
    if not token:
        raise ValueError('Geen AH-account gekoppeld')
    payload = [{'productId': int(it['productId']), 'quantity': int(it['quantity']),
                'originCode': 'PRD', 'description': '', 'strikethrough': False}
               for it in items if it.get('productId') is not None]
    if not payload:
        return

    oid = int(order_id)
    resp = _req.put(
        _AH_ORDER_ITEMS_URL,
        json={'items': payload},
        headers={**_AH_HEADERS, 'Authorization': f'Bearer {token}',
                 'Content-Type': 'application/json',
                 'Appie-Current-Order-Id': str(oid)},
        timeout=20,
    )
    if resp.status_code == 412:
        raise ValueError('Deze bestelling is doorgezet. Open hem eerst zelf in '
                         'de AH-app, dan kun je hier items toevoegen.')
    resp.raise_for_status()


def _ah_extract_code(raw):
    """Haal de OAuth-code op uit een volledige URL of losse code."""
    raw = raw.strip()
    m = re.search(r'[?&]code=([^&\s]+)', raw)
    return m.group(1) if m else raw


def _solve_hcaptcha_capsolver(api_key):
    """Los de invisible hCaptcha op via Capsolver."""
    import requests as _req
    create = _req.post(
        'https://api.capsolver.com/createTask',
        json={
            'clientKey': api_key,
            'task': {
                'type': 'HCaptchaTaskProxyless',
                'websiteURL': _AH_CAPTCHA_PAGE,
                'websiteKey': _AH_CAPTCHA_SITEKEY,
                'isInvisible': True,
            },
        },
        timeout=10,
    ).json()
    if create.get('errorId'):
        raise ValueError(f'Capsolver fout: {create.get("errorDescription", create)}')
    task_id = create['taskId']

    for _ in range(30):
        time.sleep(3)
        result = _req.post(
            'https://api.capsolver.com/getTaskResult',
            json={'clientKey': api_key, 'taskId': task_id},
            timeout=10,
        ).json()
        if result.get('status') == 'ready':
            return result['solution']['gRecaptchaResponse']
        if result.get('status') == 'failed':
            raise ValueError(f'Capsolver: captcha mislukt — {result}')
    raise TimeoutError('Capsolver: timeout bij oplossen captcha')


def ah_login_with_password(email, password, capsolver_key=None):
    """Voert de volledige AH OAuth-flow server-side uit via curl_cffi."""
    from curl_cffi import requests as cffi_req
    import requests as _req

    key = capsolver_key or _ah_setting('capsolver_key') or ''
    if not key:
        raise ValueError(
            'Een Capsolver API-key is vereist. '
            'Maak gratis een account aan op capsolver.com en voer de key in bij instellingen.'
        )

    captcha_token = _solve_hcaptcha_capsolver(key)

    sess = cffi_req.Session(impersonate='chrome120')
    hdrs = {
        'Accept-Language': 'nl-NL,nl;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    r1 = sess.get(
        _AH_LOGIN_BASE + _AH_AUTHORIZE_PATH,
        headers=hdrs,
        allow_redirects=True,
        timeout=15,
    )

    r2 = sess.post(
        _AH_LOGIN_BASE + '/login/api/login',
        json={
            'username':          email,
            'password':          password,
            'h-captcha-response': captcha_token,
        },
        headers={
            **hdrs,
            'Content-Type': 'application/json',
            'Origin':        _AH_LOGIN_BASE,
            'Referer':       r1.url or (_AH_LOGIN_BASE + '/login'),
        },
        allow_redirects=False,
        timeout=15,
    )

    location = r2.headers.get('Location', '')
    if not location:
        body = r2.text[:200]
        raise ValueError(f'Inloggen mislukt — {body}')

    for _ in range(10):
        if 'appie://login-exit' in location:
            break
        if not location or not location.startswith('http'):
            break
        r = sess.get(location, headers=hdrs, allow_redirects=False, timeout=15)
        location = r.headers.get('Location', '')

    code = _ah_extract_code(location)
    if not code or code == location:
        raise ValueError(
            f'Inloggen mislukt — geen OAuth-code ontvangen. '
            f'Controleer e-mail en wachtwoord. (laatste redirect: {location!r:.120})'
        )

    tok = _req.post(
        _AH_TOKEN_URL,
        json={'clientId': _AH_CLIENT_ID, 'code': code},
        headers=_AH_HEADERS,
        timeout=10,
    )
    tok.raise_for_status()
    data = tok.json()
    expires_at = int(time.time()) + data.get('expires_in', 604798)
    return data['access_token'], data['refresh_token'], expires_at
