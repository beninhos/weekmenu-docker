"""Wat is er nieuw: een changelog voor mensen, bereikbaar via de instellingen.

Rutger, 10 okt 2026: 'maak vanaf nu ook een changelog die te benaderen is via
de instellingenpagina, overzichtelijk en voor mensen duidelijk.' Vanaf nu
betekent: geen versie zonder regel. De eerste test faalt bij een versiebump
waarbij weekmenu/changelog.py vergeten is.
"""
from html import unescape

from weekmenu import __version__
from weekmenu.changelog import WIJZIGINGEN


def test_de_huidige_versie_staat_bovenaan_in_de_changelog():
    assert WIJZIGINGEN[0]['versie'] == __version__, \
        'versie opgehoogd zonder regel in weekmenu/changelog.py'
    assert all(v['punten'] for v in WIJZIGINGEN), 'elke versie zegt wat er veranderde'


def test_de_instellingen_linken_naar_wat_er_nieuw_is(client):
    assert '/wat-is-er-nieuw' in client.get('/settings').get_data(as_text=True)
    pagina = unescape(client.get('/wat-is-er-nieuw').get_data(as_text=True))
    for versie in WIJZIGINGEN:
        assert versie['versie'] in pagina
        assert all(punt in pagina for punt in versie['punten'])
