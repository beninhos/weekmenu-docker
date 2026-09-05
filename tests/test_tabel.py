"""Ingrediëntentabel van een receptkaart uit de woordcoördinaten van Vision.

Drie echte achterkanten als waarheid (overgetypt van de kaart, nooit
aangepast aan de uitvoer): de 2020-kaart met één kolom, een scheef
gescande één-kolomkaart waar de hoeveelheden 1,5 rij lager staan dan de
namen, en een 1–6-personenkaart met zes kolommen.
"""
import json
import os

from weekmenu.services.tabel import _banden, _segmenten, tabelrijen, woordboxen

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _fixture(naam):
    return json.load(open(os.path.join(FIXTURES, naam)))


def _woord(tekst, x0, y0, hoogte=24):
    breedte = 14 * len(tekst)
    return {'symbols': [{'text': t} for t in tekst],
            'boundingBox': {'vertices': [{'x': x0, 'y': y0}, {'x': x0 + breedte, 'y': y0},
                                         {'x': x0 + breedte, 'y': y0 + hoogte}, {'x': x0, 'y': y0 + hoogte}]}}


def _annotatie(woorden):
    return {'pages': [{'blocks': [{'paragraphs': [{'words': woorden}]}]}]}


def _regel(tekst, x0, y0, hoogte=24):
    """Woorden van één tekstregel achter elkaar, met gewone spatiëring."""
    uit, x = [], x0
    for t in tekst.split():
        uit.append(_woord(t, x, y0, hoogte))
        x += 14 * len(t) + 12
    return uit


def _teksten(banden):
    return [[w['tekst'] for w in band] for band in banden]


def _kort(rijen):
    return [(r['naam'], r['hoeveelheid'], r['blok']) for r in rijen]


# ── woordboxen ──────────────────────────────────────────────────────────

def test_woordboxen_vullen_ontbrekende_nul_aan():
    # Vision laat x=0 of y=0 weg in de JSON.
    w = {'symbols': [{'text': 'A'}],
         'boundingBox': {'vertices': [{'y': 10}, {'x': 20, 'y': 10}, {'x': 20, 'y': 40}, {'y': 40}]}}
    box = woordboxen(_annotatie([w]))[0]
    assert (box['x0'], box['x1'], box['y0'], box['y1']) == (0, 20, 10, 40)
    assert box['tekst'] == 'A'


def test_woorden_zonder_box_worden_overgeslagen():
    assert woordboxen(_annotatie([{'symbols': [{'text': 'x'}]}])) == []


# ── banden en segmenten ─────────────────────────────────────────────────

def test_banden_groeperen_op_hoogte_ook_uit_verschillende_paragrafen():
    ann = {'pages': [{'blocks': [{'paragraphs': [
        {'words': [_woord('Sperziebonen', 100, 500, 26), _woord('Kokosmelk', 100, 560, 26)]},
        {'words': [_woord('200', 600, 493, 18), _woord('g', 660, 493, 18),
                   _woord('100', 600, 555, 18), _woord('ml', 660, 555, 18)]},
    ]}]}]}
    assert _teksten(_banden(woordboxen(ann))) == [['Sperziebonen', '200', 'g'], ['Kokosmelk', '100', 'ml']]


def test_banden_smelten_niet_samen_bij_dicht_op_elkaar_staande_regels():
    woorden = []
    for i, t in enumerate(['een', 'twee', 'drie', 'vier']):
        woorden += _regel(t, 100, 500 + 30 * i, 26)
    assert _teksten(_banden(woordboxen(_annotatie(woorden)))) == [['een'], ['twee'], ['drie'], ['vier']]


def test_segmenten_splitsen_bij_elk_groot_gat():
    band = sorted(woordboxen(_annotatie(_regel('Halfkruimige aardappelen', 50, 500)
                                        + _regel('500 g', 460, 500)
                                        + _regel('Frietjes maken', 620, 500))),
                  key=lambda w: w['x0'])
    assert [' '.join(w['tekst'] for w in s) for s in _segmenten(band)] == \
        ['Halfkruimige aardappelen', '500 g', 'Frietjes maken']


# ── tabelrijen: echte kaarten ───────────────────────────────────────────

def test_kaart_2020_met_een_kolom():
    rijen, reden = tabelrijen(_fixture('hellofresh_achterkant.json'))
    assert reden is None
    assert _kort(rijen) == [
        ('Halfkruimige aardappelen', '500 g', 'kaart'),
        ('Sperziebonen', '200 g', 'kaart'),
        ('Pindakaas', '2 kuipje', 'kaart'),
        ('Kokosmelk', '100 ml', 'kaart'),
        ('Gekruide runderburger', '2 st', 'kaart'),
        ('Komkommer', '1 st', 'kaart'),
        ('Ui', '1 st', 'kaart'),
        ('Mayonaise', '40 g', 'kaart'),
        ('Ketjap', '1 el', 'voorraad'),
        ('Olijfolie', '1 el', 'voorraad'),
        ('Zonnebloemolie', '½ el', 'voorraad'),
        ('Wittewijnazijn', '2 tl', 'voorraad'),
        ('Mosterd', '1 tl', 'voorraad'),
        ('Extra vierge olijfolie', 'naar smaak', 'voorraad'),
        ('Peper en zout', 'naar smaak', 'voorraad'),
    ]


def test_scheve_kaart_hoeveelheden_anderhalve_rij_lager_dan_de_namen():
    """Telefoonscan, +2,2° gedraaid, en de kaart drukt de hoeveelheden zelf al
    lager dan de namen: op y uitlijnen koppelt hier alles één rij verkeerd."""
    rijen, reden = tabelrijen(_fixture('hellofresh_scheef_achterkant.json'))
    assert reden is None
    assert _kort(rijen) == [
        ('Knoflookteen', '1 st', 'kaart'),
        ('Courgette', '½ st', 'kaart'),
        ('Gesneden ui', '75 g', 'kaart'),
        ('Paprikareepjes', '100 g', 'kaart'),
        ('Semi-gedroogde tomaten', '35 g', 'kaart'),
        ('Italiaanse kruiden', '3 tl', 'kaart'),
        ('Kalkoenmedaillonstukjes', '120 g', 'kaart'),
        ('Snelkook fusilli', '180 g', 'kaart'),
        ('Kookroom', '200 ml', 'kaart'),
        ('Geraspte Italiaanse kaas', '25 g', 'kaart'),
        ('Olijfolie', '1 el', 'voorraad'),
        ('Roomboter', '1 el', 'voorraad'),
        ('Groentebouillonblokje', '½ st', 'voorraad'),
        ('Peper en zout', 'naar smaak', 'voorraad'),
    ]


def test_meerkoloms_kaart_kiest_de_kolom_van_het_aantal_personen():
    rijen, reden = tabelrijen(_fixture('hellofresh_meerkoloms_achterkant.json'), personen=2)
    assert reden is None
    assert _kort(rijen) == [
        ('Zoete aardappel', '500 g', 'kaart'),
        ('Kruimige aardappelen', '200 g', 'kaart'),
        ('Knoflookteen', '1 st', 'kaart'),
        ('Rode peper', '1 st', 'kaart'),
        ('Bosui', '4 st', 'kaart'),
        ('Snijbonen', '300 g', 'kaart'),
        ('Pompoenpitten', '10 g', 'kaart'),
        ('Duitse biefstuk', '2 st', 'kaart'),
        ('Groentebouillon', '800 ml', 'voorraad'),
        ('Olijfolie', '1 el', 'voorraad'),
        ('Roomboter', '1 el', 'voorraad'),
        ('Melk', 'scheutje', 'voorraad'),
        ('Peper & zout', 'naar smaak', 'voorraad'),
    ]


def test_meerkoloms_kaart_zonder_of_met_onbekend_aantal_personen_wordt_geweigerd():
    ann = _fixture('hellofresh_meerkoloms_achterkant.json')
    assert tabelrijen(ann) == (None, 'meerdere kolommen')
    assert tabelrijen(ann, personen=7) == (None, 'meerdere kolommen')


# ── tabelrijen: synthetisch ─────────────────────────────────────────────

def _tabel(regels, x_naam=50, x_hoev=460, start_y=1100, stap=36, verschuiving=0):
    """regels: (naam, hoeveelheid|None[, tekst rechts]). `verschuiving` zet de
    hoeveelheden zoveel px lager dan hun naam (zoals de scheve kaart)."""
    woorden, y = [], start_y
    for regel in regels:
        naam, hoev = regel[0], regel[1]
        rechts = regel[2] if len(regel) > 2 else None
        woorden += _regel(naam, x_naam, y)
        if hoev:
            woorden += _regel(hoev, x_hoev, y - 4 + verschuiving, 18)
        if rechts:
            woorden += _regel(rechts, 620, y)
        y += stap
    return _annotatie(woorden)


DRIE = [('Ui', '1 st'), ('Prei', '2 st'), ('Feta', '100 g')]


def test_kop_en_tabelkop_horen_niet_bij_de_namen():
    ann = _tabel([('Ingrediënten voor 2 personen', None)] + DRIE)
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_hoeveelheden_die_een_rij_lager_staan_koppelen_op_volgorde():
    ann = _tabel(DRIE + [('Kip', '300 g')], verschuiving=40)
    rijen, reden = tabelrijen(ann)
    assert reden is None
    assert _kort(rijen) == [('Ui', '1 st', 'kaart'), ('Prei', '2 st', 'kaart'),
                            ('Feta', '100 g', 'kaart'), ('Kip', '300 g', 'kaart')]


def test_stappen_in_de_kolom_ernaast_horen_niet_bij_de_tabel():
    ann = _tabel([('Ui', '1 st', 'Verwarm de oven voor op 220'), ('Prei', '2 st', 'graden en snijd de ui'),
                  ('Feta', '100 g', '30-35 minuten in de oven.')])
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_stapnummer_en_voetnoot_tellen_niet_mee():
    ann = _tabel([('Ui', '1 st'), ('3', None), ('Prei', '2 st'), ('Feta', '100 g'),
                  ('* in de koelkast bewaren', None)])
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_allergeencodes_sterretjes_en_spaties_rond_koppeltekens():
    ann = _tabel([('Pindakaas 5 ) 21 ) 22 )', '2 kuipje'), ('Mayonaise * 3 )', '40 g'),
                  ('Semi - gedroogde tomaten *', '35 g')])
    rijen, _ = tabelrijen(ann)
    assert [r['naam'] for r in rijen] == ['Pindakaas', 'Mayonaise', 'Semi-gedroogde tomaten']


def test_naam_over_twee_regels_wordt_een_rij_als_de_tweede_regel_klein_begint():
    ann = _tabel([('Halfkruimige', None), ('aardappelen', '500 g'), ('Ui', '1 st'), ('Prei', '2 st')])
    rijen, reden = tabelrijen(ann)
    assert reden is None
    assert _kort(rijen)[0] == ('Halfkruimige aardappelen', '500 g', 'kaart') and len(rijen) == 3


def test_hoeveelheid_wordt_opgeschoond():
    ann = _tabel([('Zonnebloemolie', '½½⁄2 el'), ('Dille', '5g'), ('Mosterd', '6tl')])
    rijen, _ = tabelrijen(ann)
    assert [r['hoeveelheid'] for r in rijen] == ['½ el', '5 g', '6 tl']


def test_voorraadkop_zet_blok_en_is_zelf_geen_rij():
    ann = _tabel(DRIE + [('Zelf toevoegen', None), ('Olijfolie', '1 el'), ('Melk', 'scheutje'),
                         ('Peper en zout', 'naar smaak')])
    rijen, reden = tabelrijen(ann)
    assert reden is None
    assert _kort(rijen) == [('Ui', '1 st', 'kaart'), ('Prei', '2 st', 'kaart'), ('Feta', '100 g', 'kaart'),
                            ('Olijfolie', '1 el', 'voorraad'), ('Melk', 'scheutje', 'voorraad'),
                            ('Peper en zout', 'naar smaak', 'voorraad')]


def test_minder_dan_drie_rijen_is_geen_tabel():
    assert tabelrijen(_tabel(DRIE[:2])) == (None, 'geen tabel')
    assert tabelrijen({}) == (None, 'geen tabel')


def test_telling_die_niet_klopt_wordt_geweigerd():
    # Een naam zonder hoeveelheid die niet als vervolgregel te herkennen is:
    # liever weigeren dan alles daaronder één rij verschuiven.
    ann = _tabel(DRIE + [('Kip', None), ('Prei', '2 st')])
    assert tabelrijen(ann) == (None, 'telling klopt niet: 5 namen, 4 hoeveelheden')


def test_voedingswaardentabel_wint_niet_van_de_ingredientenlijst():
    regels = DRIE + [('Kip', '300 g'), ('Voedingswaarden', None), ('Energie (kJ/kcal)', None),
                     ('Vetten (g)', None), ('Eiwit (g)', None)]
    ann = _tabel(regels)
    extra = []
    for i, getal in enumerate(['4163/995', '60', '43']):
        extra += _regel(getal, 300, 1100 + 36 * (5 + i) - 4, 18)
    ann['pages'][0]['blocks'][0]['paragraphs'][0]['words'] += extra
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta', 'Kip']


def _meerkoloms(personen_koppen, regels, x_kolom=(420, 480, 540, 600), start_y=1100, stap=36):
    """regels: (naam, [cel per kolom]). Kopregel met '1P 2P ...' erboven."""
    woorden = []
    for kop, x in zip(personen_koppen, x_kolom):
        woorden.append(_woord(kop, x, start_y - stap, 18))
    y = start_y
    for naam, cellen in regels:
        woorden += _regel(naam, 50, y)
        for cel, x in zip(cellen, x_kolom):
            if cel:
                woorden.append(_woord(cel, x, y - 4, 18))
        y += stap
    return _annotatie(woorden)


def test_meerkoloms_eenheid_uit_de_naam_en_kolom_op_personen():
    ann = _meerkoloms(['1P', '2P', '3P', '4P'], [
        ('Zoete aardappel ( g )', ['250', '500', '750', '1000']),
        ('Bosui ( st )', ['2', '4', '6', '8']),
        ('Biefstuk ( st )', ['1', '2', '3', '4']),
    ])
    rijen, reden = tabelrijen(ann, personen=3)
    assert reden is None
    assert _kort(rijen) == [('Zoete aardappel', '750 g', 'kaart'), ('Bosui', '6 st', 'kaart'),
                            ('Biefstuk', '3 st', 'kaart')]


def test_meerkoloms_cel_zonder_getal_geldt_voor_elke_kolom():
    ann = _meerkoloms(['1P', '2P', '3P', '4P'], [
        ('Bosui ( st )', ['2', '4', '6', '8']),
        ('Biefstuk ( st )', ['1', '2', '3', '4']),
        ('Melk', ['', 'scheutje', '', '']),
        ('Peper & zout', ['', 'naar smaak', '', '']),
    ])
    rijen, reden = tabelrijen(ann, personen=4)
    assert reden is None
    assert _kort(rijen)[2:] == [('Melk', 'scheutje', 'kaart'), ('Peper & zout', 'naar smaak', 'kaart')]


def test_meerkoloms_zonder_personen_wordt_geweigerd():
    ann = _meerkoloms(['1P', '2P', '3P', '4P'], [
        ('Bosui ( st )', ['2', '4', '6', '8']),
        ('Biefstuk ( st )', ['1', '2', '3', '4']),
        ('Ui ( st )', ['1', '1', '2', '2']),
    ])
    assert tabelrijen(ann) == (None, 'meerdere kolommen')
    assert tabelrijen(ann, personen=5) == (None, 'meerdere kolommen')
