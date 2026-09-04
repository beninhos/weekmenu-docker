"""Opnieuw inlezen van een importbatch.

Een geaccepteerd concept is al een recept geworden. Dat mag bij het opnieuw
inlezen niet verdwijnen, en de gebruiker mag er ook geen tweede concept voor
terugkrijgen: dan staat hij een recept na te kijken dat hij al heeft.
"""
import json
from unittest.mock import patch

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft
from weekmenu.services.dump import _accepted_pages, retry_dump_job


def _job_met_concepten(job_id='job-1'):
    db.session.add(DumpJob(id=job_id, status='done'))
    for pagina, status in ((1, 'accepted'), (2, 'pending'), (3, 'rejected')):
        db.session.add(RecipeDraft(
            job_id=job_id, name=f'Recept {pagina}', source_page=pagina,
            ingredients_json='[]', status=status))
    db.session.commit()
    return job_id


def test_geaccepteerd_concept_overleeft_opnieuw_inlezen(app):
    job_id = _job_met_concepten()
    with patch('weekmenu.services.dump._start_thread'):
        retry_dump_job(job_id)

    over = RecipeDraft.query.filter_by(job_id=job_id).all()
    assert [(d.source_page, d.status) for d in over] == [(1, 'accepted')]


def test_openstaand_en_afgewezen_verdwijnen_wel(app):
    job_id = _job_met_concepten()
    with patch('weekmenu.services.dump._start_thread'):
        retry_dump_job(job_id)

    statussen = {d.status for d in RecipeDraft.query.filter_by(job_id=job_id)}
    assert 'pending' not in statussen and 'rejected' not in statussen


def test_job_gaat_terug_naar_verwerken(app):
    job_id = _job_met_concepten()
    DumpJob.query.get(job_id).error_message = 'oude fout'
    db.session.commit()
    with patch('weekmenu.services.dump._start_thread') as thread:
        retry_dump_job(job_id)

    job = DumpJob.query.get(job_id)
    assert job.status == 'processing' and job.error_message is None
    thread.assert_called_once_with(job_id)


def test_accepted_pages_kent_de_afgehandelde_paginas(app):
    job_id = _job_met_concepten()
    assert _accepted_pages(job_id) == {1}


def test_accepted_pages_negeert_concepten_zonder_pagina(app):
    job_id = 'job-2'
    db.session.add(DumpJob(id=job_id, status='done'))
    db.session.add(RecipeDraft(job_id=job_id, name='Zonder pagina', source_page=None,
                               ingredients_json='[]', status='accepted'))
    db.session.commit()
    assert _accepted_pages(job_id) == set()


def test_afgehandelde_pagina_levert_geen_tweede_concept(app, tmp_path):
    """De kern: pagina 1 is al een recept, dus daar komt niets nieuws voor terug."""
    job_id = _job_met_concepten('job-3')
    job = DumpJob.query.get(job_id)

    antwoord = json.dumps([
        {"title": "Recept 1 opnieuw", "yields": 2, "photo_page": 1,
         "ingredients": [{"name": "ui", "amount": 1, "unit": "stuks"}], "instructions": "Stap 1."},
        {"title": "Recept 2 opnieuw", "yields": 2, "photo_page": 2,
         "ingredients": [{"name": "ei", "amount": 2, "unit": "stuks"}], "instructions": "Stap 1."},
    ])

    class _Antwoord:
        text = antwoord
        candidates = []

    jobmap = tmp_path / 'job'
    jobmap.mkdir()

    with patch('weekmenu.services.dump._get_gemini_api_key', return_value='x'), \
         patch('weekmenu.services.dump.lees_paginas', return_value=(['tekst pagina 1', 'tekst pagina 2'], [[], []])), \
         patch('weekmenu.services.dump._pdf_page_jpegs', return_value=[b'a', b'b']), \
         patch('weekmenu.services.dump._job_dir', return_value=str(jobmap)), \
         patch('weekmenu.services.dump._resolve_image', return_value=None), \
         patch('google.genai.Client') as client:
        (jobmap / '000.pdf').write_bytes(b'%PDF-')
        client.return_value.models.generate_content.return_value = _Antwoord()
        from weekmenu.services.dump import _process
        # pagina 1 staat op accepted; alleen pagina 2 hoort een nieuw concept te worden
        RecipeDraft.query.filter(RecipeDraft.job_id == job_id,
                                 RecipeDraft.status != 'accepted').delete()
        db.session.commit()
        _process(job)
        db.session.commit()

    nieuw = RecipeDraft.query.filter_by(job_id=job_id, status='pending').all()
    assert [d.source_page for d in nieuw] == [2]
    assert RecipeDraft.query.filter_by(job_id=job_id, status='accepted').count() == 1


def test_temperatuur_staat_op_nul(app, tmp_path):
    """Zonder deze instelling gokt het model en wisselt de uitkomst per aanroep."""
    db.session.add(DumpJob(id='job-4', status='processing'))
    db.session.commit()
    job = DumpJob.query.get('job-4')

    class _Antwoord:
        text = '[]'
        candidates = []

    jobmap = tmp_path / 'job'
    jobmap.mkdir()

    with patch('weekmenu.services.dump._get_gemini_api_key', return_value='x'), \
         patch('weekmenu.services.dump.lees_paginas', return_value=(['tekst'], [[]])), \
         patch('weekmenu.services.dump._pdf_page_jpegs', return_value=[b'a']), \
         patch('weekmenu.services.dump._job_dir', return_value=str(jobmap)), \
         patch('google.genai.Client') as client:
        (jobmap / '000.pdf').write_bytes(b'%PDF-')
        client.return_value.models.generate_content.return_value = _Antwoord()
        from weekmenu.services.dump import _process
        _process(job)

    config = client.return_value.models.generate_content.call_args.kwargs['config']
    assert config.temperature == 0
