"""Bereidingstekst knippen op ankers: de tekst komt uit de OCR, nooit uit het model."""
from weekmenu.services.ankers import knip_stappen, normaliseer
from weekmenu.services.dump import parse_batch_response

PAGINA = """KIP MET RIJST
2 kipfilets
½ bosje koriander
AAN DE SLAG
Snijd de kip in reepjes en bak ze goud-
bruin in de pan ⚫ Kook intussen de rijst
volgens de aanwijzingen op de verpakking
• Serveer de kip op de rijst en strooi er
de koriander over
32 KIP
"""


def test_exacte_ankers_knippen_letterlijk():
    stappen = [
        {'start': 'Snijd de kip in reepjes', 'end': 'in de pan'},
        {'start': 'Kook intussen de rijst', 'end': 'op de verpakking'},
        {'start': 'Serveer de kip', 'end': 'de koriander over'},
    ]
    tekst, meldingen = knip_stappen(PAGINA, stappen)
    assert meldingen == []
    assert tekst.split('\n') == [
        'Snijd de kip in reepjes en bak ze goud-bruin in de pan',
        'Kook intussen de rijst volgens de aanwijzingen op de verpakking',
        'Serveer de kip op de rijst en strooi er de koriander over',
    ]


def test_afbreking_wordt_samengevoegd_als_het_woord_elders_voorkomt():
    corpus = PAGINA + '\nbak ze goudbruin en gaar'
    assert 'goudbruin in de pan' in normaliseer(PAGINA, corpus)
    # zonder bewijs blijft het koppelteken zichtbaar staan
    assert 'goud-bruin' in normaliseer(PAGINA)
    # een weggelaten deel vóór 'of'/'en' houdt zijn koppelteken en spatie
    assert normaliseer('1 mok zilvervlies-\nof basmatirijst') == '1 mok zilvervlies- of basmatirijst'


def test_gat_tussen_twee_stappen_gaat_bij_de_vorige():
    # Het model liet 'volgens de aanwijzingen op de verpakking' vallen.
    stappen = [
        {'start': 'Snijd de kip', 'end': 'in de pan'},
        {'start': 'Kook intussen', 'end': 'intussen de rijst'},
        {'start': 'Serveer de kip', 'end': 'koriander over'},
    ]
    tekst, meldingen = knip_stappen(PAGINA, stappen)
    assert meldingen == []
    assert 'volgens de aanwijzingen op de verpakking' in tekst.split('\n')[1]
    assert tekst.count('verpakking') == 1


def test_ingredientenlijst_dwars_door_een_stap_wordt_weggelaten():
    pagina = ("1 gedroogde peper Verkruimel de peper in de blender en giet er water\n"
              "2 lente-uitjes\n1 grote rijpe tomaat\nFajita's\n½ bosje verse koriander\n"
              "32 KIP\n"
              "bij om ze te laten wellen Maak de lente-uitjes schoon en doe ze bij de tomaat\n")
    stappen = [{'start': 'Verkruimel de peper', 'end': 'bij de tomaat'}]
    namen = ['gedroogde peper', 'lente-uitjes', 'rijpe tomaat', 'verse koriander']
    tekst, meldingen = knip_stappen(pagina, stappen, ingredienten=namen)
    # De melding noemt wat er weg is: de zekere ingrediëntregels geteld, de rest letterlijk.
    assert meldingen == ['uit de bereiding weggelaten: 3 ingrediëntregels; op vorm: "Fajita\'s", \'32 KIP\'']
    assert tekst == ('Verkruimel de peper in de blender en giet er water '
                     'bij om ze te laten wellen Maak de lente-uitjes schoon en doe ze bij de tomaat')


def test_ingredientregel_die_aan_een_stapregel_vastzit_gaat_eraf():
    pagina = ("Voeg wanneer de linzen koken en de\n"
              "1 handvol verse tijm, rozemarijn en/ spinazie geslonken is, peper en zout naar smaak toe\n"
              "of laurier\n4 plakken gerookte pancetta\n1 bundel groene asperges (300 g)\nVoor erbij\n"
              "Doe de pancetta en de asperges in de koekenpan en bak ze goudbruin\n")
    stappen = [{'start': 'Voeg wanneer de linzen', 'end': 'bak ze goudbruin'}]
    namen = ['verse tijm, rozemarijn en/ of laurier', 'gerookte pancetta', 'groene asperges']
    tekst, meldingen = knip_stappen(pagina, stappen, ingredienten=namen)
    assert meldingen == ["uit de bereiding weggelaten: 2 ingrediëntregels; op vorm: 'of laurier', "
                         "'Voor erbij', '1 handvol verse tijm, rozemarijn en/'"]
    assert tekst == ('Voeg wanneer de linzen koken en de spinazie geslonken is, peper en zout naar '
                     'smaak toe Doe de pancetta en de asperges in de koekenpan en bak ze goudbruin')


def test_een_losse_hoeveelheidsregel_in_een_stap_blijft_staan():
    # Eén regel is geen lijst: 'sap van 1 limoen' op een eigen regel hoort bij de stap.
    pagina = "Knijp er het\n1 limoen boven uit\nen roer door\n"
    stappen = [{'start': 'Knijp er het', 'end': 'roer door'}]
    tekst, meldingen = knip_stappen(pagina, stappen, ingredienten=['limoen'])
    assert meldingen == []
    assert tekst == 'Knijp er het 1 limoen boven uit en roer door'


def test_fuzzy_anker_vangt_een_tekenfout():
    stappen = [{'start': 'Snijd de kip in reepjes', 'end': 'de aanwijzingen op de verpaking'}]
    tekst, meldingen = knip_stappen(PAGINA, stappen)
    assert tekst.endswith('op de verpakking')
    # wat na dit (enige) eindanker komt is nog bereiding, en dat wordt gemeld
    assert len(meldingen) == 1 and 'na de laatste stap' in meldingen[0]


def test_ontbrekend_anker_knipt_ruim_en_meldt():
    stappen = [
        {'start': 'Snijd de kip', 'end': 'in de pan'},
        {'start': 'Dit staat nergens op de pagina', 'end': 'op de verpakking'},
        {'start': 'Serveer de kip', 'end': 'koriander over'},
    ]
    tekst, meldingen = knip_stappen(PAGINA, stappen)
    assert len(meldingen) == 1 and 'beginanker niet gevonden' in meldingen[0]
    regels = tekst.split('\n')
    assert len(regels) == 3
    assert regels[1].endswith('op de verpakking')      # ruim geknipt, niets kwijt
    assert 'Serveer de kip' in regels[2]


def test_geen_enkel_anker_geeft_lege_tekst_en_melding():
    tekst, meldingen = knip_stappen(PAGINA, [{'start': 'xyz', 'end': 'abc'}])
    assert tekst == '' and 'geen enkel anker' in meldingen[0]
    tekst, meldingen = knip_stappen(PAGINA, [])
    assert tekst == '' and meldingen == ['geen bereidingsstappen aangewezen']


def test_herhaald_anker_pakt_de_volgende_niet_de_eerste():
    pagina = "Snijd de ui en bak hem\nVoeg de tomaat toe\nSnijd de ui in ringen voor erbij\n"
    stappen = [
        {'start': 'Snijd de ui', 'end': 'bak hem'},
        {'start': 'Voeg de tomaat', 'end': 'tomaat toe'},
        {'start': 'Snijd de ui', 'end': 'voor erbij'},
    ]
    tekst, meldingen = knip_stappen(pagina, stappen)
    assert meldingen == []
    assert tekst.split('\n') == ['Snijd de ui en bak hem', 'Voeg de tomaat toe',
                                 'Snijd de ui in ringen voor erbij']


def test_parse_batch_response_knipt_uit_de_paginatekst(app):
    antwoord = ('[{"title": "Kip met rijst", "photo_page": 1, "ingredients": [], '
                '"steps": [{"start": "Snijd de kip", "end": "in de pan"}]}]')
    recepten = parse_batch_response(antwoord, page_texts=[PAGINA])
    assert recepten[0]['instructions'] == 'Snijd de kip in reepjes en bak ze goud-bruin in de pan'
    assert len(recepten[0]['meldingen']) == 1
    assert 'na de laatste stap' in recepten[0]['meldingen'][0]
    assert 'verpakking' in recepten[0]['meldingen'][0]


def test_parse_batch_response_zonder_paginatekst_meldt(app):
    antwoord = ('[{"title": "Kip", "photo_page": 1, "ingredients": [], '
                '"steps": [{"start": "Snijd de kip", "end": "in de pan"}]}]')
    recepten = parse_batch_response(antwoord)
    assert recepten[0]['instructions'] == ''
    assert recepten[0]['meldingen'] and 'geen paginatekst' in recepten[0]['meldingen'][0]


def test_oud_antwoordformaat_blijft_werken(app):
    antwoord = '[{"title": "Kip", "photo_page": 1, "ingredients": [], "instructions": "Doe iets."}]'
    recepten = parse_batch_response(antwoord, page_texts=[PAGINA])
    assert recepten[0]['instructions'] == 'Doe iets.'
    assert recepten[0]['meldingen'] == []


def test_genummerde_stappen_zijn_geen_ingredientenlijst():
    """'2 Bak de kipfilet gaar' begint met een cijfer, net als '2 kipfilets'. Toch weg? Nooit."""
    pagina = ("Bereiding\n1 Snipper de rode ui fijn\n2 Bak de kipfilet gaar\n"
              "3 Voeg de bloem toe en roer\n"
              "4 Serveer met verse peterselie erover en breng op smaak met peper en zout\n")
    namen = ['rode ui', 'kipfilet', 'bloem', 'verse peterselie']
    tekst, meldingen = knip_stappen(pagina, [{'start': 'Snipper de rode ui', 'end': 'peper en zout'}],
                                    ingredienten=namen)
    assert meldingen == []
    assert 'Bak de kipfilet gaar' in tekst and 'Voeg de bloem toe' in tekst


def test_oplopende_nummering_zonder_hoofdletter_blijft_ook_staan():
    pagina = ("Bereiding\n1 snipper de rode ui fijn\n2 bak de kipfilet gaar\n3 voeg de bloem toe\n"
              "4 serveer met verse peterselie erover en breng op smaak met peper en zout\n")
    tekst, meldingen = knip_stappen(pagina, [{'start': 'snipper de rode ui', 'end': 'peper en zout'}],
                                    ingredienten=['rode ui', 'kipfilet', 'bloem', 'verse peterselie'])
    assert meldingen == []
    assert 'bak de kipfilet gaar' in tekst and 'voeg de bloem toe' in tekst


def test_hele_ingredientnaam_in_een_bereidingsregel_wordt_niet_afgeknipt():
    # '1 el extra vierge olijfolie erbij en roer' is een zin, geen geplakte ingrediëntregel:
    # de naam loopt op deze regel af. Alleen een afgebroken naam ('en/' + 'of laurier') mag eraf.
    pagina = ("Zet de pan op het vuur en begin\n"
              "1 el extra vierge olijfolie erbij en roer alles door tot het glad is\n"
              "2 rode uien\n1 teen knoflook\n200 g bloem\nVoor erbij\n"
              "Serveer met brood en ga aan tafel\n")
    namen = ['extra vierge olijfolie', 'rode uien', 'teen knoflook', 'bloem']
    tekst, meldingen = knip_stappen(pagina, [{'start': 'Zet de pan', 'end': 'ga aan tafel'}],
                                    ingredienten=namen)
    assert 'extra vierge olijfolie erbij en roer' in tekst
    assert '2 rode uien' not in tekst


def test_tabel_in_een_gat_gaat_eruit_de_tip_en_de_kop_blijven():
    """HelloFresh: tussen twee stappen staat een tip, dan vijftig regels tabel, dan de kop van de volgende stap."""
    tabel = "\n".join(["5", "6", "Gekruide runderburger", "2 st", "Komkommer", "1 st", "Ui", "1 st",
                       "Mayonaise 3) 10) 19) 22)", "40 g", "Zelf toevoegen", "Ketjap", "1 el",
                       "Peper en zout", "Voedingswaarden", "Per portie", "Energie (kJ/kcal)",
                       "4163/995", "Vetten (g)", "60", "8", "Allergenen:", "Noten"])
    pagina = ("Voeg de pindakaas toe aan een steelpan en breng aan de kook.\n"
              "Tip: Voeg eventueel extra melk of water toe als de\n"
              "pindasaus te dik wordt en breng verder op smaak\n"
              "met sambal en/of ketchup.\n" + tabel + "\n"
              "Hamburgers bakken\n"
              "Verhit de olie in een koekenpan en bak de hamburger gaar.\n")
    stappen = [{'start': 'Voeg de pindakaas', 'end': 'aan de kook.'},
               {'start': 'Verhit de olie', 'end': 'hamburger gaar.'}]
    tekst, meldingen = knip_stappen(pagina, stappen)
    stap1, stap2 = tekst.split('\n')
    assert 'Tip: Voeg eventueel extra melk' in stap1 and 'met sambal en/of ketchup.' in stap1
    assert 'Hamburgers bakken' in stap1                 # kort, vlak na het blok: kan een zinstaart zijn
    assert 'Gekruide runderburger' not in tekst and 'Voedingswaarden' not in tekst
    assert stap2 == 'Verhit de olie in een koekenpan en bak de hamburger gaar.'
    assert len(meldingen) == 1 and meldingen[0].startswith('uit de bereiding weggelaten: op vorm:')
    assert "'Gekruide runderburger'" in meldingen[0]


def test_los_stapnummer_in_een_gat_blijft_staan():
    # Eén meubilairregel is geen tabel; die weghalen op vorm alleen is het niet waard.
    pagina = ("Bak de frietjes tot ze goudbruin zijn.\n4\nBoontjes koken\n"
              "Kook de boontjes in ruim water gaar.\n")
    stappen = [{'start': 'Bak de frietjes', 'end': 'goudbruin zijn.'},
               {'start': 'Kook de boontjes', 'end': 'water gaar.'}]
    tekst, meldingen = knip_stappen(pagina, stappen)
    assert meldingen == []
    assert tekst.split('\n')[0] == 'Bak de frietjes tot ze goudbruin zijn. 4 Boontjes koken'


def test_bereidingszin_na_het_laatste_anker_wordt_gemeld_paginavoet_niet():
    pagina = ("Rooster de kip een uur tot alles gaar is.\n"
              "Hussel de groenten voor het opscheppen nog even goed door het vocht.\n"
              "CALORIEEN 467 kcal VET 9,6 g\n")
    tekst, meldingen = knip_stappen(pagina, [{'start': 'Rooster de kip', 'end': 'alles gaar is.'}])
    assert tekst == 'Rooster de kip een uur tot alles gaar is.'
    assert len(meldingen) == 1
    assert "'Hussel de groenten voor het opscheppen nog even" in meldingen[0]
    # alleen paginavoet erna: niets te melden
    tekst, meldingen = knip_stappen("Rooster de kip een uur tot alles gaar is.\n32 KIP\n",
                                    [{'start': 'Rooster de kip', 'end': 'alles gaar is.'}])
    assert meldingen == []


def test_niet_tekstueel_anker_laat_de_batch_niet_omvallen():
    for raar in (5, ['a', 'b'], {'x': 1}, None, 3.5):
        tekst, meldingen = knip_stappen(PAGINA, [{'start': raar, 'end': 'in de pan'},
                                                 {'start': 'Kook intussen', 'end': 'op de verpakking'}])
        assert 'Kook intussen de rijst' in tekst
        assert any('beginanker niet gevonden' in m for m in meldingen)


def test_dezelfde_ankers_twee_keer_geven_de_tekst_niet_twee_keer():
    stap = {'start': 'Snijd de kip in reepjes', 'end': 'in de pan'}
    tekst, _ = knip_stappen(PAGINA, [stap, stap, stap])
    assert tekst.count('Snijd de kip in reepjes') == 1


def test_antwoord_zonder_stappen_en_zonder_tekst_wordt_gemeld(app):
    antwoord = '[{"title": "Kip", "photo_page": 1, "ingredients": []}]'
    recepten = parse_batch_response(antwoord, page_texts=[PAGINA])
    assert recepten[0]['instructions'] == ''
    assert recepten[0]['meldingen'] == ['geen bereidingsstappen aangewezen']
