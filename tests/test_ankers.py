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
    assert meldingen == ['5 ingrediëntregels die door de bereiding heen liepen zijn weggelaten']
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
    assert meldingen == ['5 ingrediëntregels die door de bereiding heen liepen zijn weggelaten']
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
    assert meldingen == []
    assert tekst.endswith('op de verpakking')


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
    assert recepten[0]['meldingen'] == []


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
