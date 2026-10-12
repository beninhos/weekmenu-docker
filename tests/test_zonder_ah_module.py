"""De app start en werkt zonder de AH-module (stap 2 uit het winkelmodules-
onderzoek van 12 okt 2026): de connector is het losse package weekmenu_ah,
en alles wat eraan hangt moet het kunnen missen.

Draait in een subprocess, want in dit proces zijn die modules al geladen en
een sys.modules-truc achteraf bewijst niets.
"""
import json
import os
import subprocess
import sys

_SCRIPT = r'''
import sys
sys.modules['weekmenu_ah'] = None  # de connector ontbreekt
import os
os.environ['DATABASE_URL'] = 'sqlite://'
from weekmenu import create_app
app = create_app()
app.config['TESTING'] = True
from weekmenu.services.shopping import UITGANGEN, huidige_uitgang
with app.app_context():
    c = app.test_client()
    uit = {
        'blueprints': sorted(app.blueprints),
        'uitgangen': sorted(UITGANGEN),
        'standaard': huidige_uitgang(),
        'status': {p: c.get(p, follow_redirects=True).status_code for p in ['/', '/boodschappen', '/settings', '/wat-is-er-nieuw']},
        'settings_html': c.get('/settings').get_data(as_text=True),
        'boodschappen_html': c.get('/boodschappen').get_data(as_text=True),
    }
import json
print('RESULTAAT' + json.dumps(uit))
'''


def _zonder_ah():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, '-c', _SCRIPT], cwd=repo,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    regel = [r for r in proc.stdout.splitlines() if r.startswith('RESULTAAT')][-1]
    return json.loads(regel[len('RESULTAAT'):])


def test_de_app_start_zonder_ah_module_en_elke_pagina_laadt():
    uit = _zonder_ah()
    assert 'ah' not in uit['blueprints']
    assert uit['status'] == {'/': 200, '/boodschappen': 200, '/settings': 200, '/wat-is-er-nieuw': 200}


def test_zonder_ah_module_is_de_link_naar_ah_nl_de_standaard_uitgang():
    uit = _zonder_ah()
    assert uit['uitgangen'] == ['deeplink']
    assert uit['standaard'] == 'deeplink'
    assert 'value="ah"' not in uit['settings_html']
    assert 'value="deeplink"' in uit['settings_html']


def test_zonder_ah_module_verdwijnen_de_ah_knoppen_en_scripts():
    uit = _zonder_ah()
    assert 'AH winkelmand' not in uit['settings_html']
    assert 'Start AH-koppelaar' not in uit['settings_html']
    assert 'Koppel AH product' not in uit['boodschappen_html']
    assert 'ah_search.js' not in uit['boodschappen_html']
