"""Receptkaart-modus: van upload tot concept."""
import io
import json
from unittest.mock import patch

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft

VOOR = 'HELLO Patatje oorlog\nFRESH\nBereidingstijd:40 min. (totaal voor 2 personen)\n'
ACHTER = ('Benodigdheden\nPan met deksel\nIngrediënten voor 2 personen\nUi\n1 st\nPrei\n2 st\nOlijfolie\n1 el\n'
          'Snijd de ui in ringen.\nBak de prei 5 minuten.\n')
RIJEN = [{'naam': 'Ui', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 1},
         {'naam': 'Prei', 'hoeveelheid': '2 st', 'blok': 'kaart', 'y': 2},
         {'naam': 'Olijfolie', 'hoeveelheid': '1 el', 'blok': 'voorraad', 'y': 3}]
ANTWOORD = json.dumps([{'title': 'Patatje oorlog', 'yields': 2,
                        'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'},
                                        {'name': 'prei', 'amount': '3', 'unit': 'stuks'},
                                        {'name': 'olijfolie', 'amount': '1', 'unit': 'el'}],
                        'steps': [{'start': 'Snijd de ui', 'end': '5 minuten.'}]}])


ANTWOORD_ZONDER_ANKER = json.dumps([{'title': 'Patatje oorlog', 'yields': 2,
                                     'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'},
                                                     {'name': 'prei', 'amount': '2', 'unit': 'stuks'},
                                                     {'name': 'olijfolie', 'amount': '1', 'unit': 'el'}],
                                     'steps': [{'start': 'Verhit de olie in', 'end': 'gaar is.'}]}])


class _Antwoord:
    text = ANTWOORD
    candidates = []


class _ZonderAnker:
    """Ankers die nergens in de kaarttekst staan: er valt niets te knippen."""
    text = ANTWOORD_ZONDER_ANKER
    candidates = []


class _Garbage:
    """Een antwoord dat parse_batch_response niet kan redden: geen JSON, geen candidates."""
    text = 'dit is geen json'
    candidates = []


def _draai(tmp_path, mode, texts, annotaties, tabel, antwoorden=None, twijfels=None):
    job = DumpJob(id=f'job-{mode}', status='processing', mode=mode)
    db.session.add(job)
    db.session.commit()
    jobmap = tmp_path / 'job'
    jobmap.mkdir()
    if twijfels is None:
        twijfels = [[] for _ in texts]
    with patch('weekmenu.services.dump._get_gemini_api_key', return_value='x'), \
         patch('weekmenu.services.dump.lees_paginas_met_annotaties', return_value=(texts, twijfels, annotaties)), \
         patch('weekmenu.services.dump.lees_paginas', return_value=(texts, twijfels)), \
         patch('weekmenu.services.kaart.tabelrijen', side_effect=tabel), \
         patch('weekmenu.services.dump._pdf_page_jpegs', return_value=[b'a'] * len(texts)), \
         patch('weekmenu.services.dump._job_dir', return_value=str(jobmap)), \
         patch('weekmenu.services.dump._resolve_image', side_effect=lambda j, p, m: f'static/uploads/p{p}.jpg'), \
         patch('google.genai.Client') as client:
        (jobmap / '000.pdf').write_bytes(b'%PDF-')
        if antwoorden is not None:
            client.return_value.models.generate_content.side_effect = antwoorden
        else:
            client.return_value.models.generate_content.return_value = _Antwoord()
        from weekmenu.services.dump import _process
        _process(job)
        db.session.commit()
        return job, client


def test_kaartmodus_maakt_een_concept_van_twee_paginas(app, tmp_path):
    job, client = _draai(tmp_path, 'kaart', [VOOR, ACHTER], [{'p': 1}, {'p': 2}],
                         lambda ann, personen=None: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'))
    drafts = RecipeDraft.query.filter_by(job_id=job.id).all()
    assert len(drafts) == 1
    d = drafts[0]
    assert (d.name, d.serves, d.prep_time, d.source_page) == ('Patatje oorlog', 2, 40, 1)
    assert d.image_path == 'static/uploads/p1.jpg' and d.back_image_path == 'static/uploads/p2.jpg'
    assert d.instructions.startswith('Benodigdheden: Pan met deksel\n')
    assert 'Snijd de ui in ringen.' in d.instructions and 'Bak de prei 5 minuten.' in d.instructions
    ing = json.loads(d.ingredients_json)
    assert ing[1]['check'] == "tabel zegt '2 st'"
    assert ing[2]['kaart_voorraad'] is True
    assert client.return_value.models.generate_content.call_count == 1
    prompt = client.return_value.models.generate_content.call_args.kwargs['contents'][0]
    assert '--- Ingrediënten (tabel) ---\nUi | 1 st\nPrei | 2 st\nOlijfolie | 1 el' in prompt
    assert job.warning is None


def test_zonder_geknipte_bereiding_blijft_de_bereiding_leeg(app, tmp_path):
    # Vindt de ankerknip niets, dan is er geen bereiding. De benodigdheden
    # mogen er dan niet alsnog een niet-lege tekst van maken: de nakijkkaart
    # toont geen rode 'bereiding ontbreekt' meer en accepteren glipt erdoor.
    job, _ = _draai(tmp_path, 'kaart', [VOOR, ACHTER], [{'p': 1}, {'p': 2}],
                    lambda ann, personen=None: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'),
                    antwoorden=[_ZonderAnker()])
    d = RecipeDraft.query.filter_by(job_id=job.id).first()
    assert not (d.instructions or '').strip()
    assert 'geen enkel anker gevonden' in job.warning


def test_tabelcheck_en_twijfel_worden_beide_bewaard(app, tmp_path):
    # De tabel zet 'check' eerst (controleer_tegen_tabel); Vision's eigen
    # twijfel over hetzelfde ingrediënt mag die niet overschrijven, maar moet
    # erachter komen te staan — de tabel blijft leidend en dus voorop.
    twijfels = [[], [{'regel': '3 st Prei', 'cijfer': '3', 'zekerheid': 0.4}]]
    job, client = _draai(tmp_path, 'kaart', [VOOR, ACHTER], [{'p': 1}, {'p': 2}],
                         lambda ann, personen=None: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'),
                         twijfels=twijfels)
    d = RecipeDraft.query.filter_by(job_id=job.id).first()
    ing = json.loads(d.ingredients_json)
    assert ing[1]['check'].startswith("tabel zegt '2 st'; Vision las '3'")


def test_slecht_paar_wordt_gemeld_en_de_rest_gaat_door(app, tmp_path):
    job, client = _draai(tmp_path, 'kaart', [VOOR, ACHTER, VOOR, VOOR], [{'p': i} for i in (1, 2, 3, 4)],
                         lambda ann, personen=None: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'))
    assert RecipeDraft.query.filter_by(job_id=job.id).count() == 1
    assert "Pagina's 3 en 4 zijn niet als één kaart te lezen" in job.warning
    assert '4 pagina' not in job.warning   # geen 'minder recepten dan pagina's'-melding: paren tellen


def test_onleesbaar_antwoord_stopt_alleen_dat_paar(app, tmp_path):
    # Kaart 1+2 komt terug als brabbeltaal (bv. een kapotte JSON-respons); dat
    # mag de batch niet laten omvallen. Kaart 3+4 is verder identiek en goed.
    job, client = _draai(
        tmp_path, 'kaart', [VOOR, ACHTER, VOOR, ACHTER], [{'p': i} for i in (1, 2, 3, 4)],
        lambda ann, personen=None: (RIJEN, None) if ann['p'] in (2, 4) else (None, 'geen tabel'),
        antwoorden=[_Garbage(), _Antwoord()])
    drafts = RecipeDraft.query.filter_by(job_id=job.id).all()
    assert len(drafts) == 1
    assert drafts[0].source_page == 3
    assert "Pagina's 1+2:" in job.warning
    assert client.return_value.models.generate_content.call_count == 2


def test_boekmodus_waarschuwt_bij_kaarten(app, tmp_path):
    job, _ = _draai(tmp_path, 'boek', [VOOR, ACHTER, VOOR, ACHTER], [{}] * 4, lambda ann, personen=None: (None, 'geen tabel'))
    assert "lijken receptkaarten" in job.warning and "Pagina's 1, 3" in job.warning


def test_serialize_draft_zet_kaart_voorraad_om_in_pantry(app, client):
    from weekmenu.routes.dump import serialize_draft
    db.session.add(DumpJob(id='s', status='done'))
    d = RecipeDraft(job_id='s', name='K', ingredients_json=json.dumps(
        [{'name': 'olijfolie', 'amount': 1, 'unit': 'el', 'kaart_voorraad': True}]))
    db.session.add(d)
    db.session.commit()
    assert serialize_draft(d)['ingredients'][0]['in_pantry'] is True


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
