"""AH login reverse-proxy met browser-fingerprint (curl_cffi).

Vervangt de Go-proxy: AH's WAF (Akamai) blokkeert een Go-client (403), maar
laat curl_cffi met Chrome-fingerprint door. De gebruiker logt via deze proxy
in op login.ah.nl — echte invisible hCaptcha, eigen residential IP, dus een
geldige captcha-score. appie://login-exit wordt onderschept op /callback, de
OAuth-code ingewisseld voor tokens en weggeschreven naar /tmp/appie-tokens.json
(de Flask-app pollt dat bestand via /api/ah/poll-token).
"""
import json
import os
import time
from urllib.parse import urlparse

import requests as rq
from curl_cffi import requests as cf
from flask import Flask, request, Response, redirect

LOGIN_BASE   = 'https://login.ah.nl'
TOKEN_URL    = 'https://api.ah.nl/mobile-auth/v1/auth/token'
CLIENT_ID    = 'appie-ios'
TOKEN_FILE   = '/tmp/appie-tokens.json'
IMPERSONATE  = 'chrome120'
APPIE_UA     = 'Appie/9.28 (iPhone17,3; iPhone; CPU OS 26_1 like Mac OS X)'

# Deel A — origin-preserving HTTPS. Is er een TLS-cert (cert.pem/key.pem), dan
# draaien we op :443 met origin **https://login.ah.nl**. De laptop wijst
# login.ah.nl via /etc/hosts naar de SSH-tunnel → de browser-stack ziet de
# echte origin, dus hCaptcha (sitekey-lock) én passkey (WebAuthn-origin) werken.
# Zonder cert: HTTP op :9002 met localhost-origin (fallback/oude gedrag).
# LET OP: alleen de LAPTOP-/etc/hosts wijst naar de tunnel; de server/container
# resolvet login.ah.nl normaal, zodat de upstream curl_cffi de échte AH bereikt
# (geen proxy-loop).
CERT_FILE = os.environ.get('AH_PROXY_CERT', os.path.join(os.path.dirname(__file__), 'cert.pem'))
KEY_FILE  = os.environ.get('AH_PROXY_KEY',  os.path.join(os.path.dirname(__file__), 'key.pem'))
HTTPS = os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE)
if HTTPS:
    LISTEN_PORT  = 443
    LOCAL_ORIGIN = 'https://login.ah.nl'
else:
    LISTEN_PORT  = 9002
    LOCAL_ORIGIN = 'http://localhost:9002'

# Begin de OAuth-flow bij de authorize-endpoint (zet sessie op, redirect naar /login).
OAUTH_START = ('/secure/oauth/authorize?client_id=appie'
               '&redirect_uri=appie%3A%2F%2Flogin-exit&response_type=code')

# Headers die we niet 1-op-1 mogen doorgeven aan de browser.
_HOP = {
    'content-encoding', 'content-length', 'transfer-encoding', 'connection',
    'keep-alive', 'content-security-policy', 'content-security-policy-report-only',
    'strict-transport-security', 'x-frame-options', 'report-to', 'nel', 'alt-svc',
}
# Alleen deze request-headers geven we door; al het andere (User-Agent, Accept,
# sec-ch-ua, sec-fetch-*, …) laat curl_cffi zetten zodat de Chrome-fingerprint
# klopt — anders blokkeert AH's WAF (403). Cookies/CSRF/inhoud gaan wél mee.
_FWD_EXACT = {'cookie', 'content-type', 'referer', 'origin', 'authorization', 'x-requested-with'}
_TEXT = ('text/html', 'javascript', 'json', 'text/css', 'application/xml', 'text/plain')

app = Flask(__name__)

_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;
height:100vh;margin:0;background:{bg};}}.card{{background:#fff;border-radius:12px;padding:40px;
text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.1);}}h1{{color:{fg};margin:0 0 12px;}}
p{{color:#6b7280;margin:0;}}</style></head><body><div class="card"><h1>{h1}</h1><p>{msg}</p></div></body></html>"""


def _success():
    return _PAGE.format(title='Gekoppeld!', bg='#f0fdf4', fg='#16a34a', h1='✓ Gekoppeld!',
                        msg='Je AH-account is gekoppeld. Je kunt dit tabblad sluiten.')


def _error(msg):
    return _PAGE.format(title='Fout', bg='#fef2f2', fg='#dc2626', h1='✗ Koppelen mislukt', msg=msg)


def _sanitize_cookie(c):
    """Verwijder Secure/SameSite/Domain zodat cookies werken over http://localhost."""
    parts = c.split(';')
    out = [parts[0]]
    for p in parts[1:]:
        a = p.strip().lower()
        if a == 'secure' or a.startswith('samesite') or a.startswith('domain'):
            continue
        out.append(p)
    return ';'.join(out)


def _exchange_code(code):
    r = rq.post(TOKEN_URL, json={'clientId': CLIENT_ID, 'code': code},
                headers={'User-Agent': APPIE_UA, 'Content-Type': 'application/json'}, timeout=15)
    r.raise_for_status()
    d = r.json()
    with open(TOKEN_FILE, 'w') as f:
        json.dump({'access_token': d['access_token'], 'refresh_token': d['refresh_token'],
                   'expires_at': int(time.time()) + d.get('expires_in', 604798)}, f)


@app.route('/callback')
def callback():
    code = request.args.get('code', '')
    if not code:
        return Response(_error('Geen OAuth-code ontvangen'), status=400, content_type='text/html')
    try:
        _exchange_code(code)
    except Exception as e:
        return Response(_error(f'Token-exchange mislukt: {e}'), status=500, content_type='text/html')
    return Response(_success(), content_type='text/html')


@app.route('/')
def root():
    return redirect(LOCAL_ORIGIN + OAUTH_START)


@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'])
def proxy(path):
    full = request.full_path
    if full.endswith('?'):
        full = full[:-1]
    url = LOGIN_BASE + full

    fwd = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk == 'referer':
            fwd['Referer'] = v.replace(LOCAL_ORIGIN, LOGIN_BASE)
        elif lk == 'origin':
            fwd['Origin'] = LOGIN_BASE
        elif lk in _FWD_EXACT or lk.startswith('x-'):
            fwd[k] = v

    sess = cf.Session(impersonate=IMPERSONATE)
    try:
        up = sess.request(request.method, url, data=request.get_data(),
                          headers=fwd, allow_redirects=False, timeout=25)
    except Exception as e:
        return Response(f'Proxy fout: {e}', status=502)

    body = up.content
    ctype = up.headers.get('content-type', '')
    if any(t in ctype for t in _TEXT):
        body = body.replace(b'appie://login-exit', (LOCAL_ORIGIN + '/callback').encode())
        body = body.replace(b'https://login.ah.nl', LOCAL_ORIGIN.encode())

    out_headers = []
    for k, v in up.headers.multi_items():
        lk = k.lower()
        if lk in _HOP:
            continue
        if lk == 'location':
            if v.startswith('appie://'):
                q = urlparse(v).query
                v = LOCAL_ORIGIN + '/callback' + (('?' + q) if q else '')
            else:
                v = v.replace(LOGIN_BASE, LOCAL_ORIGIN)
        elif lk == 'set-cookie':
            v = _sanitize_cookie(v)
        out_headers.append((k, v))

    return Response(body, status=up.status_code, headers=out_headers)


if __name__ == '__main__':
    ssl_ctx = (CERT_FILE, KEY_FILE) if HTTPS else None
    print(f'[ah-proxy] {"HTTPS" if HTTPS else "HTTP"} op :{LISTEN_PORT}, origin {LOCAL_ORIGIN}', flush=True)
    app.run(host='0.0.0.0', port=LISTEN_PORT, threaded=True, ssl_context=ssl_ctx)
