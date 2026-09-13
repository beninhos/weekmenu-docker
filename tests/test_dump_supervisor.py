"""Wat gebeurt er met verloren 'processing' jobs bij Flask-opstart.

De thread die de job draaide leeft niet meer als de container is herstart,
maar de status blijft anders 'processing' en de dump-pagina polt eeuwig.
"""
from weekmenu.extensions import db
from weekmenu.models import DumpJob
from weekmenu.services.dump import herstel_verloren_jobs


def test_processing_wordt_error_bij_opstart(app):
    db.session.add(DumpJob(id='p1', status='processing'))
    db.session.commit()

    aantal = herstel_verloren_jobs()

    assert aantal == 1
    job = db.session.get(DumpJob, 'p1')
    assert job.status == 'error'
    assert 'herstart' in (job.error_message or '').lower()


def test_klaar_en_error_blijven_staan(app):
    db.session.add_all([
        DumpJob(id='d1', status='done'),
        DumpJob(id='e1', status='error', error_message='iets anders'),
    ])
    db.session.commit()

    herstel_verloren_jobs()

    assert db.session.get(DumpJob, 'd1').status == 'done'
    err = db.session.get(DumpJob, 'e1')
    assert err.status == 'error'
    assert err.error_message == 'iets anders'


def test_zonder_verloren_jobs_geen_commit(app):
    db.session.add(DumpJob(id='d1', status='done'))
    db.session.commit()

    assert herstel_verloren_jobs() == 0
