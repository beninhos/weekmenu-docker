import glob
import hashlib
import os
import re
from datetime import date

from flask import Blueprint, current_app, redirect, request, url_for

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    today = date.today()
    iso = today.isocalendar()
    year, week_number = iso[0], iso[1]
    cookie = request.cookies.get('last_viewed_week', '')
    try:
        c_year, c_week = (int(p) for p in cookie.split('-'))
        if 1 <= c_week <= 53 and abs(c_year - year) <= 1:
            # Validate that the week actually exists for that year
            date.fromisocalendar(c_year, c_week, 1)
            year, week_number = c_year, c_week
    except (ValueError, AttributeError):
        pass
    return redirect(url_for('menu.week_menu', year=year, week=week_number))


@bp.route('/boodschappenlijst')
def boodschappenlijst_redirect():
    return redirect(url_for('shopping.boodschappen'))


# Service worker: CACHE-naam is een hash van de eigen inhoud plus alle
# JS-bestanden die de app serveert, zodat een uitrol de oude cache automatisch
# ongeldig maakt en de handmatige 'weekmenu-vN'-oplopende regel niet meer nodig
# is. De hash wordt bij Flask-opstart één keer berekend en daarna hergebruikt;
# elke container-restart pikt nieuwe bytes vanzelf op.
_SW_CACHE_RE = re.compile(r"const CACHE = '[^']*';")
_SW_CACHE = {'inhoud': None}


def _bouw_sw_inhoud():
    static = current_app.static_folder
    sw_pad = os.path.join(static, 'sw.js')
    bronnen = sorted(glob.glob(os.path.join(static, 'js', '*.js')))
    for blauwdruk in current_app.blueprints.values():  # de AH-connector levert eigen JS
        if blauwdruk.static_folder:
            bronnen += sorted(glob.glob(os.path.join(blauwdruk.static_folder, 'js', '*.js')))
    bronnen.append(sw_pad)
    hasher = hashlib.sha1()
    for pad in bronnen:
        with open(pad, 'rb') as fh:
            hasher.update(fh.read())
    stempel = hasher.hexdigest()[:12]
    with open(sw_pad) as fh:
        return _SW_CACHE_RE.sub(f"const CACHE = 'weekmenu-{stempel}';", fh.read())


@bp.route('/static/sw.js')
def sw_js():
    if _SW_CACHE['inhoud'] is None:
        _SW_CACHE['inhoud'] = _bouw_sw_inhoud()
    return _SW_CACHE['inhoud'], 200, {
        'Content-Type': 'application/javascript',
        'Cache-Control': 'no-cache',
    }
