"""De app start en werkt zonder de Picnic-module (stap 3 winkelmodules): de
connector is het losse package weekmenu_picnic. Subprocess, net als
test_zonder_ah_module: in dit proces is het package al geladen."""
import json
import os
import subprocess
import sys

_SCRIPT = r'''
import sys
sys.modules['weekmenu_picnic'] = None  # de connector ontbreekt
import os
os.environ['DATABASE_URL'] = 'sqlite://'
from weekmenu import create_app
app = create_app()
app.config['TESTING'] = True
from weekmenu.services.shopping import UITGANGEN, BESTELLING_LEZERS
with app.app_context():
    c = app.test_client()
    c.post('/settings', data={'uitgang': 'picnic'})
    from weekmenu.services.shopping import huidige_uitgang
    uit = {
        'blueprints': sorted(app.blueprints),
        'uitgangen': sorted(UITGANGEN),
        'lezers': sorted(BESTELLING_LEZERS),
        'na_keuze_picnic': huidige_uitgang(),
        'status': {p: c.get(p, follow_redirects=True).status_code for p in ['/', '/boodschappen', '/settings']},
        'settings_html': c.get('/settings').get_data(as_text=True),
    }
import json
print('RESULTAAT' + json.dumps(uit))
'''


def test_de_app_start_zonder_picnic_module():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run([sys.executable, '-c', _SCRIPT], cwd=repo,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr[-2000:]
    uit = json.loads(proc.stdout.split('RESULTAAT', 1)[1])
    assert 'picnic' not in uit['blueprints']
    assert 'picnic' not in uit['uitgangen'] and 'picnic' not in uit['lezers']
    assert uit['na_keuze_picnic'] != 'picnic', 'een onbekende uitgang is niet te kiezen'
    assert all(code == 200 for code in uit['status'].values()), uit['status']
    assert 'value="picnic"' not in uit['settings_html'] and 'id="picnic"' not in uit['settings_html']
