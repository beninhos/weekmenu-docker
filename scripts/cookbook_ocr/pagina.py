# -*- coding: utf-8 -*-
"""De pijplijn van pagina naar ingrediëntenlijst.

Twee passages over de pagina:

  Eerste pas — waar staat wat.
    Tesseract met --psm 3 over de hele pagina, alleen voor de layout. Zijn
    blokken worden op horizontale overlap tot kolommen samengevoegd, en de
    ingrediëntenkolom is de kolom waarvan de meeste regels met een hoeveelheid
    beginnen.

  Tweede pas — wat staat er.
    Alleen die kolom nog eens door Tesseract, nu als los beeld. Dat scheelt
    aanzienlijk: met de bereidingstekst uit beeld leest hij de smalle kolom
    schoon, terwijl hij in de eerste pas op de plek van het breukteken losse
    letters verzint.

Daarna: cursieve regels zijn blokkoppen, ingesprongen regels horen bij de regel
erboven, en de breuktekens die Tesseract niet kán schrijven worden op pixel-
niveau teruggewonnen.
"""

import re

import cv2
import numpy as np

import breuken
import bron
import ocrlines

# Hoogte waarop we een verdachte glyph aan de breukclassificatie voorleggen. Bij
# een pdf renderen we het gebied daarvoor opnieuw en scherper.
BREUK_HOOGTE = 40

# Een hoeveelheid telt hooguit een paar tekens: '½', '1½', '½-1'. Langere woorden
# komen niet in aanmerking als breukteken.
MAX_HOEVEELHEID_LENGTE = 3

# Hoeveel regels een verticale groep moet tellen om als deel van de lijst mee te
# doen. Een paginanummer onder aan de kolom staat alleen; een ingrediëntenblok
# nooit. Wat afvalt komt in 'weggelaten' terecht, zodat het nooit stil gebeurt.
MIN_GROEP = 3

# Hoeveel graden schuiner dan de rest van de kolom een regel moet staan om op de
# schuinstand alleen al als cursieve blokkop te tellen. Gemeten in dit boek:
# koppen 14 tot 18 graden, gewone regels hooguit 7.
CURSIEF_MARGE = 10.0

# Niet elk cursief is even schuin: Lato-Italic haalt maar 7 graden. Een regel die
# minder schuin staat mag alsnog een kop zijn als er duidelijk extra witruimte
# boven staat, want een blokkop krijgt altijd lucht. 'Duidelijk extra' is de
# gebruikelijke regelruimte plus dit deel van een letterhoogte; op de testpagina
# zit de gewone ruimte op 9 px en die boven een kop op 33 tot 39.
CURSIEF_MARGE_ZWAK = 5.0
LUCHT_DEEL = 0.6

# Een regel die met een hoeveelheid begint: een getal, een breukteken, of allebei,
# eventueel als bereik ('2-3 eetlepels', '½-1 peper'). Hieraan herkennen we de
# ingrediëntenkolom. Let op de '%': zolang de breuken nog niet hersteld zijn,
# staat daar het teken dat Tesseract van een breuk maakte.
_GETAL = r"(?:[0-9]+(?:[.,][0-9]+)?\s*[½¼¾⅓⅔⅛%]?|[½¼¾⅓⅔⅛%])"
HOEVEELHEID = re.compile(rf"^\s*{_GETAL}(?:\s*[-–]\s*{_GETAL})?(?:\s|$)")


# ── Kolom kiezen ────────────────────────────────────────────────────────────

def hoeveelheidsaandeel(regels):
    """Welk deel van de regels met een hoeveelheid begint."""
    if not regels:
        return 0.0
    return sum(bool(HOEVEELHEID.match(r["text"])) for r in regels) / len(regels)


def kies_ingredientenkolom(kolommen, ondergrens=0.25, min_regels=3):
    """De kolom die de ingrediëntenlijst bevat.

    Een bereidingstekst begint vrijwel nooit met een getal, een ingrediëntenlijst
    bijna altijd. Op de testpagina is dat 0,67 tegen 0,00: ruim genoeg om er geen
    tweede signaal bij te hoeven halen. Elke kolom wordt eerst in verticale
    groepen geknipt, zodat het paginanummer onder aan de kolom niet meetelt.
    """
    kandidaten = []
    for kol in kolommen:
        for groep in ocrlines.verticale_groepen(ocrlines.lines(kol["words"])):
            if len(groep) >= min_regels:
                kandidaten.append({"kolom": kol, "score": hoeveelheidsaandeel(groep)})
    if not kandidaten:
        return None, 0.0
    beste = max(kandidaten, key=lambda k: k["score"])
    if beste["score"] < ondergrens:
        return None, beste["score"]
    return beste["kolom"], beste["score"]


def kolomknipsel(beeld, kolom, woordhoogte):
    """De kolom als los beeld, met een regelhoogte marge zodat niets afvalt."""
    rand = int(woordhoogte)
    box = (max(0, kolom["x0"] - rand), max(0, kolom["y0"] - rand),
           min(beeld.width, kolom["x1"] + rand), min(beeld.height, kolom["y1"] + rand))
    return beeld.crop(box), (box[0], box[1])


# ── Koppen en omgeslagen regels ─────────────────────────────────────────────

def schuinstand(beeld, x0, y0, x1, y1, bereik=25.0):
    """Schuinstand van de letters in graden, positief is naar rechts hellend.

    We scheren het knipsel over een reeks hoeken en houden de hoek waarbij de
    verticale projectie het meest gepiekt is: dan staan de stokken recht.
    """
    grijs = np.array(beeld.crop((x0, y0, x1, y1)).convert("L"))
    if grijs.shape[0] < 6 or grijs.shape[1] < 6:
        return 0.0
    _, crop = cv2.threshold(grijs, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    h, w = crop.shape
    beste, hoek = -1.0, 0.0
    for a in np.arange(-bereik, bereik + 0.1, 1.0):
        s = float(np.tan(np.radians(a)))
        m = np.float32([[1, s, -s * h / 2], [0, 1, 0]])
        r = cv2.warpAffine(crop, m, (w + int(abs(s) * h) + 2, h), flags=cv2.INTER_NEAREST)
        v = float(np.var((r > 0).sum(axis=0).astype(np.float64)))
        if v > beste:
            beste, hoek = v, float(a)
    return hoek


def _ruimte_boven(regels):
    """Per regel de witruimte erboven, en wat in deze kolom gebruikelijk is."""
    ruimtes = [None] + [regels[i]["y0"] - regels[i - 1]["y1"]
                        for i in range(1, len(regels))]
    echte = [r for r in ruimtes if r is not None]
    return ruimtes, (float(np.median(echte)) if echte else 0.0)


def markeer_koppen(regels, beeld, marge=CURSIEF_MARGE, zwakke_marge=CURSIEF_MARGE_ZWAK,
                   max_woorden=3):
    """Zet 'kop' op de regels die als blokkop gezet zijn.

    De koppen in dit boek zijn cursief, en de rechte regels in de kolom bepalen
    zelf de nullijn waartegen we dat afmeten. Dat werkt ook als de scan scheef
    staat of het papier bol ligt. Gemeten: koppen 14 tot 18 graden boven de
    nullijn, gewone regels hooguit 7.

    Omdat niet elk cursief even schuin is, telt een minder schuine regel ook mee
    zodra er duidelijk extra witruimte boven staat. Een regel die met een
    hoeveelheid begint is nooit een kop, hoe de meting ook uitvalt; dat vangt de
    korte regels af die toevallig scheef lijken.
    """
    hoeken = [schuinstand(beeld, r["x0"], r["y0"], r["x1"], r["y1"]) for r in regels]
    nullijn = float(np.median(hoeken)) if hoeken else 0.0
    ruimtes, gebruikelijk = _ruimte_boven(regels)
    woordhoogte = ocrlines.median_word_height([w for r in regels for w in r["words"]])
    for r, a, ruimte in zip(regels, hoeken, ruimtes):
        r["schuinstand"] = a - nullijn
        r["ruimte_boven"] = ruimte
        lucht = ruimte is None or ruimte > gebruikelijk + LUCHT_DEEL * woordhoogte
        r["kop"] = ((r["schuinstand"] >= marge
                     or (r["schuinstand"] >= zwakke_marge and lucht))
                    and len(r["text"].split()) <= max_woorden
                    and not HOEVEELHEID.match(r["text"]))
    return regels


def voeg_wraps_samen(regels, woordhoogte, marge=0.5):
    """Voeg ingesprongen vervolgregels bij de regel erboven.

    Een omgeslagen ingrediënt springt in ten opzichte van de regel waar het
    ingrediënt begon. We vergelijken daarom met de laatste NIET-ingesprongen
    regel en niet met één linkermarge voor de hele kolom: op een gefotografeerde
    pagina ligt het papier bol, en op de gemeten pagina schuift de linkerkant
    daardoor van x=124 bovenaan naar x=101 onderaan. Tegen één vaste marge zou de
    halve kolom ingesprongen lijken.
    """
    uit, basis = [], None
    for r in regels:
        if r["kop"]:
            uit.append(r)
            basis = None
            continue
        ingesprongen = basis is not None and r["x0"] > basis + marge * woordhoogte
        if ingesprongen and uit and not uit[-1]["kop"]:
            uit[-1]["text"] += " " + r["text"]
            uit[-1]["x1"] = max(uit[-1]["x1"], r["x1"])
            uit[-1]["y1"] = r["y1"]
        else:
            uit.append(r)
            basis = r["x0"]
    return uit


# ── Breuktekens ─────────────────────────────────────────────────────────────

def karakterboxen(knip, verschuiving, taal, psm):
    """Alle karakters met hun bbox in paginacoördinaten, in leesvolgorde."""
    import pytesseract
    dx, dy = verschuiving
    ruw = pytesseract.image_to_boxes(knip, lang=taal, config=f"--psm {psm}")
    uit = []
    for regel in ruw.splitlines():
        d = regel.split()
        if len(d) < 5:
            continue
        a, b, c, e = int(d[1]), int(d[2]), int(d[3]), int(d[4])
        # image_to_boxes rekent vanaf linksonder; wij vanaf linksboven
        uit.append({"teken": d[0], "x0": a + dx, "y0": knip.height - e + dy,
                    "x1": c + dx, "y1": knip.height - b + dy})
    return uit


def _binnen(kar, woord):
    mx, my = (kar["x0"] + kar["x1"]) / 2, (kar["y0"] + kar["y1"]) / 2
    return woord["x0"] <= mx <= woord["x1"] and woord["y0"] <= my <= woord["y1"]


def cijferhoogte(karakters):
    """Mediane hoogte van de cijfers in de kolom: de maat van een hoeveelheid."""
    hoogtes = [k["y1"] - k["y0"] for k in karakters if k["teken"].isdigit()]
    return float(np.median(hoogtes)) if hoogtes else 0.0


def breukkandidaten(regels, karakters, min_hoogte_deel=0.85):
    """Welke glyphs leggen we ter herkeuring voor aan de breukclassificatie?

    Een breukteken is een hoeveelheid, en een hoeveelheid staat vooraan de regel
    in een kort woordje: '½', '1½', '½-1'. We kijken daarom naar de eerste twee
    glyphs van het eerste woord van elke regel, maar alleen als dat woord hooguit
    drie tekens telt. Zonder die eis wordt de w van 'worcestersaus' een kandidaat,
    en die haalde in de proef inderdaad een hogere score voor ½ dan voor w.

    Tweede eis: de glyph moet zo hoog zijn als een cijfer in dezelfde kolom. Dat
    gooit de onderkast eruit, die maar tot de x-hoogte reikt.

    Een als '%' gelezen glyph mag altijd mee, waar in de regel hij ook staat: een
    procentteken in een ingrediëntenlijst is vrijwel altijd een verminkte breuk.
    """
    ondergrens = min_hoogte_deel * cijferhoogte(karakters)
    kandidaten, gezien = [], set()
    for regel in regels:
        woord = regel["words"][0] if regel["words"] else None
        if woord is None or len(woord["text"]) > MAX_HOEVEELHEID_LENGTE:
            continue
        in_woord = sorted((k for k in karakters if _binnen(k, woord)),
                          key=lambda k: k["x0"])
        for i, kar in enumerate(in_woord[:2]):
            if kar["y1"] - kar["y0"] < ondergrens:
                continue
            kandidaten.append({"kar": kar, "woord": woord, "index": i,
                               "regel": regel, "tekens": in_woord})
            gezien.add(id(kar))
    for kar in karakters:
        if kar["teken"] != "%" or id(kar) in gezien:
            continue
        for regel in regels:
            for woord in regel["words"]:
                if _binnen(kar, woord):
                    kandidaten.append({"kar": kar, "woord": woord,
                                       "index": None, "regel": regel,
                                       "tekens": None})
    return kandidaten


def _dekt(a, b, deel=0.5):
    """Beslaan twee karakter-bboxen grotendeels dezelfde inkt?"""
    smalst = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
    overlap = max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]))
    return smalst > 0 and overlap > deel * smalst


def _vervang(kandidaat, teken):
    """Zet het herkende breukteken op de juiste plek in de woordtekst.

    Tesseract maakt van één breukglyph soms twee tekens ('Ya' voor ½). Hun
    bboxen liggen dan over elkaar heen, want ze beschrijven dezelfde inkt. Alle
    tekens die de herkende glyph overlappen verdwijnen daarom mee.
    """
    woord, kar = kandidaat["woord"], kandidaat["kar"]
    tekst, i, gelezen = woord["text"], kandidaat["index"], kar["teken"]
    tekens = kandidaat.get("tekens")

    if tekens and len(tekens) == len(tekst) and "".join(k["teken"] for k in tekens) == tekst:
        nieuw = [teken if k is kar else (None if _dekt(k, kar) else t)
                 for k, t in zip(tekens, tekst)]
        woord["text"] = "".join(t for t in nieuw if t is not None)
    elif i is not None and i < len(tekst) and tekst[i] == gelezen:
        woord["text"] = tekst[:i] + teken + tekst[i + 1:]
    elif gelezen in tekst:
        woord["text"] = tekst.replace(gelezen, teken, 1)
    else:
        return False
    regel = kandidaat["regel"]
    regel["text"] = " ".join(w["text"] for w in regel["words"])
    return True


def herstel_breuken(regels, br, knip, verschuiving, taal, psm):
    """Win de breuktekens terug die Tesseract niet kán schrijven.

    Zie breuken.py: elke verdachte glyph wordt zo nodig scherper opnieuw uit de
    pdf gerenderd en dan op vorm en topologie beoordeeld. Komt er geen breuk uit,
    dan blijft de lezing van Tesseract ongemoeid.
    """
    karakters = karakterboxen(knip, verschuiving, taal, psm)
    verslag = []
    for kandidaat in breukkandidaten(regels, karakters):
        kar = kandidaat["kar"]
        if not mag_beoordelen(kar, br.herrenderbaar):
            continue
        patch, hergerenderd = br.knipsel((kar["x0"] - 2, kar["y0"] - 2,
                                          kar["x1"] + 2, kar["y1"] + 2), BREUK_HOOGTE)
        teken, uitleg = breuken.herken_breuk(patch.convert("L"))
        if teken is not None and _vervang(kandidaat, teken):
            verslag.append({"gelezen": kar["teken"], "teken": teken,
                            "hoogte": kar["y1"] - kar["y0"],
                            "hergerenderd": hergerenderd, "uitleg": uitleg})
    return verslag


# ── De pijplijn ─────────────────────────────────────────────────────────────

def lees_pagina(pad, pagina=0, schaal=4.0, taal="nld", psm_layout=3, psm_tekst=6):
    """Lees de ingrediëntenlijst van één pagina.

    Geeft een dict met 'blocks' (elk met 'header' en 'lines'), en diagnostiek:
    'reden' als er niets gevonden is, 'breuken' met wat er is bijgesteld, en
    'kolommen' met de gevonden tekstkolommen.
    """
    br = bron.Bron(pad, pagina, schaal)
    beeld = br.basis

    woorden = ocrlines.words(beeld, lang=taal, psm=psm_layout)
    if not woorden:
        return {"blocks": [], "reden": "Tesseract vond geen tekst op deze pagina",
                "kolommen": []}
    kolommen = ocrlines.columns(woorden)
    diagnose = []
    for k in kolommen:
        rs = ocrlines.lines(k["words"])
        diagnose.append({"x0": k["x0"], "x1": k["x1"], "regels": len(rs),
                         "hoeveelheden": hoeveelheidsaandeel(rs), "gekozen": False})
    kolom, score = kies_ingredientenkolom(kolommen)
    if kolom is None:
        return {"blocks": [], "kolommen": diagnose,
                "reden": f"geen ingrediëntenlijst gevonden (beste score {score:.2f})"}
    for k, d in zip(kolommen, diagnose):
        d["gekozen"] = k is kolom

    woordhoogte = ocrlines.median_word_height(kolom["words"])
    knip, verschuiving = kolomknipsel(beeld, kolom, woordhoogte)
    woorden = ocrlines.words(knip, lang=taal, psm=psm_tekst)
    if not woorden:
        return {"blocks": [], "kolommen": diagnose,
                "reden": "de gevonden kolom bleek onleesbaar"}
    dx, dy = verschuiving
    for w in woorden:
        w["x0"] += dx
        w["x1"] += dx
        w["y0"] += dy
        w["y1"] += dy

    regels, weggelaten = splits_groepen(ocrlines.lines(woorden))
    regels, voet = zonder_paginavoet(regels, ocrlines.median_word_height(woorden))
    weggelaten += voet
    if not regels:
        return {"blocks": [], "kolommen": diagnose, "weggelaten": weggelaten,
                "reden": "de kolom viel uiteen in te kleine stukken"}
    verslag = herstel_breuken(regels, br, knip, verschuiving, taal, psm_tekst)
    woordhoogte = ocrlines.median_word_height([w for r in regels for w in r["words"]])
    regels = voeg_wraps_samen(markeer_koppen(regels, beeld), woordhoogte)

    return {"blocks": naar_blokken(regels), "breuken": verslag,
            "kolommen": diagnose, "weggelaten": weggelaten}


def zonder_paginavoet(regels, woordhoogte, marge=1.0):
    """Haal een aanhangende paginavoet ('84 RUND') van de lijst af.

    Aan de witruimte erboven is een voet niet te herkennen: op pagina 14 staat
    hij op 2,03 maal de regelafstand en de blokkoppen op 2,00 tot 2,07. Wat hem
    wél verraadt is dat hij in de paginamarge staat, links van de tekstkolom:
    x=91 tegen x=116 voor de ingrediënten. Regels binnen de kolom schuiven bij een
    bolle pagina hooguit een paar pixels per regel op, dus een uitspringing van
    een hele letterhoogte is er geen van.

    Geeft (regels, weggelaten_teksten).
    """
    if len(regels) < 3:
        return regels, []
    laatste, vorige = regels[-1], regels[-2]
    if laatste["x0"] < vorige["x0"] - marge * woordhoogte:
        return regels[:-1], [laatste["text"]]
    return regels, []


def splits_groepen(regels, min_groep=MIN_GROEP):
    """Verdeel de regels in wat we houden en wat afvalt.

    Een kolom kan uiteenvallen in verticale groepen: blokken met veel lucht
    ertussen, en het paginanummer onder aan de bladspiegel. Alles met minstens
    `min_groep` regels hoort bij de lijst; de rest valt af en wordt gemeld, want
    stilzwijgend een heel ingrediëntenblok laten verdwijnen is het ergste wat
    deze stap kan doen.
    """
    groepen = ocrlines.verticale_groepen(regels)
    gehouden = [r for g in groepen if len(g) >= min_groep for r in g]
    weggelaten = [r["text"] for g in groepen if len(g) < min_groep for r in g]
    return gehouden, weggelaten


def mag_beoordelen(karakter, herrenderbaar, min_hoogte=None):
    """Is deze glyph groot genoeg om er een breukoordeel over te vellen?

    Bij een pdf kunnen we het gebied scherper opnieuw renderen en is elke hoogte
    goed. Bij een losse afbeelding voegt opschalen niets toe, en onder de
    minimumhoogte lopen de rondjes van een procentteken dicht — dan is het
    topologische signaal weg en laten we de lezing van Tesseract staan.
    """
    if herrenderbaar:
        return True
    grens = breuken.MIN_HOOGTE if min_hoogte is None else min_hoogte
    return (karakter["y1"] - karakter["y0"]) >= grens


def naar_blokken(regels):
    """Groepeer de regels onder hun kop."""
    blokken, huidig = [], {"header": None, "lines": []}
    for r in regels:
        if r["kop"]:
            if huidig["lines"]:
                blokken.append(huidig)
            huidig = {"header": r["text"], "lines": []}
        else:
            huidig["lines"].append(r["text"])
    if huidig["lines"]:
        blokken.append(huidig)
    return blokken
