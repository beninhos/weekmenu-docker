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
