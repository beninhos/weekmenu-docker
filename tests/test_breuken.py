"""Breuken in hoeveelheden: ½ is een halve, geen anderhalve.

Gemini las ½ structureel als 1.5 en op HelloFresh-kaarten (per persoon) zelfs als 3.
Daarom leest het model de hoeveelheid nu letterlijk over en rekent Python hem om.
"""
import pytest

from weekmenu.services.units import _parse_amount


@pytest.mark.parametrize('tekst,verwacht', [
    ('½', 0.5),
    ('¼', 0.25),
    ('¾', 0.75),
    ('1/2', 0.5),
    ('1 1/2', 1.5),
])
def test_losse_breuken(tekst, verwacht):
    assert _parse_amount(tekst) == verwacht


@pytest.mark.parametrize('tekst,verwacht', [
    ('1½', 1.5),
    ('2¼', 2.25),
    ('3¾', 3.75),
])
def test_heel_getal_met_breuk_plakt_niet_aan_elkaar(tekst, verwacht):
    """'1½' werd '10.5' doordat ½ als tekst door '0.5' werd vervangen."""
    assert _parse_amount(tekst) == verwacht


@pytest.mark.parametrize('tekst,verwacht', [
    ('½-1', 0.5),
    ('1-2', 1.0),
    ('2-3', 2.0),
    ('1½-2', 1.5),
    ('1 – 2', 1.0),
])
def test_bereik_wordt_de_ondergrens(tekst, verwacht):
    assert _parse_amount(tekst) == verwacht


@pytest.mark.parametrize('tekst,verwacht', [
    ('200', 200.0),
    ('1,5', 1.5),
    ('1.5', 1.5),
    ('2', 2.0),
])
def test_gewone_getallen_blijven_werken(tekst, verwacht):
    assert _parse_amount(tekst) == verwacht


@pytest.mark.parametrize('tekst', ['', None, 'naar smaak', 'een snufje'])
def test_onleesbaar_wordt_none(tekst):
    assert _parse_amount(tekst) is None


def test_een_derde_benadert_een_derde():
    assert _parse_amount('⅓') == pytest.approx(1 / 3)


def test_gemini_string_gaat_door_dezelfde_parser():
    """_as_number is wat de importer aanroept op wat Gemini teruggeeft."""
    from weekmenu.services.gemini import _as_number
    assert _as_number('½') == 0.5
    assert _as_number('1½') == 1.5
    assert _as_number(200) == 200.0
    assert _as_number(None) is None


# ── Afgekapt batchantwoord ──────────────────────────────────────────────

def test_afgekapte_batch_redt_de_volledige_recepten(app):
    """Bij een MAX_TOKENS-stop eindigt het antwoord midden in een recept."""
    from weekmenu.services.dump import parse_batch_response
    afgekapt = '''[
      {"title": "Eerste", "yields": 4, "photo_page": 1,
       "ingredients": [{"name": "munt", "amount": "½", "unit": "bosje"}],
       "instructions": "Stap 1."},
      {"title": "Tweede", "yields": 2, "photo_page": 2,
       "ingredients": [{"name": "bloem", "amount": "200", "unit": "g"}],
       "instructions": "Stap 1."},
      {"title": "Derde", "yields": 4, "photo_page": 3,
       "ingredients": [{"name": "ui", "amo'''
    recepten = parse_batch_response(afgekapt)
    assert [r['name'] for r in recepten] == ['Eerste', 'Tweede']
    assert recepten[0]['ingredients'][0]['amount'] == 0.5


def test_leeg_antwoord_geeft_nette_melding(app):
    """response.text is None zodra het budget in thinking is opgegaan."""
    from weekmenu.services.dump import parse_batch_response
    for leeg in (None, ''):
        with pytest.raises(ValueError, match='leeg antwoord'):
            parse_batch_response(leeg)


def test_onleesbaar_antwoord_zonder_te_redden_deel(app):
    from weekmenu.services.dump import parse_batch_response
    with pytest.raises(ValueError, match='Onleesbaar'):
        parse_batch_response('dit is geen json')


def test_ocr_verdubbelt_soms_een_breukteken():
    """Cloud Vision las '½ citroen' een keer als '½½ citroen'.

    Tweemaal hetzelfde breukteken achter elkaar bestaat niet in een recept,
    dus dat mag als artefact worden opgeruimd in plaats van None te worden.
    """
    assert _parse_amount('½½') == 0.5
    assert _parse_amount('¼¼') == 0.25
    assert _parse_amount('1½') == 1.5      # blijft anderhalf
    assert _parse_amount('½') == 0.5
