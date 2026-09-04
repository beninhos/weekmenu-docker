"""Bereidingstekst uit de OCR-tekst knippen op aanwijzing van het model.

Waarom het model de tekst niet zelf overschrijft: dat is vragen om
letterlijkheid in plaats van hem afdwingen. Gemeten op de kipbundel schreef
gemini-3.5-flash zes keer 'and' waar het boek 'en' heeft en 'till' voor 'tot',
en liet het regelafbrekingen als 'ser- veer' staan; gemini-2.5-flash zette in
de ene aanroep punten achter elke stap en in de volgende niet. Geen prompt
houdt dat tegen, want het model kopieert duizenden woorden en mag daar niets
in veranderen.

Hier geeft het model per stap alleen de eerste en laatste paar woorden (de
ankers). De tekst die in het recept komt is dan per constructie de tekst die
Vision las: het model heeft hem nooit uitgesproken. Wisselen van model raakt
de bereidingstekst daardoor niet meer, en een inhoudsfilter dat boektekst in
modeluitvoer herkent heeft niets om op af te gaan.

Gemeten op 22 pagina's: 252 van 252 ankers pasten exact. Wat wél voorkomt is
dat Vision de eerste regel van de bereiding aan de ingrediëntkolom plakt
(kolommen die elkaar op 16 px raken), zodat een stap in de tekst onderbroken
wordt door de ingrediëntenlijst. Die lijst wordt uit de stap gehaald op wat
hem verraadt: een blok korte regels die met een hoeveelheid beginnen. En het
model laat soms een zin tussen een eindanker en het volgende beginanker
vallen; die tekst gaat dan bij de vorige stap, want tekst kwijtraken is erger
dan een stapgrens die iets verschoven is.
"""
import difflib
import re

_BULLETS = '•⚫●▪■◦'
# Onder deze woordovereenkomst past een anker niet. Gemeten: exacte ankers
# scoren 1,0; een anker met één OCR-tekenfout in vijf woorden ~0,9.
_FUZZY_DREMPEL = 0.8
# Een niet-gevonden anker wordt in de melding tot zoveel tekens afgekort.
_ANKER_KORT = 40


def normaliseer(text, corpus=None):
    """Paginatekst in de vorm waarin geknipt wordt: enkele spaties, regeleinden intact.

    De regeleinden blijven staan omdat de ingrediëntenlijst alleen aan zijn
    regels te herkennen is (zie _zonder_ingredientregels); voor het zoeken van
    ankers telt een regeleinde als spatie.

    Regelafbrekingen worden opgelost, en dat vraagt een keuze: 'ser-|veer' is
    één woord, 'vierge-|olijfolie' hoort zijn koppelteken te houden. Van de 17
    afbrekingen op de meetlat waren er 13 lettergreepafbrekingen en 4 echte
    koppeltekens. De regel: een koppelteken vóór 'of'/'en' blijft (het is dan
    een weggelaten deel: 'zilvervlies- of basmatirijst'); anders worden de
    delen samengevoegd als dat woord elders in de tekst voorkomt, en blijft
    het koppelteken staan als dat niet zo is. Dat laatste is zichtbaar
    ('klod-dertje') in plaats van stil ('viergeolijfolie'), en dat is de
    bedoeling.
    """
    text = text or ''
    laag = (corpus if corpus is not None else text).lower()

    def los_op(m):
        a, b = m.group(1), m.group(2)
        if b.lower() in ('of', 'en'):
            return f'{a}- {b}'
        kaal = re.sub(r'\W+$', '', b)
        if re.search(r'\b' + re.escape((a + kaal).lower()) + r'\b', laag):
            return a + b
        return f'{a}-{b}'

    text = re.sub(r'(\w+)-\s*\n\s*(\S+)', los_op, text)
    text = re.sub(f'[{_BULLETS}]', ' ', text)
    regels = [re.sub(r'[^\S\n]+', ' ', r).strip() for r in text.split('\n')]
    return '\n'.join(r for r in regels if r)


def _zoek(anker, tekst, vanaf=0):
    """Positie (begin, eind) van een anker in de tekst, of None.

    Eerst letterlijk, dan zonder hoofdletters, dan fuzzy op woordniveau; het
    laatste vangt een OCR-tekenfout in het anker of een afbreking die het
    model als heel woord schreef.
    """
    anker = re.sub(r'\s+', ' ', anker or '').strip()
    if not anker:
        return None
    i = tekst.find(anker, vanaf)
    if i >= 0:
        return i, i + len(anker)
    i = tekst.lower().find(anker.lower(), vanaf)
    if i >= 0:
        return i, i + len(anker)
    woorden = [(m.start(), m.end()) for m in re.finditer(r'\S+', tekst) if m.start() >= vanaf]
    n = len(anker.split())
    beste, plek = 0.0, None
    for k in range(len(woorden) - n + 1):
        b, e = woorden[k][0], woorden[k + n - 1][1]
        score = difflib.SequenceMatcher(None, anker.lower(), tekst[b:e].lower()).ratio()
        if score > beste:
            beste, plek = score, (b, e)
    return plek if beste >= _FUZZY_DREMPEL else None


def knip_stappen(paginatekst, steps, corpus=None, ingredienten=()):
    """Knip de bereidingsstappen uit de paginatekst. Geeft (tekst, meldingen).

    `steps` is de lijst van het model: {'start', 'end'}; `ingredienten` de
    namen uit het recept, om een ingrediëntenlijst te herkennen die door een
    stap heen loopt. De tekst is de stappen met een regeleinde ertussen, zoals
    de app hem al bewaarde toen het model hem nog zelf schreef.
    """
    regels = normaliseer(paginatekst, corpus)
    tekst = regels.replace('\n', ' ')      # even lang, dus posities blijven gelden
    stappen = [s for s in (steps or []) if isinstance(s, dict)]
    if not stappen:
        return '', ['geen bereidingsstappen aangewezen']
    if not tekst:
        return '', ['geen paginatekst om uit te knippen']

    # Alle beginankers eerst, op volgorde: een anker mag niet vóór het vorige
    # beginanker vallen, anders pakt 'Snijd de ui' de eerste van twee keer.
    grenzen, meldingen, cursor = [], [], 0
    for s in stappen:
        b = _zoek(s.get('start'), tekst, cursor)
        if b is None:
            b = _zoek(s.get('start'), tekst, 0)
        if b is not None:
            cursor = b[0] + 1
        grenzen.append([b, None])

    # Eindankers ná hun begin; ontbreekt het begin, dan ná het vorige begin.
    laatste_begin = 0
    for s, g in zip(stappen, grenzen):
        if g[0] is not None:
            laatste_begin = g[0][0]
        g[1] = _zoek(s.get('end'), tekst, laatste_begin)

    if all(g[0] is None for g in grenzen):
        return '', [f"geen enkel anker gevonden ({_kort(stappen[0].get('start'))})"]

    # Ontbrekende ankers invullen: een ontbrekend begin sluit aan op het
    # vorige einde, een ontbrekend einde loopt door tot het volgende begin.
    # Dat is ruim geknipt in plaats van weggelaten, en het wordt gemeld.
    stukken = []
    for i, (s, g) in enumerate(zip(stappen, grenzen)):
        begin, eind = g
        if begin is None:
            vorige = stukken[-1][1] if stukken else 0
            begin = (vorige, vorige)
            meldingen.append(f"beginanker niet gevonden ({_kort(s.get('start'))}); "
                             "stap ruim geknipt")
        if eind is None:
            volgende = next((h[0][0] for h in grenzen[i + 1:] if h[0] is not None), len(tekst))
            eind = (volgende, volgende)
            meldingen.append(f"eindanker niet gevonden ({_kort(s.get('end'))}); "
                             "stap ruim geknipt")
        stukken.append((begin[0], max(eind[1], begin[0])))

    # Een gat tussen twee stappen gaat bij de vorige: een zin die het model
    # oversloeg mag niet verdwijnen. Overlap (volgend begin vóór dit einde)
    # laten we zoals het is; dat is een dubbel woord, geen verloren tekst.
    uit, weggelaten = [], 0
    for i, (b, e) in enumerate(stukken):
        if i + 1 < len(stukken) and stukken[i + 1][0] > e:
            e = stukken[i + 1][0]
        stuk, n = _zonder_ingredientregels(regels[b:e], ingredienten)
        weggelaten += n
        stuk = re.sub(r'\s+', ' ', stuk).strip().lstrip('.,;: ')
        if stuk:
            uit.append(stuk)
    if weggelaten:
        meldingen.append(f'{weggelaten} ingrediëntregels die door de bereiding heen liepen '
                         'zijn weggelaten')
    return '\n'.join(uit), meldingen


# Een ingrediëntregel is kort; een regel bereidingstekst in dezelfde kolom is
# dat niet. Gemeten op de kipbundel: ingrediëntregels hooguit 41 tekens, regels
# bereidingstekst rond de 75.
_INGREDIENTREGEL_MAX = 50
_HOEVEELHEID = re.compile(r'^(\d+[½¼¾]?|[½¼¾⅓⅔])\s')


def _zonder_ingredientregels(stuk, ingredienten):
    """Haal een ingrediëntenlijst die door een stap heen loopt eruit.

    Vision plakt op sommige pagina's de eerste regel van de bereiding aan de
    ingrediëntkolom; de rest van de stap komt dan pas na de hele lijst. Wat
    de lijst verraadt: minstens twee regels die met een hoeveelheid beginnen
    en waarvan de naam bij een ingrediënt van het recept hoort, en alles
    daartussen kort (blokkoppen, doorlopende namen). Het blok van de eerste
    tot de laatste zo'n regel wordt weggelaten; de regels ervoor en erna zijn
    de stap. Geeft (tekst, aantal weggelaten regels).
    """
    regels = stuk.split('\n')
    if len(regels) < 3:
        return stuk, 0
    namen = set()
    for naam in ingredienten or []:
        namen |= set(re.findall(r'[^\W\d_]{3,}', naam.lower()))
    treffers = [i for i, r in enumerate(regels[1:-1], 1)
                if _HOEVEELHEID.match(r) and len(r) <= _INGREDIENTREGEL_MAX
                and namen & set(re.findall(r'[^\W\d_]{3,}', r.lower()))]
    if len(treffers) < 2:
        return stuk, 0
    eerste, laatste = treffers[0], treffers[-1]
    if any(len(r) > _INGREDIENTREGEL_MAX for r in regels[eerste:laatste + 1]):
        return stuk, 0
    # Blokkoppen, doorlopende namen en de paginavoet horen bij de lijst en
    # zijn net zo kort; de bereiding zelf hervat met een regel over de volle
    # kolombreedte. De eerste en laatste regel van het stuk blijven altijd
    # staan, want daar staan de ankers.
    while eerste > 1 and len(regels[eerste - 1]) <= _INGREDIENTREGEL_MAX:
        eerste -= 1
    while laatste < len(regels) - 2 and len(regels[laatste + 1]) <= _INGREDIENTREGEL_MAX:
        laatste += 1
    weggelaten = laatste - eerste + 1
    # Soms plakt Vision de laatste ingrediëntregel vóór de lijst aan een regel
    # bereidingstekst ('1 handvol verse tijm, rozemarijn en/ spinazie geslonken
    # is, ...'). Die regel is lang en begint met een hoeveelheid; wat eraf mag
    # is het stuk dat woord voor woord met een ingrediëntnaam overeenkomt.
    if eerste > 1 and _HOEVEELHEID.match(regels[eerste - 1]):
        rest = _zonder_ingredientprefix(regels[eerste - 1], ingredienten)
        if rest is not None:
            regels[eerste - 1] = rest
            weggelaten += 1
    return '\n'.join(regels[:eerste] + regels[laatste + 1:]), weggelaten


def _zonder_ingredientprefix(regel, ingredienten):
    """De regel zonder de ingrediëntregel waarmee hij begint, of None.

    Na de hoeveelheid en een eventueel maatwoord moeten minstens twee woorden
    van een ingrediëntnaam volgen; alleen dat stuk gaat eraf.
    """
    woorden = regel.split()
    kaal = [re.sub(r'[^\w/]+$', '', w).lower() for w in woorden]
    for naam in ingredienten or []:
        naamw = [re.sub(r'[^\w/]+$', '', w).lower() for w in naam.split()]
        for begin in (1, 2):                       # direct na het getal, of na het maatwoord
            n = 0
            while n < len(naamw) and begin + n < len(kaal) and _zelfde_woord(kaal[begin + n], naamw[n]):
                n += 1
            if n >= 2 and begin + n < len(woorden):
                return ' '.join(woorden[begin + n:])
    return None


def _kort(anker):
    anker = (anker or '').strip()
    return repr(anker[:_ANKER_KORT] + ('…' if len(anker) > _ANKER_KORT else ''))


def _zelfde_woord(regelwoord, naamwoord):
    """Gelijk, of een aan een schuine streep afgebroken woord ('en/' bij 'en/of')."""
    return regelwoord == naamwoord or (regelwoord.endswith('/') and naamwoord.startswith(regelwoord))
