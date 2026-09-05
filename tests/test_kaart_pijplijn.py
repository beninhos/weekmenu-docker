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
