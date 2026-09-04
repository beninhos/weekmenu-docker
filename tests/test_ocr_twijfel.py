"""Vision's eigen zekerheid als markering voor een ½ die als cijfer is gelezen.

Gemeten op 22 kookboekpagina's: het breukteken scoort 0,19–0,39, een echt cijfer
minstens 0,81, en de twee missers ('2 theelepel', '12 komkommer') 0,49 en 0,31.
"""
from weekmenu.services.dump import _markeer_twijfels
from weekmenu.services.ocr import onzekere_hoeveelheden


def _woord(tekst, zekerheden, einde=None):
    symbols = [{'text': t, 'confidence': c} for t, c in zip(tekst, zekerheden)]
    if einde:
        symbols[-1]['property'] = {'detectedBreak': {'type': einde}}
    return {'symbols': symbols}


def _annotatie(regels):
    """regels: lijst van lijsten (tekst, zekerheden) per woord."""
    woorden = []
    for regel in regels:
        for i, (tekst, zk) in enumerate(regel):
            woorden.append(_woord(tekst, zk, 'LINE_BREAK' if i == len(regel) - 1 else 'SPACE'))
    return {'pages': [{'blocks': [{'paragraphs': [{'words': woorden}]}]}]}


def test_onzeker_begingetal_wordt_gemarkeerd_zeker_getal_niet():
    ann = _annotatie([
        [('2', [0.49]), ('theelepel', [0.98] * 9), ('komijnzaad', [0.97] * 10)],
        [('12', [0.31, 0.46]), ('komkommer', [0.99] * 9)],
        [('200', [0.97, 0.96, 0.98]), ('g', [0.95]), ('feta', [0.99] * 4)],
        [('½', [0.30]), ('bosje', [0.9] * 5), ('koriander', [0.9] * 9)],
    ])
    uit = onzekere_hoeveelheden(ann)
    assert [(t['regel'], t['cijfer'], t['zekerheid']) for t in uit] == [
        ('2 theelepel komijnzaad', '2', 0.49),
        ('12 komkommer', '12', 0.31),
    ]


def test_los_cijfer_in_de_marge_telt_niet():
    # Een als '0' gelezen vlekje aan de paginarand, en een paginanummer:
    # geen vervolgwoord, dus geen hoeveelheid.
    ann = _annotatie([[('0', [0.2])], [('44', [0.5, 0.5])]])
    assert onzekere_hoeveelheden(ann) == []


def test_cijfer_midden_in_regel_telt_niet():
    ann = _annotatie([[('sap', [0.9] * 3), ('van', [0.9] * 3), ('1', [0.3]), ('limoen', [0.9] * 6)]])
    assert onzekere_hoeveelheden(ann) == []


def test_lege_annotatie():
    assert onzekere_hoeveelheden({}) == []


def test_twijfel_komt_op_het_juiste_ingredient():
    recipes = [{'photo_page': 5, 'ingredients': [
        {'name': 'gemengde bonen', 'amount': 400, 'unit': 'g'},
        {'name': 'komijnzaad', 'amount': 2, 'unit': 'tl'},
    ]}]
    twijfels = [[], [], [], [], [{'regel': '2 theelepel komijnzaad', 'cijfer': '2', 'zekerheid': 0.49}]]
    meldingen = _markeer_twijfels(recipes, twijfels)
    assert meldingen == []
    assert 'check' not in recipes[0]['ingredients'][0]
    assert recipes[0]['ingredients'][1]['check'] == "Vision las '2' met 49% zekerheid; mogelijk een breukteken (½)"


def test_twijfel_zonder_ingredient_wordt_een_melding():
    recipes = [{'photo_page': 1, 'ingredients': [{'name': 'feta', 'amount': 20, 'unit': 'g'}]}]
    twijfels = [[{'regel': '12 komkommer', 'cijfer': '12', 'zekerheid': 0.31}]]
    meldingen = _markeer_twijfels(recipes, twijfels)
    assert len(meldingen) == 1
    assert "Pagina 1" in meldingen[0] and "'12 komkommer'" in meldingen[0]
    assert 'check' not in recipes[0]['ingredients'][0]


def test_eol_sure_space_is_ook_een_regeleinde():
    # Vision markeert een regeleinde als LINE_BREAK óf EOL_SURE_SPACE; beide moeten knippen.
    woorden = [_woord('2', [0.4], 'EOL_SURE_SPACE'), _woord('theelepel', [0.9] * 9, 'LINE_BREAK'),
               _woord('12', [0.3, 0.4], 'SPACE'), _woord('komkommer', [0.9] * 9, 'EOL_SURE_SPACE')]
    ann = {'pages': [{'blocks': [{'paragraphs': [{'words': woorden}]}]}]}
    uit = onzekere_hoeveelheden(ann)
    # '2' staat alleen op zijn regel (geen vervolgwoord), '12 komkommer' wel
    assert [(t['regel'], t['cijfer']) for t in uit] == [('12 komkommer', '12')]


def test_bovenrand_van_de_drempel():
    # Het laagste echte cijfer op de meetlat scoorde 0,81; het randartefact '0' 0,72 maar zonder vervolgwoord.
    ann = _annotatie([
        [('1', [0.81]), ('wortel', [0.95] * 6)],
        [('0', [0.72])],
        [('2', [0.60]), ('limoenen', [0.95] * 8)],
    ])
    assert onzekere_hoeveelheden(ann) == []
