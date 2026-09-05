"""Ingrediëntentabel van een receptkaart uit de woordcoördinaten van Vision.

In de platte OCR-tekst valt zo'n tabel uit elkaar: eerst een blok namen, dan
een blok hoeveelheden, met stapnummers ertussen en de laatste hoeveelheden
pas na de kop 'Voedingswaarden'. Het model maakte daar op de ene kaart die
we hadden 14 van de 15 rijen goed van — maar een hoeveelheid aan de
verkeerde naam is in de tekst niet te zien. Deze module leest de tabel uit
de boxen die Vision toch al meegeeft, en geeft het model schone regels
'naam | hoeveelheid'.

Alles hier is merkloos. Wat twaalf gescande kaarten leerden, en waarom het
níét 'naam en hoeveelheid op dezelfde hoogte' is:

* Een telefoonscan staat een paar graden gedraaid, en sommige kaarten
  drukken de hoeveelheid al een halve rij lager dan de naam. Samen is dat
  anderhalve rij: op y uitlijnen koppelt dan álles één rij verkeerd, en
  niets verraadt dat. De volgorde binnen de tabel klopt wél altijd — de
  i-de naam hoort bij de i-de hoeveelheid. Dus: kolommen op x, rijen op
  volgorde, en y alleen als controle (de verschuiving moet per rij
  ongeveer gelijk zijn).
* De stappen staan in kolommen náást de tabel, met een eigen regelhoogte.
  Banden over de hele breedte kruipen daardoor; alles gebeurt binnen de
  strook van de tabel.
* Kaarten voor 1–6 personen hebben zes getalkolommen met een kop '1P 2P
  … 6P', de eenheid in de naam ('Zoete aardappel (g)') en cellen die door
  de kleine tussenruimte tot één segment plakken. De kolom wordt gekozen
  op het aantal personen; zonder dat gegeven wordt zo'n tabel geweigerd.
* Een hoeveelheid is niet altijd een getal: 'naar smaak', 'scheutje'.
"""
import re
from statistics import median

from weekmenu.services.kaartsignaturen import is_voorraadkop

# Een kolomgrens is een gat van minstens zoveel maal de woordhoogte; kleiner
# is gewone spatiëring tussen woorden.
_GAT_FACTOR = 1.5
# Een woord hoort bij een band als het minstens zoveel van zijn eigen hoogte
# overlapt met de kern van de band (gemiddeld midden ± halve mediaanhoogte).
_BAND_FACTOR = 0.2
# Hoeveelheden die zoveel maal de woordhoogte van de kolom af staan horen er
# niet bij (stapnummers, een tweede tabel). Op de kaarten staan de echte
# binnen 2 woordhoogtes van elkaar, de voedingswaardenkolom er 4 vanaf.
_KOLOM_FACTOR = 2.5
# Een hoeveelheidcel is kort ('200 g', 'naar smaak'); een stapregel die
# toevallig met een getal begint ('180 graden. Schud...') is dat niet.
_MAX_CELWOORDEN = 3
_MIN_RIJEN = 3
# Namen staan hooguit zoveel rijen boven hun hoeveelheid (scheve scan +
# opmaak: anderhalf gemeten), en de verschuiving mag per rij hooguit zoveel
# rijen uiteenlopen (een afgebroken naam telt vanaf zijn eerste regel).
_NAAM_BOVEN = 1.8
_MAX_SPREIDING = 1.2
# Meer dan zoveel rijen zonder hoeveelheid ertussen: een andere tabel.
_MAX_GAT = 3
_FRACTIES = '½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞'
_HOEVEELHEID = re.compile(rf'^(\d|[{_FRACTIES}]|naar smaak)', re.IGNORECASE)
_GETAL = re.compile(rf'^[\d{_FRACTIES}]')
_PERSONENKOP = re.compile(r'^(\d+)\s*[pP]\.?$')
_TABELKOP = re.compile(r'\bpersonen\b|\bpers\.', re.IGNORECASE)
_EENHEID_IN_NAAM = re.compile(r'\(\s*([^\W\d_]{1,6})\s*\)')


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


def _xmid(w):
    return (w['x0'] + w['x1']) / 2


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


def _ontscheef(boxen):
    """Draai een scheve scan recht: y wordt y - helling·x.

    De helling komt uit de lange regels zelf (in een gedraaide regel loopt
    y op met x). Een telefoonscan staat zo 2° gedraaid; over de breedte van
    een tabel is dat een halve rij, genoeg om woorden van twee regels in één
    band te krijgen.
    """
    hellingen = []
    for band in _banden(boxen):
        for seg in _segmenten(band):
            breedte = seg[-1]['x1'] - seg[0]['x0']
            if len(seg) >= 4 and breedte >= 12 * _hoogte(seg[0]):
                hellingen.append((_mid(seg[-1]) - _mid(seg[0])) / breedte)
    if len(hellingen) < 3:
        return boxen
    helling = median(hellingen)
    return [dict(w, y0=w['y0'] - helling * w['x0'], y1=w['y1'] - helling * w['x0'])
            for w in boxen]


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
    tekst = _schoon_hoeveelheid(tekst)
    return bool(_HOEVEELHEID.match(tekst)) and len(tekst.split()) <= _MAX_CELWOORDEN


def _schoon_naam(naam):
    """Allergeencodes ('5) 21) 22)'), sterretjes, aanhalingstekens en de
    spaties die de OCR rond een koppelteken zet ('Semi - gedroogde')."""
    naam = re.sub(r'(\s*\d+\s*\))+', ' ', naam)
    naam = re.sub(r'[*"]', '', naam)
    naam = re.sub(r'\s*-\s*', '-', naam)
    return re.sub(r'\s+', ' ', naam).strip()


def _schoon_hoeveelheid(cel):
    """OCR-artefacten: '½½⁄2 el' en '½½ / 2 st' zijn '½ el' en '½ st', '1½2'
    is '1½', '75g' is '75 g', en '1 stuk ( s )' is '1 stuk(s)'."""
    cel = re.sub(r'\s*\(\s*([^\W\d_]+)\s*\)', r'(\1)', cel)
    cel = re.sub(rf'([{_FRACTIES}])\1+', r'\1', cel)
    cel = re.sub(rf'([{_FRACTIES}])\s*[⁄/]?\s*\d(?!\d)', r'\1', cel)
    cel = re.sub(r'(\d)([^\W\d_])', r'\1 \2', cel)
    return re.sub(r'\s+', ' ', cel).strip()


def _cluster(xs, tolerantie):
    """Groepen x-posities die hooguit `tolerantie` uit elkaar liggen: [(midden, n)]."""
    groepen = []
    for x in sorted(xs):
        if groepen and x - groepen[-1][-1] <= tolerantie:
            groepen[-1].append(x)
        else:
            groepen.append([x])
    return [(sum(g) / len(g), len(g)) for g in groepen]


def _kolommen(banden, hoogte, personen):
    """De x-posities van de hoeveelheidkolommen, en welke gekozen is.

    Geeft (kolom_x, alle_kolommen, reden). Eén kolom: de x waar de meeste
    getallen staan die rechts van tekst beginnen. Meer kolommen: een kop
    '1P 2P …' wijst ze aan, en `personen` kiest; zonder kop of zonder
    passend aantal personen is de reden 'meerdere kolommen'.
    """
    getallen = []
    for band in banden:
        segmenten = _segmenten(band)
        if not _heeft_letters(_tekst(segmenten[0])):
            continue
        links_x1 = segmenten[0][-1]['x1']
        for seg in segmenten[1:]:
            if all(_GETAL.match(w['tekst']) for w in seg) or _is_cel(_tekst(seg)):
                getallen += [_xmid(w) for w in seg if _GETAL.match(w['tekst']) and w['x0'] > links_x1]
    groepen = [g for g in _cluster(getallen, 1.5 * hoogte) if g[1] >= _MIN_RIJEN]
    if not groepen:
        return None, [], 'geen tabel'

    koppen = {}
    for band in banden:
        treffers = [(int(_PERSONENKOP.match(w['tekst']).group(1)), _xmid(w))
                    for w in band if _PERSONENKOP.match(w['tekst'])]
        if len(treffers) >= 2:
            koppen = dict(treffers)
            break
    if koppen:
        if personen in koppen:
            return koppen[personen], sorted(koppen.values()), None
        return None, sorted(koppen.values()), 'meerdere kolommen'
    # Geen kop: de drukste kolom. Of er náást die kolom nog een tweede staat
    # (2p | 4p zonder kop) blijkt pas per rij van het gekozen blok; de
    # voedingswaardentabel heeft ook een tweede kolom, maar in andere rijen.
    beste = max(groepen, key=lambda g: g[1])[0]
    return beste, [beste], None


def tabelrijen(annotation, personen=None):
    """De ingrediëntentabel van een kaart: ([{naam, hoeveelheid, blok, y}], None),
    of (None, reden).

    Redenen: 'geen tabel', 'meerdere kolommen' (zie _kolommen), 'telling
    klopt niet: N namen, M hoeveelheden' en 'rijen niet uit te lijnen' (de
    verschuiving tussen naam en hoeveelheid loopt per rij te veel uiteen —
    dan is de volgorde niet te vertrouwen).
    """
    boxen = woordboxen(annotation)
    if not boxen:
        return None, 'geen tabel'
    hoogte = median(_hoogte(w) for w in boxen)
    boxen = _ontscheef(boxen)
    banden = _banden(boxen)
    kolom, kolommen, reden = _kolommen(banden, hoogte, personen)
    if reden:
        return None, reden
    meerkoloms = len(kolommen) > 1
    afstand = min(b - a for a, b in zip(kolommen, kolommen[1:])) if meerkoloms else None
    tolerantie = min(_KOLOM_FACTOR * hoogte, 0.45 * afstand) if meerkoloms else _KOLOM_FACTOR * hoogte
    gebied = (kolommen[0] - 2 * hoogte, kolommen[-1] + 2 * hoogte)

    # Tweede pas: alleen de strook tot en met de cellen. De stapkolommen
    # ernaast hebben een eigen regelhoogte en trekken anders elke band scheef.
    rand = kolommen[-1] + 2 * hoogte
    for band in banden:
        for seg in _segmenten(band):
            if abs(seg[0]['x0'] - kolom) <= tolerantie and _is_cel(_tekst(seg)):
                rand = max(rand, seg[-1]['x1'] + hoogte)
    banden = _banden([w for w in boxen if w['x1'] <= rand])

    # Rijen: banden met een cel in de gekozen kolom (of een korte cel zonder
    # getal ergens in het kolomgebied: 'scheutje', 'naar smaak').
    rijen = []
    for band in banden:
        if _is_kopregel(band):
            continue
        cel = _cel_in_kolom(band, kolom, tolerantie, gebied, meerkoloms)
        if cel is not None:
            rijen.append({'y': band[0]['y0'], 'cel': cel, 'band': band})
    if len(rijen) < _MIN_RIJEN:
        return None, 'geen tabel'

    # Het aaneengesloten blok: een gat van meer dan _MAX_GAT rijen is een
    # andere tabel (voedingswaarden). Het langste blok wint.
    pitch = median(b['y'] - a['y'] for a, b in zip(rijen, rijen[1:]))
    blokken, huidig = [], [rijen[0]]
    for vorige, rij in zip(rijen, rijen[1:]):
        if rij['y'] - vorige['y'] > _MAX_GAT * pitch:
            blokken.append(huidig)
            huidig = []
        huidig.append(rij)
    blokken.append(huidig)
    rijen = max(blokken, key=len)
    if len(rijen) < _MIN_RIJEN:
        return None, 'geen tabel'
    if not meerkoloms and sum(1 for r in rijen if _tweede_cel(r['band'], kolom, hoogte)) >= _MIN_RIJEN:
        return None, 'meerdere kolommen'

    # Namen: tekst links van de kolommen, van iets boven de eerste rij tot
    # de laatste rij. Koppen wisselen het blok, voetnoten en de tabelkop
    # tellen niet mee, een regel met een kleine letter vooraan hoort bij de
    # naam erboven.
    y_van = rijen[0]['y'] - _NAAM_BOVEN * pitch
    y_tot = rijen[-1]['y'] + 0.5 * pitch
    namen, kop_y = [], None
    for band in banden:
        y = band[0]['y0']
        if not y_van <= y <= y_tot:
            continue
        if _is_kopregel(band):
            continue
        heel = _tekst(_segmenten(band)[0])
        if is_voorraadkop(heel):
            kop_y = y
            continue
        tekst = _tekst([w for w in band if w['x1'] <= kolommen[0] - tolerantie])
        if not _heeft_letters(tekst) or heel.lstrip().startswith('*'):
            continue
        # Een vervolgregel ('aardappelen') of een losse eenheid ('( g )')
        # hoort bij de naam erboven.
        if namen and (tekst[:1].islower() or _EENHEID_IN_NAAM.fullmatch(tekst.strip())):
            namen[-1]['tekst'] += ' ' + tekst
            continue
        namen.append({'y': y, 'tekst': tekst})
    if len(namen) != len(rijen):
        return None, f'telling klopt niet: {len(namen)} namen, {len(rijen)} hoeveelheden'

    verschuivingen = [r['y'] - n['y'] for n, r in zip(namen, rijen)]
    if max(verschuivingen) - min(verschuivingen) > _MAX_SPREIDING * pitch:
        return None, 'rijen niet uit te lijnen'

    uit = []
    for naam, rij in zip(namen, rijen):
        eenheid = _EENHEID_IN_NAAM.search(naam['tekst'])
        tekst = _EENHEID_IN_NAAM.sub(' ', naam['tekst'])
        cel = _schoon_hoeveelheid(rij['cel'])
        if eenheid and not _heeft_letters(cel):
            cel = f'{cel} {eenheid.group(1)}'
        uit.append({'naam': _schoon_naam(tekst), 'hoeveelheid': cel,
                    'blok': 'voorraad' if kop_y is not None and naam['y'] > kop_y else 'kaart',
                    'y': rij['y']})
    return uit, None


def _is_kopregel(band):
    """De tabelkop ('Ingrediënten voor 2 personen') of de kolomkop ('1P 2P …')."""
    return (any(_PERSONENKOP.match(w['tekst']) for w in band)
            or bool(_TABELKOP.search(_tekst(_segmenten(band)[0]))))


def _tweede_cel(band, kolom, hoogte):
    """Staat er rechts van de cel in `kolom` nóg een korte cel met een getal?"""
    segmenten = _segmenten(band)
    for seg, volgende in zip(segmenten[1:], segmenten[2:]):
        if abs(seg[0]['x0'] - kolom) <= _KOLOM_FACTOR * hoogte and _is_cel(_tekst(seg)):
            return _is_cel(_tekst(volgende)) and _GETAL.match(_tekst(volgende))
    return False


def _cel_in_kolom(band, kolom, tolerantie, gebied, meerkoloms):
    """De celtekst van deze band in de gekozen kolom, of None als het geen rij is.

    Eén kolom: het korte segment dat bij de kolom begint. Meer kolommen: het
    getal dat het dichtst bij de kolom staat. In beide gevallen telt ook een
    kort segment zonder getal in het kolomgebied ('scheutje') — mits er
    links ervan tekst staat, anders is het een stapkop in de marge.
    """
    segmenten = _segmenten(band)
    if not segmenten:
        return None
    if meerkoloms:
        getallen = [w for w in band if _GETAL.match(w['tekst']) and gebied[0] <= _xmid(w) <= gebied[1]]
        dichtbij = [w for w in getallen if abs(_xmid(w) - kolom) <= tolerantie]
        if dichtbij:
            return min(dichtbij, key=lambda w: abs(_xmid(w) - kolom))['tekst']
        if getallen:
            return None
    else:
        # Ook het eerste segment: op een scheve scan staat de naam anderhalve
        # rij hoger en is de cel het enige op deze band.
        for seg in segmenten:
            if _is_cel(_tekst(seg)) and abs(seg[0]['x0'] - kolom) <= tolerantie:
                return _tekst(seg)
    # Geen getal: een korte cel in het kolomgebied, met tekst links ervan
    # ('scheutje', 'naar smaak', of een breuk die Vision als '%' las — die
    # gaat letterlijk door, de controle achteraf markeert hem).
    for seg in segmenten[1:]:
        tekst = _tekst(seg)
        if (len(_schoon_hoeveelheid(tekst).split()) <= _MAX_CELWOORDEN and _heeft_letters(tekst)
                and not _GETAL.match(tekst)
                and seg[0]['x0'] < gebied[1] and seg[-1]['x1'] > gebied[0]
                and segmenten[0][-1]['x1'] < gebied[0]):
            return tekst
    return None
