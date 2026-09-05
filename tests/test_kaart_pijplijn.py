"""Receptkaart-modus: van upload tot concept."""
import io
import json
from unittest.mock import patch

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft


def _upload(client, mode=None):
    data = {'files': (io.BytesIO(b'\xff\xd8\xff'), 'a.jpg', 'image/jpeg')}
    if mode:
        data['mode'] = mode
    with patch('weekmenu.services.dump._start_thread'):
        return client.post('/dump/upload', data=data, content_type='multipart/form-data')


def test_upload_zonder_modus_is_boek(app, client):
    resp = _upload(client)
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'boek'


def test_upload_met_kaartmodus_zet_vlag_op_de_job(app, client):
    resp = _upload(client, 'kaart')
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'kaart'


def test_onbekende_modus_wordt_boek(app, client):
    resp = _upload(client, 'iets')
    assert DumpJob.query.get(resp.get_json()['job_id']).mode == 'boek'


def test_standaard_pagina_overstemt_photo_page_van_het_model(app):
    from weekmenu.services.dump import parse_batch_response
    antwoord = json.dumps([{'title': 'K', 'yields': 2, 'photo_page': 7,
                            'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'}],
                            'steps': [{'start': 'Snijd de ui', 'end': 'in ringen.'}]}])
    recepten = parse_batch_response(antwoord, ['Snijd de ui in ringen.'], standaard_pagina=1)
    assert recepten[0]['photo_page'] == 1
    assert recepten[0]['instructions'] == 'Snijd de ui in ringen.'
    assert recepten[0]['meldingen'] == []


def test_kaartprompt_vraagt_een_recept_en_geen_photo_page():
    from weekmenu.services.dump import _KAART_PROMPT
    assert 'één recept' in _KAART_PROMPT and 'Ingrediënten (tabel)' in _KAART_PROMPT
    assert '"photo_page"' not in _KAART_PROMPT
    assert 'Gebruik ALLEEN deze eenheden' in _KAART_PROMPT   # de boekregels reizen mee
