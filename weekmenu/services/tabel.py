"""Ingrediëntentabel van een receptkaart uit de woordcoördinaten van Vision.

In de platte OCR-tekst valt zo'n tabel uit elkaar: eerst een blok namen, dan
een blok hoeveelheden, met stapnummers ertussen en de laatste hoeveelheden
pas na de kop 'Voedingswaarden'. Het model maakte daar op de ene kaart die
we hadden 14 van de 15 rijen goed van — maar een hoeveelheid aan de
verkeerde naam is in de tekst niet te zien. Geometrisch is de tabel wél
intact: naam en hoeveelheid staan op dezelfde hoogte. Deze module leest de
rijen dus uit de boxen die Vision toch al meegeeft, en geeft het model
schone regels 'naam | hoeveelheid'.

Alles hier is merkloos. Wat de HelloFresh-achterkant leerde en waar de
stappen hieronder op zijn gebouwd:

* De stappen staan in kolommen náást de tabel, op dezelfde hoogte. Een
  regel is dus geen rij; een regel valt in segmenten (woorden met gewone
  spatiëring ertussen), en een tabelrij is een segment met letters met
  direct rechts ervan een segment dat op een hoeveelheid lijkt.
* Losse stapnummers ('4', '5') staan ook rechts van tekst ('Voedingswaarden').
  De echte hoeveelheden staan allemaal in één smalle kolom; de kolom met
  de meeste kandidaten is de hoeveelheidkolom, de rest valt af.
* Een band mag niet meegroeien met elk woord dat erbij komt: regels op
  30 px afstand smelten dan samen tot één band over de halve pagina.
"""
import re
from statistics import median

from weekmenu.services.kaartsignaturen import is_voorraadkop

# Een kolomgrens is een gat van minstens zoveel maal de woordhoogte; kleiner
# is gewone spatiëring tussen woorden.
_GAT_FACTOR = 1.5
# Een woord hoort bij een band als het minstens zoveel van zijn eigen hoogte
# overlapt met de kern van de band. Ruim genomen: op de kaart staat de
# hoeveelheid ~10 px hoger dan de naam en overlapt maar 5 van 17 px.
_BAND_FACTOR = 0.2
# Hoeveelheden die zoveel maal de woordhoogte van de hoeveelheidkolom af
# staan horen er niet bij (stapnummers, een tweede tabel). Op de kaart staan
# de echte hoeveelheden binnen 2 woordhoogtes van elkaar, de voedings-
# waardenkolom staat er 4 vanaf.
_KOLOM_FACTOR = 2.5
# Een hoeveelheidcel is kort ('200 g', 'naar smaak'); een stapregel die
# toevallig met een getal begint ('180 graden. Schud...') is dat niet.
_MAX_CELWOORDEN = 3
_MIN_RIJEN = 3
_FRACTIES = '½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞'
# Een rechtercel is een hoeveelheid als hij met een cijfer of breuk begint,
# of 'naar smaak' is. Meer hoeft niet: de linkercel doet de rest.
_HOEVEELHEID = re.compile(rf'^(\d|[{_FRACTIES}]|naar smaak)', re.IGNORECASE)


def woordboxen(annotation):
    """Alle woorden van een fullTextAnnotation als {tekst, x0, x1, y0, y1}.

    Vision laat nulwaarden weg in de JSON: een vertex {'y': 837} betekent
    x = 0. Woorden zonder vier hoekpunten worden overgeslagen.
    """
    boxen = []
    for page in annotation.get('pages') or []:
        for block in page.get('blocks') or []:
            for paragraph in block.get('paragraphs') or []:
                for word in paragraph.get('words') or []:
                    vertices = (word.get('boundingBox') or {}).get('vertices') or []
                    tekst = ''.join(s.get('text', '') for s in word.get('symbols') or [])
                    if len(vertices) != 4 or not tekst:
                        continue
                    xs = [v.get('x', 0) for v in vertices]
                    ys = [v.get('y', 0) for v in vertices]
                    boxen.append({'tekst': tekst, 'x0': min(xs), 'x1': max(xs),
                                  'y0': min(ys), 'y1': max(ys)})
    return boxen


def _mid(w):
    return (w['y0'] + w['y1']) / 2


def _hoogte(w):
    return w['y1'] - w['y0']


def _banden(boxen):
    """Woorden gegroepeerd tot regels; per band gesorteerd op x.

    De kern van een band is het gemiddelde middelpunt van de leden, plus en
    min de halve mediaanhoogte. Mediaan, niet maximum: een stapkop van 36 px
    op dezelfde regel mag de band niet oprekken tot hij de volgende regel
    opslokt. Gemiddelde, niet uiterste grenzen: anders groeit de band met
    elk woord mee.
    """
    banden = []
    for w in sorted(boxen, key=_mid):
        band = banden[-1] if banden else None
        if band is not None:
            mid = sum(_mid(b) for b in band) / len(band)
            half = median(_hoogte(b) for b in band) / 2
            overlap = min(w['y1'], mid + half) - max(w['y0'], mid - half)
            if overlap >= _BAND_FACTOR * _hoogte(w):
                band.append(w)
                continue
        banden.append([w])
    return [sorted(band, key=lambda b: b['x0']) for band in banden]


def _segmenten(band):
    """Een band opgedeeld bij elk gat dat groter is dan gewone spatiëring."""
    if not band:
        return []
    hoogte = sum(_hoogte(w) for w in band) / len(band)
    segmenten, huidig = [], [band[0]]
    for vorige, w in zip(band, band[1:]):
        if w['x0'] - vorige['x1'] >= _GAT_FACTOR * hoogte:
            segmenten.append(huidig)
            huidig = []
        huidig.append(w)
    segmenten.append(huidig)
    return segmenten


def _tekst(woorden):
    return ' '.join(w['tekst'] for w in woorden)


def _heeft_letters(tekst):
    return re.search(r'[^\W\d_]', tekst) is not None


def _is_cel(tekst):
    return bool(_HOEVEELHEID.match(tekst)) and len(tekst.split()) <= _MAX_CELWOORDEN


def _schoon_naam(naam):
    """Allergeencodes ('5) 21) 22)') en sterretjes eraf."""
    naam = re.sub(r'(\s*\d+\s*\))+\s*$', '', naam)
    naam = naam.replace('*', '').strip()
    return re.sub(r'\s+', ' ', naam)


def _schoon_hoeveelheid(cel):
    """OCR-artefacten rond een breukteken: '½½⁄2 el' is '½ el'."""
    cel = re.sub(rf'([{_FRACTIES}])\1+', r'\1', cel)
    cel = re.sub(rf'([{_FRACTIES}])[⁄/]?\d(?!\d)', r'\1', cel)
    return re.sub(r'\s+', ' ', cel).strip()


def _kandidaten(banden):
    """Per band wat hij voor de tabel kan zijn.

    ('rij', naam, hoeveelheid, x_hoev, rechts, x1_hoev): letters met direct
    rechts een hoeveelheid; `rechts` zijn de segmenten daar weer rechts van.
    ('kop', tekst) voor een voorraadkop, ('los', tekst) voor alleen letters,
    None voor al het andere (een leeg blok, alleen cijfers).
    """
    uit = []
    for band in banden:
        segmenten = _segmenten(band)
        kandidaat = None
        for links, rechts in zip(segmenten, segmenten[1:]):
            l_tekst, r_tekst = _tekst(links), _tekst(rechts)
            if _heeft_letters(l_tekst) and _is_cel(r_tekst):
                plek = segmenten.index(rechts)
                kandidaat = ('rij', l_tekst, r_tekst, rechts[0]['x0'],
                             [_tekst(s) for s in segmenten[plek + 1:]], rechts[-1]['x1'])
                break
        if kandidaat is None:
            eerste = _tekst(segmenten[0])
            if is_voorraadkop(eerste):
                kandidaat = ('kop', eerste)
            elif _heeft_letters(eerste):
                kandidaat = ('los', eerste)
        uit.append(kandidaat)
    return uit


def _hoeveelheidkolom(kandidaten, hoogte):
    """De x-positie waar de meeste hoeveelheden staan, of None."""
    xs = sorted(k[3] for k in kandidaten if k and k[0] == 'rij')
    if not xs:
        return None
    beste, beste_n = None, 0
    for x in xs:
        n = sum(1 for y in xs if abs(y - x) <= _KOLOM_FACTOR * hoogte)
        if n > beste_n:
            beste, beste_n = x, n
    return beste


def tabelrijen(annotation):
    """De ingrediëntentabel van een kaart: ([{naam, hoeveelheid, blok, y}], None),
    of (None, reden) met reden 'geen tabel' of 'meerdere kolommen'.

    Twee passen. De eerste legt alle woorden in banden en zoekt de
    hoeveelheidkolom: de x-positie waar de meeste 'letters | getal'-paren
    staan. Die banden zijn onbetrouwbaar — de stappen staan in kolommen
    ernaast met een eigen regelhoogte, en hun woorden trekken een band
    scheef — maar voor een x-positie is dat goed genoeg. De tweede pas
    legt alleen de strook tot en met de hoeveelheidkolom in banden; daar
    staan enkel namen en hoeveelheden, dus daar kruipt niets.

    De tabel is dan het langste blok opeenvolgende banden dat uit rijen (in
    de hoeveelheidkolom), voorraadkoppen en losse tekstregels bestaat;
    banden zonder letters (stapnummers) breken het niet. Een losse regel
    wordt alleen bij de volgende naam geplakt als die met een kleine letter
    begint; anders is het een kop en valt hij weg.
    """
    boxen = woordboxen(annotation)
    if not boxen:
        return None, 'geen tabel'
    hoogte = median(_hoogte(w) for w in boxen)
    kandidaten = _kandidaten(_banden(boxen))
    kolom = _hoeveelheidkolom(kandidaten, hoogte)
    if kolom is None:
        return None, 'geen tabel'
    in_kolom = [k for k in kandidaten
                if k and k[0] == 'rij' and abs(k[3] - kolom) <= _KOLOM_FACTOR * hoogte]
    # Rechts van de hoeveelheid nóg een hoeveelheid (2p | 4p): niet raden.
    if sum(1 for k in in_kolom if k[4] and _is_cel(k[4][0])) >= _MIN_RIJEN:
        return None, 'meerdere kolommen'

    # Tweede pas: alleen de strook van de tabel.
    rand = max(k[5] for k in in_kolom) + hoogte
    banden = _banden([w for w in boxen if w['x1'] <= rand])
    kandidaten = _kandidaten(banden)
    genormeerd = []
    for k, band in zip(kandidaten, banden):
        if k is None:
            continue
        if k[0] == 'rij' and abs(k[3] - kolom) > _KOLOM_FACTOR * hoogte:
            k = ('los', k[1])
        genormeerd.append((k, band[0]['y0']))

    # Het langste blok: drie losse regels achter elkaar ná rijen betekent dat
    # de tabel voorbij is (kop van een volgende tabel, lopende tekst).
    beste, huidig = [], []
    for k, y in genormeerd:
        huidig.append((k, y))
        staart = [x for x in huidig[-3:] if x[0][0] == 'los']
        if len(staart) == 3 and _telt(huidig):
            if _telt(huidig[:-3]) > _telt(beste):
                beste = huidig[:-3]
            huidig = huidig[-3:]
    if _telt(huidig) > _telt(beste):
        beste = huidig
    if _telt(beste) < _MIN_RIJEN:
        return None, 'geen tabel'

    uit, blok, prefix = [], 'kaart', ''
    for k, y in beste:
        if k[0] == 'kop':
            blok, prefix = 'voorraad', ''
        elif k[0] == 'los':
            prefix = k[1]
        else:
            naam, hoev = k[1], k[2]
            if prefix and naam[:1].islower():
                naam = prefix + ' ' + naam
            prefix = ''
            uit.append({'naam': _schoon_naam(naam), 'hoeveelheid': _schoon_hoeveelheid(hoev),
                        'blok': blok, 'y': y})
    return uit, None


def _telt(kandidaten):
    return sum(1 for k, _y in kandidaten if k[0] == 'rij')
