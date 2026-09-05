"""Wat er tussen scan en recept stil fout kon gaan.

De importroute is alleen bruikbaar als je erop kunt vertrouwen. Deze tests
leggen de gevallen vast waarin er eerder ongemerkt iets fouts in de database
kwam: een hoeveelheid die 0 werd, een half ingelezen batch die er compleet
uitzag, en hetzelfde concept dat twee recepten opleverde.
"""
import json
from unittest.mock import patch

import pytest

from weekmenu.extensions import db
from weekmenu.models import DumpJob, Recipe, RecipeDraft, RecipeIngredient
from weekmenu.services.dump import _eerste_getal, parse_batch_response
from weekmenu.services.ocr import _clean_ocr_text


def _concept(app, ingredienten, status='pending', job_id='job-v',
            instructions='Stap 1. Doe iets.'):
    if not DumpJob.query.get(job_id):
        db.session.add(DumpJob(id=job_id, status='done'))
    d = RecipeDraft(job_id=job_id, name='Proefrecept', source_page=1, status=status,
                    instructions=instructions,
                    ingredients_json=json.dumps(ingredienten))
    db.session.add(d)
    db.session.commit()
    return d


# ── Een hoeveelheid die ontbreekt mag geen nul worden ──────────────────

def test_ontbrekende_hoeveelheid_blokkeert_opslaan(client, app):
    """'g kipfilets' zou als 0 g op de boodschappenlijst belanden."""
    d = _concept(app, [{'name': 'kipfilets', 'amount': None, 'unit': 'g'}])
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 409
    assert 'kipfilets' in resp.get_json()['message']
    assert Recipe.query.count() == 0
    assert RecipeDraft.query.get(d.id).status == 'pending'


def test_ingredient_zonder_maat_mag_wel_zonder_getal(app, client):
    """'olijfolie' zonder hoeveelheid is normaal en hoort gewoon door te gaan."""
    d = _concept(app, [{'name': 'olijfolie', 'amount': None, 'unit': ''},
                       {'name': 'bloem', 'amount': 200, 'unit': 'g'}])
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 200
    assert Recipe.query.count() == 1


def test_onleesbare_hoeveelheid_laat_de_rest_staan(app, client):
    d = _concept(app, [{'name': 'bloem', 'amount': 'veel', 'unit': ''},
                       {'name': 'suiker', 'amount': 50, 'unit': 'g'}])
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 200
    suiker = [ri for ri in RecipeIngredient.query.all() if ri.amount == 50]
    assert len(suiker) == 1


# ── Een lege bereiding mag niet stilzwijgend geaccepteerd worden ───────

def test_lege_bereiding_blokkeert_opslaan(app, client):
    """Zonder bereidingstekst zou het recept stappenloos in de database komen."""
    d = _concept(app, [{'name': 'bloem', 'amount': 200, 'unit': 'g'}], instructions=None)
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 409
    assert 'bereiding' in resp.get_json()['message'].lower()
    assert Recipe.query.count() == 0
    assert RecipeDraft.query.get(d.id).status == 'pending'


def test_witruimte_bereiding_telt_ook_als_leeg(app, client):
    d = _concept(app, [{'name': 'bloem', 'amount': 200, 'unit': 'g'}], instructions='   \n\t  ')
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 409


def test_bereiding_met_tekst_mag_gewoon_opgeslagen_worden(app, client):
    d = _concept(app, [{'name': 'bloem', 'amount': 200, 'unit': 'g'}], instructions='Meng de bloem.')
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})

    assert resp.status_code == 200


# ── Hetzelfde concept twee keer opslaan ────────────────────────────────

def test_tweede_keer_opslaan_geeft_geen_tweede_recept(app, client):
    d = _concept(app, [{'name': 'bloem', 'amount': 200, 'unit': 'g'}])
    assert client.post(f'/dump/draft/{d.id}/accept', json={}).status_code == 200

    tweede = client.post(f'/dump/draft/{d.id}/accept', json={})
    assert tweede.status_code == 409
    assert Recipe.query.count() == 1


def test_afgewezen_concept_kan_niet_alsnog_opgeslagen_worden(app, client):
    d = _concept(app, [{'name': 'bloem', 'amount': 200, 'unit': 'g'}], status='rejected')
    assert client.post(f'/dump/draft/{d.id}/accept', json={}).status_code == 409
    assert Recipe.query.count() == 0


# ── Een afwijkend antwoord mag de batch niet kosten ────────────────────

@pytest.mark.parametrize('waarde,verwacht', [
    (4, 4), ('4', 4), ('4-6', 4), ('4 personen', 4), ('voor 2', 2),
    (None, None), ('', None), ('veel', None), (True, None), (2.0, 2),
])
def test_aantal_personen_uit_afwijkende_waarden(waarde, verwacht):
    assert _eerste_getal(waarde) == verwacht


def test_niet_numeriek_aantal_personen_breekt_de_batch_niet(app):
    payload = json.dumps([
        {"title": "Eerste", "yields": "4-6", "photo_page": 1,
         "ingredients": [{"name": "ei", "amount": 2, "unit": "stuks"}], "instructions": "x"},
        {"title": "Tweede", "yields": 2, "photo_page": 2,
         "ingredients": [{"name": "meel", "amount": 100, "unit": "g"}], "instructions": "y"},
    ])
    recepten = parse_batch_response(payload)
    assert [r['name'] for r in recepten] == ['Eerste', 'Tweede']
    assert recepten[0]['serves'] == 4


def test_recept_zonder_ingredientenlijst_kost_de_batch_niet(app):
    payload = json.dumps([
        {"title": "Zonder lijst", "yields": 2, "photo_page": 1,
         "ingredients": None, "instructions": "x"},
        {"title": "Met lijst", "yields": 2, "photo_page": 2,
         "ingredients": [{"name": "meel", "amount": 100, "unit": "g"}], "instructions": "y"},
    ])
    recepten = parse_batch_response(payload)
    assert [r['name'] for r in recepten] == ['Zonder lijst', 'Met lijst']
    assert recepten[0]['ingredients'] == []


# ── OCR-artefacten rond het breukteken ─────────────────────────────────

@pytest.mark.parametrize('ruw,schoon', [
    ('½2 citroen', '½ citroen'),          # Vision schrijft de glyph én een cijfer
    ('½½ bosje munt', '½ bosje munt'),    # verdubbeld breukteken
    ('½½2 citroen', '½ citroen'),
    ('¼4 appel', '¼ appel'),
    ('½ citroen', '½ citroen'),           # ongemoeid
    ('1½ citroen', '1½ citroen'),         # gemengd getal blijft heel
    ('3,5% melk', '3,5% melk'),           # een echt percentage
    ('12 komkommer', '12 komkommer'),     # geen breukteken: niet aan zitten
])
def test_breukartefacten_opruimen(ruw, schoon):
    assert _clean_ocr_text(ruw) == schoon


# ── Losse hoofdletter I die een 1 hoort te zijn ─────────────────────────

@pytest.mark.parametrize('ruw,schoon', [
    ('Rooster de kip I uur', 'Rooster de kip 1 uur'),  # het echte gemeten geval
    ('I ui, gesnipperd', '1 ui, gesnipperd'),
    ('Groep I', 'Groep I'),               # geen vervolgwoord: ongemoeid
    ('I. Snijd de ui', 'I. Snijd de ui'), # nummering, geen spatie na de I
    ('bak I minuut per kant', 'bak 1 minuut per kant'),  # ook midden in de zin
])
def test_losse_hoofdletter_i_wordt_1(ruw, schoon):
    assert _clean_ocr_text(ruw) == schoon


# ── Een mislukte batch laat niets half achter ──────────────────────────

def test_mislukte_batch_laat_geen_halve_oogst_achter(app, tmp_path):
    from weekmenu.services.dump import process_dump_job

    db.session.add(DumpJob(id='job-half', status='processing'))
    db.session.commit()

    def _valt_om(job):
        db.session.add(RecipeDraft(job_id='job-half', name='Half', source_page=1,
                                   ingredients_json='[]', status='pending'))
        db.session.flush()
        raise ValueError('onderweg stukgelopen')

    with patch('weekmenu.services.dump._process', side_effect=_valt_om):
        process_dump_job(app, 'job-half')

    assert RecipeDraft.query.filter_by(job_id='job-half').count() == 0
    assert DumpJob.query.get('job-half').status == 'error'
