"""Receptkaart: paren, modelinvoer, controle tegen de tabel."""
from unittest.mock import patch

from weekmenu.services.kaart import (benodigdheden, controleer_tegen_tabel, kaart_invoer, paren,
                                      zonder_tabelregels)

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
    uit = kaart_invoer('HELLO FRESH\nPrei-ui', zonder_tabelregels(ACHTER, RIJEN), RIJEN, 1, 2)
    assert uit.index('--- Voorkant (pagina 1) ---') < uit.index('--- Ingrediënten (tabel) ---') \
        < uit.index('--- Achterkant (pagina 2) ---')
    assert 'Ui | 1 st\nPrei | 2 st\nOlijfolie | 1 el' in uit
    assert 'Snijd de ui' in uit
    assert '\n1 st\n' not in uit          # de aanroeper heeft de tabelregels er al uit


def test_kaart_invoer_strijkt_de_achterkant_niet_zelf_glad():
    # De aanroeper strijkt de tabelregels eruit (en gebruikt diezelfde tekst
    # ook voor de ankerknip); kaart_invoer zet alleen de blokken op een rij.
    uit = kaart_invoer('HELLO FRESH', ACHTER, RIJEN, 1, 2)
    assert '\n1 st\n' in uit


def test_benodigdheden_tot_de_tabelkop_een_voorraadkop_of_een_lege_regel():
    assert benodigdheden(ACHTER) == 'Pan met deksel, koekenpan, steelpan, saladekom'
    assert benodigdheden('Benodigdheden\nKoekenpan, hapjespan\n\nSnijd de ui\n') == 'Koekenpan, hapjespan'
    assert benodigdheden('Benodigdheden\nKoekenpan\nZelf toevoegen\nOlijfolie\n') == 'Koekenpan'
    assert benodigdheden('Snijd de ui\n') is None


def test_benodigdheden_loopt_over_een_regel_zonder_komma_door():
    # Kaart 4 uit de meting: de opsomming breekt midden in 'hapjespan met
    # deksel' af. De oude komma-regel stopte daar en liet het laatste stuk
    # gereedschap vallen.
    tekst = ('Benodigdheden\nKoekenpan, grote pan met deksel, hapjespan met\ndeksel\n'
             'Ingrediënten voor 2 personen\n')
    assert benodigdheden(tekst) == 'Koekenpan, grote pan met deksel, hapjespan met deksel'


def test_benodigdheden_neemt_hooguit_vier_regels_mee():
    tekst = 'Benodigdheden\n' + ''.join(f'regel {i}\n' for i in range(1, 7))
    assert benodigdheden(tekst) == 'regel 1 regel 2 regel 3 regel 4'


def _recept(*ingredienten):
    return {'name': 'X', 'ingredients': [dict(i) for i in ingredienten], 'meldingen': []}


def test_kloppende_hoeveelheid_krijgt_geen_check():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    meldingen = controleer_tegen_tabel(r, RIJEN, '1+2')
    assert meldingen == []
    assert all('check' not in i for i in r['ingredients'])
    assert r['ingredients'][2]['kaart_voorraad'] is True
    assert 'kaart_voorraad' not in r['ingredients'][0]


def test_afwijkende_hoeveelheid_krijgt_check_met_de_celtekst():
    r = _recept({'name': 'ui', 'amount': 10.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    controleer_tegen_tabel(r, RIJEN, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '1 st'"


def test_breuk_en_eenheid_worden_genormaliseerd_voor_de_vergelijking():
    rijen = [{'naam': 'Zonnebloemolie', 'hoeveelheid': '½ el', 'blok': 'voorraad', 'y': 1},
             {'naam': 'Peper en zout', 'hoeveelheid': 'naar smaak', 'blok': 'voorraad', 'y': 2},
             {'naam': 'Kip', 'hoeveelheid': '300 gram', 'blok': 'kaart', 'y': 3}]
    r = _recept({'name': 'zonnebloemolie', 'amount': 0.5, 'unit': 'el'},
                {'name': 'peper en zout', 'amount': None, 'unit': ''},
                {'name': 'kip', 'amount': 300.0, 'unit': 'g'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert all('check' not in i for i in r['ingredients'])


def test_ingredient_buiten_de_tabel_blijft_staan_met_check():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'prei', 'amount': 2.0, 'unit': 'stuks'},
                {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'}, {'name': 'snuf peper', 'amount': None, 'unit': ''})
    controleer_tegen_tabel(r, RIJEN, '1+2')
    assert r['ingredients'][3]['check'] == 'staat niet in de tabel'
    assert len(r['ingredients']) == 4


def test_ontbrekende_tabelrij_wordt_gemeld():
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'}, {'name': 'olijfolie', 'amount': 1.0, 'unit': 'el'})
    meldingen = controleer_tegen_tabel(r, RIJEN, '3+4')
    assert meldingen == ["Pagina's 3+4 (X): tabelrij 'Prei | 2 st' ontbreekt in het concept."]


def test_stuk_s_uit_de_kaart_komt_overeen_met_stuks():
    rijen = [{'naam': 'Ui', 'hoeveelheid': '1 stuk(s)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'ui', 'amount': 1.0, 'unit': 'stuks'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]


def test_bol_len_uit_de_kaart_komt_overeen_met_bol():
    rijen = [{'naam': 'Mozzarella', 'hoeveelheid': '1 bol(len)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'mozzarella', 'amount': 1.0, 'unit': 'bol'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]


def test_ocr_misread_breuk_als_procent_geeft_check_met_de_celtekst():
    rijen = [{'naam': 'Mexicaanse kruiden', 'hoeveelheid': '% zakje(s)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'mexicaanse kruiden', 'amount': 0.5, 'unit': 'zakje'})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '% zakje(s)'"


def test_lege_hoeveelheid_tegen_echte_cel_geeft_check_zonder_crash():
    r = _recept({'name': 'ui', 'amount': '', 'unit': ''})
    controleer_tegen_tabel(r, RIJEN, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '1 st'"


def test_scheutje_met_amount_1_krijgt_geen_check():
    # D2: 'scheutje' heeft geen getal, maar het model las precies hetzelfde
    # (amount 1, unit 'scheutje') — dat is niets om na te kijken.
    rijen = [{'naam': 'Melk', 'hoeveelheid': 'scheutje', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'melk', 'amount': 1.0, 'unit': 'scheutje'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]


def test_scheutje_zonder_modelhoeveelheid_krijgt_geen_check():
    rijen = [{'naam': 'Melk', 'hoeveelheid': 'scheutje', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'melk', 'amount': None, 'unit': ''})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]


def test_scheutje_met_afwijkende_modelhoeveelheid_krijgt_wel_check():
    rijen = [{'naam': 'Melk', 'hoeveelheid': 'scheutje', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'melk', 'amount': 2.0, 'unit': 'el'})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt 'scheutje'"


def test_pakje_vs_pak_ken_wordt_als_dezelfde_eenheid_gezien():
    # D3: het model parafraseert de eenheid ('pakje' voor '1 pak(ken)'), het
    # getal klopt — geen echte afwijking.
    rijen = [{'naam': 'Passata', 'hoeveelheid': '1 pak(ken)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'passata', 'amount': 1.0, 'unit': 'pakje'})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]


def test_ontbrekende_eenheid_bij_het_model_blijft_een_afwijking():
    # D3: de cel heeft een eenheid ('krop'), het model niet — informatie is
    # verloren gegaan, dus dat blijft zichtbaar.
    rijen = [{'naam': 'Little gem', 'hoeveelheid': '2 krop', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'little gem', 'amount': 2.0, 'unit': ''})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '2 krop'"


def test_echt_andere_eenheid_blijft_een_afwijking():
    # D3: 'st' en 'teen' zijn geen parafrase van elkaar (normaliseren allebei
    # naar iets anders), dus dat blijft een echte check.
    rijen = [{'naam': 'Knoflookteen', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'knoflookteen', 'amount': 1.0, 'unit': 'teen'})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '1 st'"


def test_ocr_glitch_zonder_modelhoeveelheid_blijft_toch_een_afwijking():
    # D4-vangnet: '%' is geen woordhoeveelheid maar een OCR-leesfout van '½'.
    # Kan het model daardoor zelf ook geen amount bepalen (amount None), dan
    # mag dat niet stilletjes als 'gelijk' tellen zoals bij 'scheutje' —
    # anders verdwijnt precies de leesfout die zichtbaar moet blijven.
    rijen = [{'naam': 'Gemalen komijnzaad', 'hoeveelheid': '% zakje(s)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'gemalen komijnzaad', 'amount': None, 'unit': 'zakje'})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '% zakje(s)'"


def test_stopwoord_koppelt_niet_los_van_de_echte_gedeelde_naam():
    # 'en' staat in beide rijnamen en weegt dus in beide even zwaar mee; alleen
    # het echte woord 'ui' hoort bij de juiste rij. Zonder stopwoordfilter is
    # het 1-1 gelijkspel en wint de eerste rij (fout); met filter wint 'Ui'.
    rijen = [{'naam': 'Prei en wortel', 'hoeveelheid': 'naar smaak', 'blok': 'kaart', 'y': 1},
             {'naam': 'Ui', 'hoeveelheid': '1 st', 'blok': 'kaart', 'y': 2}]
    r = _recept({'name': 'ui en look', 'amount': None, 'unit': ''})
    meldingen = controleer_tegen_tabel(r, rijen, '1+2')
    assert meldingen == ["Pagina's 1+2 (X): tabelrij 'Prei en wortel | naar smaak' ontbreekt in het concept."]
    assert r['ingredients'][0]['check'] == "tabel zegt '1 st'"


def test_unicode_numeral_glyph_geeft_check_geen_silent_pass():
    # D4-vangnet: '⅐' is een Unicode numeral glyph, geen echt woord. Kan het model
    # daardoor geen amount bepalen (amount None), dan mag dat niet stilletjes als
    # 'gelijk' tellen zoals bij 'scheutje' — anders verdwijnt de OCR-leesfout
    # die zichtbaar moet blijven. (Ook '①', '②', 'Ⅷ', '²' moeten dit vangnet triggeren.)
    rijen = [{'naam': 'komijn', 'hoeveelheid': '⅐ zakje(s)', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'komijn', 'amount': None, 'unit': ''})
    controleer_tegen_tabel(r, rijen, '1+2')
    assert r['ingredients'][0]['check'] == "tabel zegt '⅐ zakje(s)'"


def test_echt_woord_scheutje_krijgt_nog_steeds_geen_check():
    # Blijft werken: 'scheutje' is echt alfabetisch, dus woordhoeveelheid.
    rijen = [{'naam': 'melk', 'hoeveelheid': 'scheutje', 'blok': 'kaart', 'y': 1}]
    r = _recept({'name': 'melk', 'amount': None, 'unit': ''})
    assert controleer_tegen_tabel(r, rijen, '1+2') == []
    assert 'check' not in r['ingredients'][0]
