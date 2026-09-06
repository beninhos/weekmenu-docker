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

Gemeten op 22 pagina's: 252 van 252 ankers pasten exact, en over vier modellen
(2.5-flash, 3.5-flash, 3.8-flash, flash-latest) is de geknipte tekst op 21 tot
22 van de 22 pagina's byte-gelijk. Wat wél voorkomt, en waar de rest van dit
bestand over gaat:

* Vision plakt de eerste regel van de bereiding aan de ingrediëntkolom
  (kolommen die elkaar op 16 px raken), zodat een stap in de tekst onderbroken
  wordt door de ingrediëntenlijst. Die lijst wordt uit de stap gehaald op wat
  hem verraadt: een blok korte regels die met een hoeveelheid beginnen en bij
  een ingrediënt van het recept horen (_zonder_ingredientregels).
* Het model laat soms een zin tussen een eindanker en het volgende beginanker
  vallen. Die tekst gaat bij de vorige stap, want tekst kwijtraken is erger
  dan een stapgrens die iets verschoven is. Maar op een receptkaart staat in
  zo'n gat ook de ingrediënten- en voedingswaardentabel; een aaneengesloten
  blok regels zonder één zin erin wordt daarom uit het gat gehaald
  (_zonder_meubilair).
* Alles na het laatste eindanker valt buiten de knip. Staat daar nog een zin
  bereidingstekst, dan wordt dat gemeld, met de zin erbij; het model zei dat
  het recept daar ophield, dus we voegen niets toe maar laten het ook niet
  stil verdwijnen.

Wat hier wordt weggehaald gaat naar de log (info-niveau), niet naar de
nakijker: op een batch van twaalf kaarten was de opsomming ('Vetten (g)',
'Kan sporen bevatten van') twaalf keer ruis en nul keer een bevinding. Wat
de nakijker wél te zien krijgt is wat er mogelijk ontbreekt: een zin na de
laatste stap, of een stap die ruim geknipt is omdat een grens niet paste.
"""
import difflib
import logging
import re

_BULLETS = '•⚫●▪■◦'
# Onder deze woordovereenkomst past een anker niet. Gemeten: exacte ankers
# scoren 1,0; een anker met één OCR-tekenfout in vijf woorden ~0,9.
_FUZZY_DREMPEL = 0.8
# Een niet-gevonden anker wordt in de melding tot zoveel tekens afgekort.
_ANKER_KORT = 40

log = logging.getLogger(__name__)


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
    # Het model hoort een string te geven; geeft het een getal, lijst of object,
    # dan is dat 'anker niet gevonden' en geen reden om de hele batch te laten
    # omvallen met een TypeError.
    if not isinstance(anker, str):
        return None
    anker = re.sub(r'\s+', ' ', anker).strip()
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
            meldingen.append(f"een stap is ruim geknipt: het begin ({_kort(s.get('start'))}) "
                             "was niet terug te vinden")
        if eind is None:
            volgende = next((h[0][0] for h in grenzen[i + 1:] if h[0] is not None), len(tekst))
            eind = (volgende, volgende)
            meldingen.append(f"een stap is ruim geknipt: het einde ({_kort(s.get('end'))}) "
                             "was niet terug te vinden")
        stukken.append((begin[0], max(eind[1], begin[0])))

    # Een gat tussen twee stappen gaat bij de vorige: een zin die het model
    # oversloeg mag niet verdwijnen. Wat in dat gat op een tabel lijkt gaat er
    # wel uit. Overlap (volgend begin vóór dit einde) laten we zoals het is;
    # dat is een dubbel woord, geen verloren tekst.
    # Kopjes ('1. Pasta koken', 'Saus maken') staan op de kaart vlak vóór de
    # stap, maar het model wijst de stap aan vanaf de eerste zin. Zo'n kopje
    # hoort bij de stap eronder, op een eigen regel — niet aan het eind van
    # de vorige stap, en niet weg als meubilair.
    ankers = list(stukken)                      # zoals het model ze aanwees, vóór het kopje erbij
    koppen = []
    for i, (b, e) in enumerate(stukken):
        grens = stukken[i - 1][1] if i else 0
        kop = _kopregel(regels, b, grens, ingredienten)
        if kop:
            begin, tekst_kop = kop
            # Een los stapnummer vlak vóór het kopje ('4' en dan 'Boontjes
            # koken' op de volgende regel) hoort bij het kopje.
            nummer = re.fullmatch(r'\s*(\d{1,2}\.?)\s*', regels[grens:begin])
            if nummer:
                begin, tekst_kop = grens, f'{nummer.group(1)} {tekst_kop}'
            stukken[i] = (begin, e)
        koppen.append(kop and tekst_kop)

    uit, weggelaten = [], []
    for i, (b, e) in enumerate(stukken):
        if i and ankers[i] == ankers[i - 1]:
            continue                            # zelfde ankers twee keer: dezelfde tekst niet twee keer
        stuk = regels[b:e]
        kop = koppen[i]
        if kop:
            # Het kopje staat vooraan in het stuk, mogelijk over twee regels
            # ('4' en dan 'Boontjes koken'): woord voor woord eraf halen.
            stuk = re.sub(r'^\s*' + r'\s+'.join(re.escape(w) for w in kop.split()) + r'\s*', '', stuk, count=1)
        if i + 1 < len(stukken) and stukken[i + 1][0] > e:
            gat, meubilair = _zonder_meubilair(regels[e:stukken[i + 1][0]])
            if re.fullmatch(r'\s*\d{1,2}\.?\s*', gat):
                gat = ''                        # los stapnummer van een genummerd kookboek
            stuk += gat
            weggelaten += meubilair
        stuk, weg = _zonder_ingredientregels(stuk, ingredienten)
        weggelaten += weg
        stuk = re.sub(r'\s+', ' ', stuk).strip().lstrip('.,;: ')
        if kop:
            uit.append(kop)
        if stuk:
            uit.append(stuk)
    if weggelaten:
        # Tabel, voedingswaarden en ingrediëntregels uit de bereiding halen is
        # gewenst gedrag, geen bevinding. De nakijker krijgt er dus geen
        # melding van (twaalf keer 'Vetten (g)' verbergt de meldingen die er
        # wél toe doen); voor wie de knip wil narekenen staat het in de log.
        log.info('%s', _weggelaten_melding(weggelaten))

    # Na het laatste eindanker houdt de knip op. Het model zei dat het recept
    # daar eindigt, dus er wordt niets toegevoegd — maar staat er nog een zin
    # bereidingstekst, dan hoort de gebruiker dat te zien.
    staart = regels[stukken[-1][1]:].split('\n')
    citaat = _staartzin(staart)
    if citaat:
        meldingen.append(f"na de laatste stap stond nog {_kort(citaat, 100)}; "
                         "dat is niet overgenomen")
    return '\n'.join(uit), meldingen


def _staartzin(staart):
    """De eerste zin bereidingstekst na de laatste stap, of None.

    Een nawoord (Weetje, Tip, Eet smakelijk; de kop staat vaak op een eigen
    regel) slikt de rest van de staart — behalve een genummerde stap erna:
    wijst het model de laatste stap één te vroeg aan, dan is dát de zin die
    de nakijker moet zien.
    """
    zinnen = [i for i, r in enumerate(staart) if _is_zin(r)]
    if not zinnen:
        return None
    citaat = ' '.join(r.strip() for r in staart[:zinnen[0] + 1] if r.strip())
    if not _is_nawoord(citaat):
        return citaat
    stap = next((i for i in zinnen if _GENUMMERDE_STAP.match(staart[i])), None)
    return staart[stap].strip() if stap is not None else None


_GENUMMERDE_STAP = re.compile(r'^\s*\d{1,2}[.)]?\s+[^\W\d_]')


def _kopregel(regels, b, grens, ingredienten):
    """Het kopje van de stap die op positie `b` begint: (beginpositie, tekst) of None.

    Twee plekken: de regel waarmee de stap begint (het model nam het kopje in
    het anker op: 'Groente snijden Snijd de paprika'), of de regel er vlak
    boven, mits die ná het einde van de vorige stap ligt. Alleen als de stap
    op een regelbegin start: midden in een regel is de tekst ervoor de
    vorige regel, geen kopje.
    """
    if b > 0 and regels[b - 1] != '\n':
        return None
    eind = regels.find('\n', b)
    eerste = regels[b:eind if eind >= 0 else len(regels)]
    volgende = regels[eind + 1:regels.find('\n', eind + 1) if regels.find('\n', eind + 1) >= 0 else len(regels)] \
        if eind >= 0 else ''
    if _is_kop(eerste, volgende, ingredienten):
        return b, eerste.strip()
    if b == 0:
        return None
    begin = regels.rfind('\n', 0, b - 1) + 1
    if begin < grens:
        return None
    ervoor = regels[begin:b - 1]
    if _is_kop(ervoor, eerste, ingredienten):
        return begin, ervoor.strip()
    return None


def _is_kop(regel, volgende, ingredienten=()):
    """Kort, zonder leesteken aan het eind, eventueel genummerd, en de regel
    erna begint met een hoofdletter (een afgebroken stap loopt in kleine
    letters door). Geen getallen buiten het nummer ('Week 32 2022', '180 g')
    en geen ingrediëntnaam ('Peper en zout')."""
    woorden = regel.split()
    if not 1 <= len(woorden) <= 5 or regel.rstrip()[-1:] in '.!?:;,':
        return False
    if regel.isupper():
        return False                            # 'AAN DE SLAG': een rubriekkop van de pagina, geen stap
    if not volgende.lstrip()[:1].isupper():
        return False
    if re.fullmatch(r'\d{1,2}\.?', woorden[0]):
        woorden = woorden[1:]
    if not woorden or not woorden[0][:1].isupper():
        return False
    if any(re.search(r'\d', w) for w in woorden):
        return False
    kopwoorden = {w.strip('.,;:()!?*\'"').lower() for w in woorden if len(w) >= 3}
    for naam in ingredienten or ():
        if kopwoorden & {w.lower() for w in re.findall(r"[^\W\d_]{3,}", naam or '')}:
            return False                        # 'Peper en zout' is een ingrediënt, geen kopje
    return True


def _weggelaten_melding(regels):
    """Eén melding voor alles wat uit de bereiding is gehaald.

    Een aantal alleen ('27 regels weggelaten') is niet na te kijken. Wat er
    letterlijk in komt is elke regel die tekst zou kúnnen zijn: minstens twee
    gewone woorden. Regels met alleen een getal, een eenheid of één woord
    ('2 st', '40 g', 'Komkommer') en regels die een hoeveelheid én een
    ingrediëntnaam van het recept hadden, worden geteld: die zijn geen
    bereiding.
    """
    zeker = [r for r in regels if r.startswith('~')]
    rest = [r for r in regels if not r.startswith('~')]
    tekst = [r for r in rest if _gewone_woorden_op_rij(r) >= 2]
    kaal = len(rest) - len(tekst)
    delen = []
    if zeker:
        delen.append(f'{len(zeker)} ingrediëntregels')
    if kaal:
        delen.append(f'{kaal} regels met alleen een getal, eenheid of los woord')
    if tekst:
        delen.append('en verder: ' + ', '.join(_kort(r) for r in tekst[:_MELDING_MAX])
                      + (f' en {len(tekst) - _MELDING_MAX} meer' if len(tekst) > _MELDING_MAX else ''))
    return 'uit de bereiding weggelaten: ' + '; '.join(delen)


# Zo veel weggelaten tekstregels komen hooguit letterlijk in één melding.
_MELDING_MAX = 20


# Een zin bereidingstekst: vijf gewone woorden achter elkaar. Tabelregels,
# koppen en de paginavoet komen daar niet aan ('Peper en zout', '32 KIP',
# 'Energie (kJ/kcal)'); een regel proza vrijwel altijd wel. Gemeten op vier
# boeken (36 recepten): geen enkele tabelregel haalt het, en van de echte
# bereidingsregels alleen de korte staart van een afgebroken zin niet.
_ZIN_WOORDEN = 5


# Wat er na de laatste stap nog volgt en géén bereiding is: het weetje, de
# tip en de afsluiter van een receptkaart. Een 'Tip' vóór de laatste stap
# blijft gewoon in het gat zitten (zie _zonder_meubilair); dit gaat alleen
# over de staart.
_NAWOORD = re.compile(r"^\s*(weetje|tip|eet smakelijk)\b", re.IGNORECASE)


def _is_nawoord(regel):
    return bool(_NAWOORD.match(regel))


def _gewone_woorden_op_rij(regel):
    """Langste reeks opeenvolgende gewone woorden (letters, geen kapitalen).

    Eén letter is geen woord — een sierrand die de OCR als 'a b c d e' leest
    telde anders als vijf woorden en dus als zin — behalve de losse letters
    die in een recept echt een woord zijn ('u', 'à').
    """
    beste = reeks = 0
    for w in regel.split():
        kaal = w.strip('.,;:()!?*\'"').replace('-', '').replace("'", '')
        if (len(kaal) >= 2 or kaal in _LOSSE_LETTERWOORDEN) and kaal.isalpha() and not kaal.isupper():
            reeks += 1
            beste = max(beste, reeks)
        else:
            reeks = 0
    return beste


_LOSSE_LETTERWOORDEN = {'u', 'à'}


def _is_zin(regel):
    return _gewone_woorden_op_rij(regel) >= _ZIN_WOORDEN


def _is_meubilair(regel):
    """Een regel met hooguit één gewoon woord: een getal, een eenheid, een kop."""
    return sum(1 for w in regel.split()
               if w.strip('.,;:()!?*\'"').replace('-', '').isalpha()) <= 1


def _zonder_meubilair(gat):
    """Haal een tabel uit het gat tussen twee stappen. Geeft (tekst, weggelaten).

    Het gat begint en eindigt midden in een regel (daar staan de ankers); die
    twee stukken blijven altijd staan. Van de hele regels ertussen gaat een
    aaneengesloten blok weg dat met een meubilairregel begint én eindigt, en
    waar geen zin in voorkomt. Een korte regel vlak vóór of ná zo'n blok
    ('met sambal en/of ketchup.', 'Hamburgers bakken') blijft dus staan: die
    kan het staartje van een zin zijn. Op de HelloFresh-kaart is het blok 50
    regels tabel; op de kookboekpagina's komt er geen enkel blok in voor.
    """
    delen = gat.split('\n')
    if len(delen) < 5:
        return gat, []
    midden = delen[1:-1]
    houden = [True] * len(midden)
    weggelaten = []
    i = 0
    while i < len(midden):
        if not _is_meubilair(midden[i]):
            i += 1
            continue
        j = i
        laatste_meubilair = i
        while j < len(midden) and not _is_zin(midden[j]):
            if _is_meubilair(midden[j]):
                laatste_meubilair = j
            j += 1
        if laatste_meubilair - i + 1 >= _MEUBILAIR_MIN:
            for k in range(i, laatste_meubilair + 1):
                houden[k] = False
                weggelaten.append(midden[k])
        i = max(j, laatste_meubilair + 1)
    if not weggelaten:
        return gat, []
    return '\n'.join([delen[0]] + [r for r, h in zip(midden, houden) if h] + [delen[-1]]), weggelaten


# Zo veel regels moet een blok minstens zijn om als tabel te tellen. Eén los
# stapnummer of paginanummer ('4') in een gat blijft dan gewoon staan: dat is
# zichtbare ruis, en een enkele regel weghalen op vorm alleen is het niet waard.
_MEUBILAIR_MIN = 3


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
    de stap.

    Een genummerde bereidingsstap begint óók met een cijfer ('2 Bak de kip
    gaar'), en die mag hier nooit voor een ingrediëntregel doorgaan. Twee
    dingen verraden hem: na het cijfer komt een hoofdletterwoord dat in geen
    ingrediëntnaam voorkomt (een werkwoord), en de cijfers van zulke regels
    tellen op: 1, 2, 3. Een ingrediëntenlijst doet geen van beide.

    Geeft (tekst, weggelaten): de weggelaten regels letterlijk, met een '~'
    ervoor als ze een hoeveelheid én een ingrediëntnaam hadden.
    """
    regels = stuk.split('\n')
    if len(regels) < 3:
        return stuk, []
    namen = set()
    for naam in ingredienten or []:
        namen |= set(re.findall(r'[^\W\d_]{3,}', naam.lower()))
    treffers = [i for i, r in enumerate(regels[1:-1], 1)
                if _is_ingredientregel(r, namen)]
    if len(treffers) < 2 or _is_nummering([regels[i] for i in treffers]):
        return stuk, []
    eerste, laatste = treffers[0], treffers[-1]
    if any(len(r) > _INGREDIENTREGEL_MAX for r in regels[eerste:laatste + 1]):
        return stuk, []
    # Blokkoppen, doorlopende namen en de paginavoet horen bij de lijst: kort,
    # hooguit drie gewone woorden. De bereiding zelf hervat met een regel over
    # de volle kolombreedte. De eerste en laatste regel van het stuk blijven
    # altijd staan, want daar staan de ankers.
    while eerste > 1 and _is_lijstregel(regels[eerste - 1], namen):
        eerste -= 1
    while laatste < len(regels) - 2 and _is_lijstregel(regels[laatste + 1], namen):
        laatste += 1
    weggelaten = [('~' if i in treffers else '') + regels[i] for i in range(eerste, laatste + 1)]
    # Soms plakt Vision de laatste ingrediëntregel vóór de lijst aan een regel
    # bereidingstekst ('1 handvol verse tijm, rozemarijn en/ spinazie geslonken
    # is, ...'). Wat eraf mag is het stuk dat woord voor woord met het begin
    # van een ingrediëntnaam overeenkomt — en alleen als die naam op deze regel
    # níét afloopt, want dan weten we dat de regel afgebroken en geplakt is.
    if eerste > 1 and _HOEVEELHEID.match(regels[eerste - 1]):
        rest = _zonder_ingredientprefix(regels[eerste - 1], ingredienten)
        if rest is not None:
            weggelaten.append(regels[eerste - 1][:len(regels[eerste - 1]) - len(rest)].rstrip())
            regels[eerste - 1] = rest
    return '\n'.join(regels[:eerste] + regels[laatste + 1:]), weggelaten


def _is_ingredientregel(regel, namen):
    """Hoeveelheid vooraan, kort, deelt een woord met een ingrediëntnaam, en
    geen zinsbegin (hoofdletterwoord dat geen ingrediënt is) na het cijfer."""
    if not _HOEVEELHEID.match(regel) or len(regel) > _INGREDIENTREGEL_MAX:
        return False
    woorden = re.findall(r'[^\W\d_]{3,}', regel.lower())
    if not namen & set(woorden):
        return False
    delen = regel.split()
    tweede = delen[1] if len(delen) > 1 else ''
    if tweede[:1].isupper() and not tweede[1:2].isupper() and tweede.lower() not in namen:
        return False
    return True


def _is_lijstregel(regel, namen):
    """Mag het weg te laten blok over deze buurregel heen worden uitgebreid?"""
    if len(regel) > _INGREDIENTREGEL_MAX:
        return False
    if _HOEVEELHEID.match(regel):
        return _is_ingredientregel(regel, namen) or _gewone_woorden_op_rij(regel) <= 3
    return _gewone_woorden_op_rij(regel) <= 3


def _is_nummering(regels):
    """Beginnen deze regels met 1, 2, 3, ...? Dan is het een genummerde lijst
    stappen en geen ingrediëntenlijst."""
    getallen = []
    for r in regels:
        m = re.match(r'(\d+)\s', r)
        if not m:
            return False
        getallen.append(int(m.group(1)))
    return all(b == a + 1 for a, b in zip(getallen, getallen[1:]))


def _zonder_ingredientprefix(regel, ingredienten):
    """De regel zonder de ingrediëntregel waarmee hij begint, of None.

    Na de hoeveelheid en een eventueel maatwoord moeten minstens twee woorden
    van een ingrediëntnaam volgen, en de naam mag op deze regel niet afgelopen
    zijn: 'verse tijm, rozemarijn en/' loopt door op de volgende regel ('of
    laurier'), en dát is het bewijs dat hier een afgebroken ingrediëntregel aan
    de bereiding is geplakt. Een regel waarin de hele naam staat ('1 el extra
    vierge olijfolie erbij en roer') kan net zo goed een bereidingszin zijn,
    en blijft heel.
    """
    woorden = regel.split()
    kaal = [re.sub(r'[^\w/]+$', '', w).lower() for w in woorden]
    for naam in ingredienten or []:
        naamw = [re.sub(r'[^\w/]+$', '', w).lower() for w in naam.split()]
        for begin in (1, 2):                       # direct na het getal, of na het maatwoord
            n = 0
            while n < len(naamw) and begin + n < len(kaal) and _zelfde_woord(kaal[begin + n], naamw[n]):
                n += 1
            if 2 <= n < len(naamw) and begin + n < len(woorden):
                return ' '.join(woorden[begin + n:])
    return None


def _kort(anker, n=_ANKER_KORT):
    anker = (anker if isinstance(anker, str) else repr(anker) if anker is not None else '').strip()
    return repr(anker[:n] + ('…' if len(anker) > n else ''))


def _zelfde_woord(regelwoord, naamwoord):
    """Gelijk, of een aan een schuine streep afgebroken woord ('en/' bij 'en/of')."""
    return regelwoord == naamwoord or (regelwoord.endswith('/') and naamwoord.startswith(regelwoord))
