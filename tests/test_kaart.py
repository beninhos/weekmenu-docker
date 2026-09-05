"""Receptkaart: paren, modelinvoer, controle tegen de tabel."""
from unittest.mock import patch

from weekmenu.services.kaart import benodigdheden, kaart_invoer, paren, zonder_tabelregels

RIJEN = [{'naam': 'Ui', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 1},
         {'naam': 'Prei', 'hoeveelheid': '2 st', 'blok': 'kaart', 'y': 2},
         {'naam': 'Olijfolie', 'hoeveelheid': '1 el', 'blok': 'voorraad', 'y': 3}]

ACHTER = ('Benodigdheden\nPan met deksel, koekenpan,\nsteelpan, saladekom\n'
          'Ingrediënten voor 2 personen\nUi\nPrei\n1 st\n2 st\nZelf toevoegen\nOlijfolie\n1 el\n'
          'Snijd de ui\nBak de prei 5 minuten.\n')


def _tabel_op(paginas):
    """Patch tabelrijen: pagina's in `paginas` hebben een tabel, de rest niet."""
    def nep(annotation, personen=None):
        return (RIJEN, None) if annotation.get('p') in paginas else (None, 'geen tabel')
    return patch('weekmenu.services.kaart.tabelrijen', side_effect=nep)


def _ann(n):
    return [{'p': i} for i in range(1, n + 1)]


def test_paren_op_volgorde_voor_dan_achter():
    with _tabel_op({2, 4}):
        uit, meldingen = paren(['HELLO FRESH kaart 1', 'tabel', 'HELLO FRESH kaart 2', 'tabel'], _ann(4))
    assert [(p['voor'], p['achter']) for p in uit] == [(1, 2), (3, 4)]
    assert uit[0]['rijen'] == RIJEN and meldingen == []


def test_achterkant_eerst_is_ook_goed():
    with _tabel_op({1}):
        uit, meldingen = paren(['tabel', 'HELLO FRESH'], _ann(2))
    assert [(p['voor'], p['achter']) for p in uit] == [(2, 1)] and meldingen == []


def test_twee_tabellen_in_een_paar_wordt_gemeld_en_overgeslagen():
    with _tabel_op({1, 2, 4}):
        uit, meldingen = paren(['t', 't', 'HELLO FRESH', 't'], _ann(4))
    assert [(p['voor'], p['achter']) for p in uit] == [(3, 4)]
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: op beide staat een ingrediëntentabel."]


def test_geen_tabel_in_een_paar_wordt_gemeld():
    with _tabel_op(set()):
        uit, meldingen = paren(['HELLO FRESH', 'x'], _ann(2))
    assert uit == []
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: op geen van beide staat een ingrediëntentabel."]


def test_meerdere_kolommen_wordt_met_reden_gemeld():
    with patch('weekmenu.services.kaart.tabelrijen', return_value=(None, 'meerdere kolommen')):
        uit, meldingen = paren(['HELLO FRESH', 'x'], _ann(2))
    assert uit == []
    assert meldingen == ["Pagina's 1 en 2 zijn niet als één kaart te lezen: de tabel heeft meerdere hoeveelheidkolommen, dat kan de app nog niet."]


def test_oneven_laatste_pagina_wordt_gemeld():
    with _tabel_op({2}):
        uit, meldingen = paren(['HELLO FRESH', 't', 'HELLO FRESH'], _ann(3))
    assert [(p['voor'], p['achter']) for p in uit] == [(1, 2)]
    assert meldingen == ['Pagina 3 heeft geen tegenhanger en is overgeslagen.']


def test_personen_uit_paginatekst_wordt_doorgegeven_aan_tabelrijen():
    with patch('weekmenu.services.kaart.tabelrijen', return_value=(RIJEN, None)) as nep:
        paren(['HELLO FRESH (totaal voor 2 personen)', 'tabel'], _ann(2))
    assert nep.call_args_list[0].kwargs['personen'] == 2
    assert nep.call_args_list[1].kwargs['personen'] == 2


def test_geen_personenzin_geeft_personen_none():
    with patch('weekmenu.services.kaart.tabelrijen', return_value=(RIJEN, None)) as nep:
        paren(['HELLO FRESH', 'tabel'], _ann(2))
    assert nep.call_args_list[0].kwargs['personen'] is None
    assert nep.call_args_list[1].kwargs['personen'] is None


def test_letterlijke_reden_wordt_met_paginanummer_gemeld():
    with patch('weekmenu.services.kaart.tabelrijen',
               side_effect=[(None, 'geen tabel'), (None, 'telling klopt niet: 11 namen, 8 hoeveelheden')]):
        uit, meldingen = paren(['HELLO FRESH', 'x'], _ann(2))
    assert uit == []
    assert meldingen == [
        "Pagina's 1 en 2 zijn niet als één kaart te lezen: "
        "de tabel op pagina 2 is niet te lezen (telling klopt niet: 11 namen, 8 hoeveelheden)."
    ]


def test_zonder_tabelregels_haalt_alleen_celregels_weg():
    uit = zonder_tabelregels(ACHTER, RIJEN)
    assert 'Ui\n' not in uit and '1 st' not in uit and 'Olijfolie' not in uit
    assert 'Snijd de ui' in uit and 'Bak de prei 5 minuten.' in uit
    assert 'Ingrediënten voor 2 personen' in uit   # de kop blijft: daar staat 'yields'


def test_kaart_invoer_heeft_drie_blokken_in_deze_volgorde():
    uit = kaart_invoer('HELLO FRESH\nPrei-ui', ACHTER, RIJEN, 1, 2)
    assert uit.index('--- Voorkant (pagina 1) ---') < uit.index('--- Ingrediënten (tabel) ---') \
        < uit.index('--- Achterkant (pagina 2) ---')
    assert 'Ui | 1 st\nPrei | 2 st\nOlijfolie | 1 el' in uit
    assert 'Snijd de ui' in uit


def test_benodigdheden_onder_de_kop_tot_de_regel_zonder_komma_aan_het_eind():
    assert benodigdheden(ACHTER) == 'Pan met deksel, koekenpan, steelpan, saladekom'
    assert benodigdheden('Snijd de ui\n') is None
