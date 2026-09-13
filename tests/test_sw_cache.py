"""Service worker: de CACHE-naam beweegt vanzelf mee met de JS-inhoud."""
import os
import re

import pytest


def _leg_sw_klaar(static_dir, sw_regel="const CACHE = 'weekmenu-devel';"):
    """Zet een minimale sw.js + een JS-bestand neer, zoals de app die kent."""
    os.makedirs(os.path.join(static_dir, 'js'), exist_ok=True)
    with open(os.path.join(static_dir, 'sw.js'), 'w') as fh:
        fh.write(f"// header\n{sw_regel}\nself.addEventListener('install', () => {{}});")
    with open(os.path.join(static_dir, 'js', 'a.js'), 'w') as fh:
        fh.write("console.log('een');")


@pytest.fixture()
def sw_app(app):
    """De service-worker-route en zijn interne cache resetten na elke test."""
    from weekmenu.routes import main as main_mod
    main_mod._SW_CACHE['inhoud'] = None
    _leg_sw_klaar(app.static_folder)
    yield app
    main_mod._SW_CACHE['inhoud'] = None


def _hash_uit(body):
    m = re.search(r"CACHE = 'weekmenu-([0-9a-f]+)'", body)
    return m.group(1) if m else None


def test_route_serveert_javascript(sw_app):
    r = sw_app.test_client().get('/static/sw.js')
    assert r.status_code == 200
    assert 'javascript' in r.headers.get('Content-Type', '')


def test_cache_naam_is_een_hash(sw_app):
    body = sw_app.test_client().get('/static/sw.js').get_data(as_text=True)
    assert _hash_uit(body), "CACHE-suffix hoort een hex-hash te zijn, niet 'devel'"


def test_hash_beweegt_mee_met_de_js(sw_app):
    from weekmenu.routes import main as main_mod
    eerste = _hash_uit(sw_app.test_client().get('/static/sw.js').get_data(as_text=True))
    main_mod._SW_CACHE['inhoud'] = None                     # geheugen ontkrachten
    with open(os.path.join(sw_app.static_folder, 'js', 'a.js'), 'w') as fh:
        fh.write("console.log('twee');")                    # inhoud gewijzigd
    tweede = _hash_uit(sw_app.test_client().get('/static/sw.js').get_data(as_text=True))
    assert eerste != tweede


def test_hash_blijft_stabiel_zonder_wijziging(sw_app):
    a = _hash_uit(sw_app.test_client().get('/static/sw.js').get_data(as_text=True))
    b = _hash_uit(sw_app.test_client().get('/static/sw.js').get_data(as_text=True))
    assert a == b
