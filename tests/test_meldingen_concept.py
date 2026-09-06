"""Meldingen horen bij het concept waar ze over gaan, niet in één batchblok.

Op de eerste echte kaartbatch (24 pagina's) stond bovenaan één blok van twaalf
keer 'uit de bereiding weggelaten: ... Vetten (g)': niemand leest dat, en het
verborg zelfs de keuzelijst eronder. Wat over één recept gaat staat nu op dat
recept; het batchblok is alleen nog voor batchbrede zaken.
"""
import json

import sqlalchemy as sa

from weekmenu.models import RecipeDraft
from weekmenu.routes.dump import serialize_draft
from tests.test_kaart_pijplijn import ACHTER, RIJEN, VOOR, _draai


class _AntwoordZonderPrei:
    text = json.dumps([{'title': 'Patatje oorlog', 'yields': 2,
                        'ingredients': [{'name': 'ui', 'amount': '1', 'unit': 'stuks'},
                                        {'name': 'olijfolie', 'amount': '1', 'unit': 'el'}],
                        'steps': [{'start': 'Snijd de ui', 'end': '5 minuten.'}]}])
    candidates = []


def test_ontbrekende_tabelrij_staat_op_het_concept_niet_op_de_batch(app, tmp_path):
    job, _ = _draai(tmp_path, 'kaart', [VOOR, ACHTER], [{'p': 1}, {'p': 2}],
                    lambda ann, personen=None: (RIJEN, None) if ann['p'] == 2 else (None, 'geen tabel'),
                    antwoorden=[_AntwoordZonderPrei()])
    d = RecipeDraft.query.filter_by(job_id=job.id).one()
    assert json.loads(d.meldingen_json) == ["tabelrij 'Prei | 2 st' ontbreekt bij de ingrediënten"]
    assert job.warning is None


class _BoekAntwoord:
    text = json.dumps([{'title': 'Kip met rijst', 'photo_page': 1, 'yields': 2,
                        'ingredients': [{'name': 'kip', 'amount': '2', 'unit': 'stuks'}],
                        'steps': [{'start': 'Rooster de kip', 'end': 'alles gaar is.'}]}])
    candidates = []


def test_staartzin_staat_op_het_concept_en_de_batch_blijft_schoon(app, tmp_path):
    pagina = ("Kip met rijst\n2 kipfilets\nRooster de kip een uur tot alles gaar is.\n"
              "Hussel de groenten voor het opscheppen nog even goed door het vocht.\n")
    job, _ = _draai(tmp_path, 'boek', [pagina], [None], lambda ann, personen=None: (None, 'geen tabel'),
                    antwoorden=[_BoekAntwoord()])
    d = RecipeDraft.query.filter_by(job_id=job.id).one()
    meldingen = json.loads(d.meldingen_json)
    assert len(meldingen) == 1 and meldingen[0].startswith("na de laatste stap stond nog 'Hussel de groenten")
    assert job.warning is None
    assert serialize_draft(d)['meldingen'] == meldingen


def test_concept_zonder_meldingen_serialiseert_een_lege_lijst(app):
    d = RecipeDraft(job_id='x', name='Leeg', ingredients_json='[]')
    assert serialize_draft(d)['meldingen'] == []


def test_migratie_v17_voegt_de_kolom_toe():
    from weekmenu.migrations import _migrate_v17
    engine = sa.create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(sa.text('CREATE TABLE recipe_draft (id INTEGER PRIMARY KEY, name TEXT)'))
        _migrate_v17(conn)
        _migrate_v17(conn)          # idempotent
        cols = [r[1] for r in conn.execute(sa.text('PRAGMA table_info(recipe_draft)')).fetchall()]
    assert 'meldingen_json' in cols


def test_batchmelding_van_een_afgehandelde_batch_verdwijnt_van_de_pagina(app, client):
    # De pagina toonde de melding van élke batch ooit, en door de volgorde won
    # de oudste: een logdump van dagen geleden bleef bovenaan staan. Een
    # batchmelding hoort bij de concepten die je nog moet nakijken; zijn die
    # weg, dan is de melding ook klaar.
    from weekmenu.extensions import db
    from weekmenu.models import DumpJob
    db.session.add(DumpJob(id='oud', status='done', warning='OUDE-MELDING-XYZ'))
    db.session.add(DumpJob(id='nieuw', status='done', warning='NIEUWE-MELDING-XYZ'))
    db.session.add(RecipeDraft(job_id='nieuw', name='Nog na te kijken', ingredients_json='[]', status='pending'))
    db.session.add(RecipeDraft(job_id='oud', name='Al afgewezen', ingredients_json='[]', status='rejected'))
    db.session.commit()
    html = client.get('/dump').get_data(as_text=True)
    assert 'NIEUWE-MELDING-XYZ' in html
    assert 'OUDE-MELDING-XYZ' not in html
