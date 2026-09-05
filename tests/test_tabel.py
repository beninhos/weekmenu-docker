"""Ingrediëntentabel van een receptkaart uit de woordcoördinaten van Vision."""
import json
import os

from weekmenu.services.tabel import _banden, _segmenten, tabelrijen, woordboxen

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'hellofresh_achterkant.json')


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
    # Naam en hoeveelheid staan in de OCR in verschillende paragrafen en een
    # paar pixels verschoven, maar op dezelfde regel: de reden van deze module.
    ann = {'pages': [{'blocks': [{'paragraphs': [
        {'words': [_woord('Sperziebonen', 100, 500, 26), _woord('Kokosmelk', 100, 560, 26)]},
        {'words': [_woord('200', 600, 493, 18), _woord('g', 660, 493, 18),
                   _woord('100', 600, 555, 18), _woord('ml', 660, 555, 18)]},
    ]}]}]}
    assert _teksten(_banden(woordboxen(ann))) == [['Sperziebonen', '200', 'g'], ['Kokosmelk', '100', 'ml']]


def test_banden_smelten_niet_samen_bij_dicht_op_elkaar_staande_regels():
    # Vier regels op 30 px afstand met letters van 26 px hoog: een band die
    # meegroeit met elk woord slokt ze alle vier op.
    woorden = []
    for i, t in enumerate(['een', 'twee', 'drie', 'vier']):
        woorden += _regel(t, 100, 500 + 30 * i, 26)
    assert _teksten(_banden(woordboxen(woorden and _annotatie(woorden)))) == [['een'], ['twee'], ['drie'], ['vier']]


def test_segmenten_splitsen_bij_elk_groot_gat():
    band = sorted(woordboxen(_annotatie(_regel('Halfkruimige aardappelen', 50, 500)
                                        + _regel('500 g', 460, 500)
                                        + _regel('Frietjes maken', 620, 500))),
                  key=lambda w: w['x0'])
    assert [' '.join(w['tekst'] for w in s) for s in _segmenten(band)] == \
        ['Halfkruimige aardappelen', '500 g', 'Frietjes maken']


def test_lopende_tekst_is_een_segment():
    band = sorted(woordboxen(_annotatie(_regel('Verwarm de oven voor op 220 graden', 600, 500))),
                  key=lambda w: w['x0'])
    assert len(_segmenten(band)) == 1


# ── tabelrijen ──────────────────────────────────────────────────────────

def _tabel(regels, x_naam=50, x_hoev=460, start_y=1100, stap=36):
    """regels: (naam, hoeveelheid|None, [extra tekst rechts]) per regel."""
    woorden, y = [], start_y
    for regel in regels:
        naam, hoev = regel[0], regel[1]
        rechts = regel[2] if len(regel) > 2 else None
        woorden += _regel(naam, x_naam, y)
        if hoev:
            woorden += _regel(hoev, x_hoev, y - 4, 18)
        if rechts:
            woorden += _regel(rechts, 620, y)
        y += stap
    return _annotatie(woorden)


def _kort(rijen):
    return [(r['naam'], r['hoeveelheid'], r['blok']) for r in rijen]


def test_tabelrijen_op_de_echte_hellofresh_achterkant():
    """De waarheid van de kaart (week 50 | 2020). Verwachting nooit aanpassen aan de uitvoer."""
    rijen, reden = tabelrijen(json.load(open(FIXTURE)))
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


def test_stappen_in_de_kolom_ernaast_horen_niet_bij_de_tabel():
    ann = _tabel([('Ui', '1 st', 'Verwarm de oven voor op 220'), ('Prei', '2 st', 'graden en snijd de ui'),
                  ('Feta', '100 g', 'in ringen.')])
    rijen, reden = tabelrijen(ann)
    assert reden is None and _kort(rijen) == [('Ui', '1 st', 'kaart'), ('Prei', '2 st', 'kaart'),
                                              ('Feta', '100 g', 'kaart')]


def test_stapnummer_tussen_de_rijen_telt_niet_mee():
    ann = _tabel([('Ui', '1 st'), ('3', None), ('Prei', '2 st'), ('Feta', '100 g')])
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_los_getal_naast_een_kop_is_geen_rij():
    # Op de kaart staat het stapnummer '4' op dezelfde hoogte als de kop
    # 'Voedingswaarden', maar ver buiten de hoeveelheidkolom.
    ann = _tabel([('Ui', '1 st'), ('Prei', '2 st'), ('Feta', '100 g'), ('Voedingswaarden', None, '4')])
    rijen, _ = tabelrijen(ann)
    assert [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta']


def test_allergeencodes_en_sterretjes_gaan_van_de_naam():
    ann = _tabel([('Pindakaas 5) 21) 22)', '2 kuipje'), ('Mayonaise* 3)', '40 g'), ('Ui', '1 st')])
    rijen, _ = tabelrijen(ann)
    assert [r['naam'] for r in rijen] == ['Pindakaas', 'Mayonaise', 'Ui']


def test_naam_over_twee_regels_wordt_een_rij_als_de_tweede_regel_klein_begint():
    ann = _tabel([('Ingrediënten voor 2 personen', None), ('Halfkruimige', None), ('aardappelen', '500 g'),
                  ('Ui', '1 st'), ('Prei', '2 st')])
    rijen, _ = tabelrijen(ann)
    assert _kort(rijen)[0] == ('Halfkruimige aardappelen', '500 g', 'kaart')
    assert len(rijen) == 3


def test_dubbel_breukteken_in_de_cel_wordt_een():
    ann = _tabel([('Zonnebloemolie', '½½⁄2 el'), ('Ui', '1 st'), ('Prei', '2 st')])
    rijen, _ = tabelrijen(ann)
    assert rijen[0]['hoeveelheid'] == '½ el'


def test_voorraadkop_zet_blok_en_is_zelf_geen_rij():
    ann = _tabel([('Ui', '1 st'), ('Prei', '2 st'), ('Feta', '100 g'), ('Zelf toevoegen', None),
                  ('Olijfolie', '1 el'), ('Peper en zout', 'naar smaak')])
    rijen, _ = tabelrijen(ann)
    assert _kort(rijen) == [('Ui', '1 st', 'kaart'), ('Prei', '2 st', 'kaart'), ('Feta', '100 g', 'kaart'),
                            ('Olijfolie', '1 el', 'voorraad'), ('Peper en zout', 'naar smaak', 'voorraad')]


def test_minder_dan_drie_rijen_is_geen_tabel():
    assert tabelrijen(_tabel([('Ui', '1 st'), ('Prei', '2 st')])) == (None, 'geen tabel')
    assert tabelrijen({}) == (None, 'geen tabel')


def test_voedingswaardentabel_wint_niet_van_de_ingredientenlijst():
    # Twee tabellen onder elkaar; de grootste is de ingrediëntenlijst.
    regels = [('Ui', '1 st'), ('Prei', '2 st'), ('Feta', '100 g'), ('Kip', '300 g'), ('Voedingswaarden', None)]
    ann = _tabel(regels + [('Energie (kJ/kcal)', None), ('Vetten (g)', None), ('Eiwit (g)', None)])
    # voedingswaarden krijgen hun getallen op een andere x
    extra = []
    for i, getal in enumerate(['4163/995', '60', '43']):
        extra += _regel(getal, 300, 1100 + 36 * (5 + i) - 4, 18)
    ann['pages'][0]['blocks'][0]['paragraphs'][0]['words'] += extra
    rijen, reden = tabelrijen(ann)
    assert reden is None and [r['naam'] for r in rijen] == ['Ui', 'Prei', 'Feta', 'Kip']


def test_meerdere_hoeveelheidkolommen_worden_geweigerd():
    # 2p en 4p naast elkaar: rechts van elke hoeveelheid nog een hoeveelheid.
    ann = _tabel([('Ui', '1 st', '2 st'), ('Prei', '2 st', '4 st'), ('Feta', '100 g', '200 g')])
    assert tabelrijen(ann) == (None, 'meerdere kolommen')
