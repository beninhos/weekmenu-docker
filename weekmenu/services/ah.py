import re
import time

from weekmenu.extensions import db
from weekmenu.models import Settings
from weekmenu.constants import (
    _AH_LOGIN_BASE, _AH_AUTHORIZE_PATH, _AH_ANON_TOKEN_URL,
    _AH_TOKEN_URL, _AH_REFRESH_URL, _AH_SEARCH_URL,
    _AH_SHOPPINGLIST_URL, _AH_HEADERS,
    _AH_CAPTCHA_SITEKEY, _AH_CAPTCHA_PAGE,
)


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
        json={'clientId': 'appie'},
        headers=_AH_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    _ah_setting('ah_anon_token', data['access_token'])
    _ah_setting('ah_anon_expires', str(int(time.time()) + data.get('expires_in', 604798)))
    return data['access_token']


def ah_get_access_token():
    """Return a valid user AH access token, auto-refreshing if needed."""
    import requests as _req
    token   = _ah_setting('ah_access_token')
    expires = _ah_setting('ah_token_expires')
    if token and expires and int(time.time()) < int(expires) - 60:
        return token
    refresh = _ah_setting('ah_refresh_token')
    if not refresh:
        return None
    try:
        resp = _req.post(
            _AH_REFRESH_URL,
            json={'clientId': 'appie', 'refreshToken': refresh},
            headers=_AH_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        _ah_setting('ah_access_token', data['access_token'])
        _ah_setting('ah_refresh_token', data.get('refresh_token', refresh))
        _ah_setting('ah_token_expires', str(int(time.time()) + data.get('expires_in', 604798)))
        return data['access_token']
    except Exception:
        return None


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
            price_raw = p.get('currentPrice') or p.get('priceBeforeBonus')
            bg_color = (
                p.get('highlight') or
                p.get('backgroundColor') or
                p.get('bgColor') or
                (images[0].get('backgroundColor') if images else None) or
                ''
            )
            products.append({
                'productId':  p.get('webshopId'),
                'title':      p.get('title', ''),
                'size':       p.get('salesUnitSize', ''),
                'price':      f"{price_raw:.2f}".replace('.', ',') if price_raw else '',
                'isBonus':    bool(p.get('isBonus') or p.get('discountLabels')),
                'image':      img_url,
                'bgColor':    bg_color,
            })
        return products
    except Exception:
        return []


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
        json={'clientId': 'appie', 'code': code},
        headers=_AH_HEADERS,
        timeout=10,
    )
    tok.raise_for_status()
    data = tok.json()
    expires_at = int(time.time()) + data.get('expires_in', 604798)
    return data['access_token'], data['refresh_token'], expires_at
