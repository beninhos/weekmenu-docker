"""De Vision-sleutel invullen op de instellingenpagina.

Het gaat hier om één ding: een sleutel die Cloud Vision weigert mag niet
opgeslagen worden, want dan denkt de gebruiker dat het geregeld is en loopt de
import pas veel later stuk — in een achtergrondthread, waar de melding niet
meer bij hem terechtkomt.
"""
import urllib.error

import pytest

from weekmenu.models import Settings
from weekmenu.services import ocr


def _http_error(code, message):
    """Een HTTPError zoals urllib hem opwerpt, inclusief leesbaar foutlichaam."""
    import io
    import json as _json
    body = _json.dumps({'error': {'message': message}}).encode()
    return urllib.error.HTTPError('https://vision', code, message, {}, io.BytesIO(body))


@pytest.fixture()
def geen_echte_aanroep(monkeypatch):
    """Standaard: elke aanroep naar Vision slaagt. Tests die iets anders willen
    zetten hun eigen _annotate neer."""
    monkeypatch.setattr(ocr, '_annotate', lambda *a, **k: [{}])


def test_geldige_sleutel_wordt_bewaard(client, geen_echte_aanroep):
    resp = client.post('/api/vision/key', json={'key': 'AIzaGoed'})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'
    assert Settings.query.filter_by(key='vision_api_key').first().value == 'AIzaGoed'


def test_geweigerde_sleutel_wordt_niet_bewaard(client, monkeypatch):
    """De API staat nog uit in het project — de meest voorkomende misser."""
    def fake_urlopen(*a, **k):
        raise _http_error(403, 'Cloud Vision API has not been used in project')
    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)

    resp = client.post('/api/vision/key', json={'key': 'AIzaFout'})
    assert resp.status_code == 400
    assert 'Vision-API aanstaat' in resp.get_json()['message']
    assert Settings.query.filter_by(key='vision_api_key').first() is None


def test_typefout_in_sleutel_geeft_begrijpelijke_melding(client, monkeypatch):
    """Google geeft bij een half overgenomen sleutel een 400, geen 401."""
    def fake_urlopen(*a, **k):
        raise _http_error(400, 'API key not valid. Please pass a valid API key.')
    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)

    resp = client.post('/api/vision/key', json={'key': 'AIzaHalf'})
    assert resp.status_code == 400
    assert 'volledig is overgenomen' in resp.get_json()['message']
    assert Settings.query.filter_by(key='vision_api_key').first() is None


def test_onbereikbare_api_bewaart_toch_met_waarschuwing(client, monkeypatch):
    """Een kapotte verbinding zegt niets over de sleutel, dus die blijft staan."""
    def fake_urlopen(*a, **k):
        raise urllib.error.URLError('Name or service not known')
    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)

    resp = client.post('/api/vision/key', json={'key': 'AIzaOnbekend'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'
    assert 'niet kunnen controleren' in data['warning']
    assert Settings.query.filter_by(key='vision_api_key').first().value == 'AIzaOnbekend'


def test_lege_sleutel_wordt_geweigerd(client):
    resp = client.post('/api/vision/key', json={'key': '   '})
    assert resp.status_code == 400
    assert Settings.query.filter_by(key='vision_api_key').first() is None


def test_sleutel_verwijderen(client, geen_echte_aanroep):
    client.post('/api/vision/key', json={'key': 'AIzaGoed'})
    assert client.delete('/api/vision/key').status_code == 200
    assert Settings.query.filter_by(key='vision_api_key').first() is None


def test_status_volgt_de_opgeslagen_sleutel(client, geen_echte_aanroep, monkeypatch):
    monkeypatch.delenv('VISION_API_KEY', raising=False)
    assert client.get('/api/vision/status').get_json()['configured'] is False
    client.post('/api/vision/key', json={'key': 'AIzaGoed'})
    assert client.get('/api/vision/status').get_json()['configured'] is True


@pytest.mark.parametrize('storing', [
    TimeoutError('timed out'),
    ConnectionResetError(104, 'Connection reset by peer'),
])
def test_storing_buiten_urlerror_kost_de_sleutel_niet(client, monkeypatch, storing):
    """urllib wikkelt niet elke storing in een URLError.

    Een leestimeout komt als kale TimeoutError naar boven. Ontsnapt die, dan
    geeft de route een 500 en raakt de gebruiker een sleutel kwijt die
    waarschijnlijk gewoon goed was.
    """
    def fake_urlopen(*a, **k):
        raise storing
    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)

    resp = client.post('/api/vision/key', json={'key': 'AIzaTraag'})
    assert resp.status_code == 200
    assert 'niet kunnen controleren' in resp.get_json()['warning']
    assert Settings.query.filter_by(key='vision_api_key').first().value == 'AIzaTraag'


def test_proefaanroep_wacht_korter_dan_een_batch(monkeypatch):
    """Een klik op Opslaan mag niet de twee minuten van een batch erven."""
    gezien = {}

    def fake_urlopen(request, timeout=None):
        gezien['timeout'] = timeout
        raise urllib.error.URLError('stop')
    monkeypatch.setattr(ocr.urllib.request, 'urlopen', fake_urlopen)

    ocr.verify_vision_key('AIzaGoed')
    assert gezien['timeout'] == ocr._TIMEOUT_PROEF
    assert ocr._TIMEOUT_PROEF < ocr._TIMEOUT


def test_proefaanroep_gebruikt_maar_een_pagina(monkeypatch):
    """De controle mag niet meer dan één van de gratis pagina's kosten."""
    gezien = []
    monkeypatch.setattr(ocr, '_annotate',
                        lambda key, images, taal, timeout=None: gezien.append(images) or [{}])
    assert ocr.verify_vision_key('AIzaGoed') == (True, '')
    assert len(gezien) == 1 and len(gezien[0]) == 1
