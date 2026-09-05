"""Wat een receptkaart per merk verraadt: alleen hier staat iets merkspecifieks."""
from weekmenu.services.kaartsignaturen import (bereidingstijd, is_benodigdheden_kop,
                                               is_voorkant, is_voorraadkop)


def test_hellofresh_voorkant():
    assert is_voorkant('HELLO Patatje oorlog met hamburger\nFRESH\nmet zelfgemaakte pindasaus')
    assert is_voorkant('HELLOFRESH\nKip tikka')
    assert not is_voorkant('Ingrediënten voor 2 personen\nHalfkruimige aardappelen')
    assert not is_voorkant('')
    assert not is_voorkant(None)


def test_voorraadkop_en_benodigdheden():
    assert is_voorraadkop('Zelf toevoegen')
    assert is_voorraadkop('  zelf toevoegen ')
    assert not is_voorraadkop('Zelf toevoegen aan de salade: 1 ui')
    assert is_benodigdheden_kop('Benodigdheden')
    assert not is_benodigdheden_kop('Benodigdheden voor de saus zijn simpel.')


def test_bereidingstijd():
    assert bereidingstijd('Bereidingstijd:40 min. (totaal voor 2 personen)') == 40
    assert bereidingstijd('Bereidingstijd: 25 minuten') == 25
    assert bereidingstijd('Kooktijd onbekend') is None
    assert bereidingstijd(None) is None


def test_bereidingstijd_kaartvarianten():
    # D1: drie extra kaartlay-outs uit de meting (Totale tijd, een bereik
    # daarin, en een kale 'N min.' achter een categorielabel).
    assert bereidingstijd('Lekker snel\nTotale tijd: 20 min.') == 20
    assert bereidingstijd('Lekker snel\nTotale tijd: 20-30 min.') == 20  # bereik -> ondergrens
    assert bereidingstijd(
        "25 min. (totaal voor 2 personen)") == 25
    assert bereidingstijd(
        'QUICK & EASY FAMILY BALANS 25 min. (totaal voor 2 personen)') == 25
    assert bereidingstijd(
        'Scandinavische salade BALANS 40 min. (totaal voor 2 personen)') == 40
    assert bereidingstijd('Kooktijd onbekend') is None


def test_bereidingstijd_wint_niet_van_oventijd():
    # D1: 'Bereidingstijd: 40 min.' moet blijven winnen als ook 'Oventijd'
    # op dezelfde kaart staat (kaart 5 uit de meting).
    assert bereidingstijd(
        'VEGGIE FAMILIE Bereidingstijd: 40 min. Oventijd: 15 min.') == 40
