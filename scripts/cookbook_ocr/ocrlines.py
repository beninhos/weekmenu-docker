# -*- coding: utf-8 -*-
"""Kolommen en regels reconstrueren uit de woord-bboxen van Tesseract.

De kolomindeling komt van Tesseract's eigen layoutanalyse (--psm 3). Die is op
deze scans betrouwbaarder dan een zelfgebouwde goot-detectie: op sommige
pagina's is de witte goot tussen de ingrediëntenkolom en de bereidingstekst
maar 13 pixels breed, smaller dan een regelhoogte, terwijl de layoutanalyse van
Tesseract hem met zijn tabstop-detectie wel vindt.

Wat we er zelf overheen doen is het samenvoegen van blokken tot kolommen, en het
opbouwen van regels binnen een kolom. Dat laatste is nodig omdat Tesseract bij
--psm 3 een enkel blok soms nog over twee kolommen uitsmeert.
"""

import re

import numpy as np
import pytesseract
from pytesseract import Output

# Een 'woord' zonder enige betekenisdrager is vuil van de scan: een randje van de
# kaderlijn, een vouw in het papier, een vlekje. Let op dat '%' hier WEL meetelt:
# dat is een van de tekens waar Tesseract een breukteken in verstopt.
_BETEKENIS = re.compile(r"[0-9A-Za-zÀ-ÿ½¼¾⅓⅔⅛%/]")


def _is_vuil(tekst):
    return _BETEKENIS.search(tekst) is None


def words(image, lang="nld", psm=3, extra=""):
    """Alle woorden met bbox, confidence en de blok-, alinea- en regelnummers."""
    cfg = f"--psm {psm} {extra}".strip()
    d = pytesseract.image_to_data(image, lang=lang, config=cfg, output_type=Output.DICT)
    out = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if not t or float(d["conf"][i]) < 0:
            continue
        out.append({
            "text": t, "conf": float(d["conf"][i]),
            "x0": d["left"][i], "y0": d["top"][i],
            "x1": d["left"][i] + d["width"][i], "y1": d["top"][i] + d["height"][i],
            "blok": d["block_num"][i], "alinea": d["par_num"][i], "regel": d["line_num"][i],
        })
    return out


def median_word_height(ws):
    return float(np.median([w["y1"] - w["y0"] for w in ws])) if ws else 1.0


def _omhullende(ws):
    return (min(w["x0"] for w in ws), min(w["y0"] for w in ws),
            max(w["x1"] for w in ws), max(w["y1"] for w in ws))


def blokken(ws, min_conf=30):
    """Groepeer de woorden per blok van Tesseract's layoutanalyse."""
    per_blok = {}
    for w in ws:
        if w["conf"] < min_conf or _is_vuil(w["text"]):
            continue
        per_blok.setdefault(w["blok"], []).append(w)
    uit = []
    for nr, leden in per_blok.items():
        if len(leden) < 2:
            continue
        x0, y0, x1, y1 = _omhullende(leden)
        uit.append({"nr": nr, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "words": leden})
    return sorted(uit, key=lambda b: (b["x0"], b["y0"]))


def _overlapt(a, b, deel=0.3):
    """Overlappen twee blokken horizontaal genoeg om één kolom te zijn?"""
    breedte = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
    return max(0, min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])) > deel * max(1, breedte)


# Hoe breed een verticale corridor door een kolom moet zijn, in letterhoogtes,
# om als kolomscheiding te tellen. Gemeten over vijf pagina's waar de layout-
# analyse het goed deed: geen enkele juiste kolom bevat een corridor van 0,4
# letterhoogte of breder. Op de pagina waar twee kolommen ten onrechte
# samengevoegd waren, zit er precies één, van 1,35.
CORRIDOR_DEEL = 0.5


def _corridors(kolom, min_gap):
    """De x-posities waar geen enkel woord van de kolom overheen loopt.

    Omdat de dekking over alle regels heen wordt opgeteld, is zo'n corridor per
    definitie over de volle hoogte leeg. Een spatie tussen twee woorden op één
    regel valt er dus niet onder, tenzij hij op élke regel op dezelfde plek zit.
    """
    breedte = kolom["x1"] - kolom["x0"] + 2
    dekking = np.zeros(breedte, bool)
    for w in kolom["words"]:
        dekking[w["x0"] - kolom["x0"]:w["x1"] - kolom["x0"]] = True
    idx = np.flatnonzero(np.diff(np.concatenate(([0], dekking.view(np.int8), [0]))))
    stukken = list(zip(idx[0::2], idx[1::2]))
    return [kolom["x0"] + int(stukken[i][1])
            for i in range(len(stukken) - 1)
            if stukken[i + 1][0] - stukken[i][1] >= min_gap]


def _splits_op_corridors(kolom, min_gap, min_woorden=6):
    """Knip een kolom in stukken op zijn lege verticale corridors.

    Tesseract's layoutanalyse voegt twee kolommen soms samen als de goot ertussen
    smal is. Dit is de reparatie achteraf; op een kolom die al goed is verandert
    het niets, want die heeft geen corridor.
    """
    grenzen = _corridors(kolom, min_gap)
    if not grenzen:
        return [kolom]
    randen = [kolom["x0"]] + grenzen + [kolom["x1"] + 1]
    delen = []
    for a, b in zip(randen, randen[1:]):
        leden = [w for w in kolom["words"] if a <= w["x0"] < b]
        if len(leden) < min_woorden:
            continue
        deel = {"blokken": kolom["blokken"], "words": leden}
        deel["x0"], deel["y0"], deel["x1"], deel["y1"] = _omhullende(leden)
        delen.append(deel)
    return delen or [kolom]


def columns(ws, min_conf=30):
    """Voeg de blokken samen tot kolommen op horizontale overlap."""
    bs = blokken(ws, min_conf)
    kolommen = []
    for b in bs:
        for k in kolommen:
            if any(_overlapt(b, ander) for ander in k["blokken"]):
                k["blokken"].append(b)
                k["words"].extend(b["words"])
                break
        else:
            kolommen.append({"blokken": [b], "words": list(b["words"])})
    for k in kolommen:
        k["x0"], k["y0"], k["x1"], k["y1"] = _omhullende(k["words"])

    min_gap = CORRIDOR_DEEL * median_word_height([w for k in kolommen for w in k["words"]])
    gesplitst = [d for k in kolommen for d in _splits_op_corridors(k, min_gap)]
    return sorted(gesplitst, key=lambda k: k["x0"])


def lines(ws):
    """Regels binnen één kolom, op de blok-, alinea- en regelnummers van Tesseract.

    Die nummering hangt aan de gevonden basislijnen en is daarmee steviger dan
    zelf clusteren op y-overlap: woorden met en zonder staartletters hebben nogal
    verschillende bboxen, en twee opeenvolgende regels raken elkaar dan al gauw.
    """
    per_regel = {}
    for w in ws:
        per_regel.setdefault((w["blok"], w["alinea"], w["regel"]), []).append(w)
    uit = []
    for leden in per_regel.values():
        leden = sorted(leden, key=lambda w: w["x0"])
        x0, y0, x1, y1 = _omhullende(leden)
        uit.append({
            "text": " ".join(w["text"] for w in leden), "words": leden,
            "x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "conf": float(np.mean([w["conf"] for w in leden])),
        })
    return sorted(uit, key=lambda r: r["y0"])


def verticale_groepen(regels, factor=4.0):
    """Splits regels waar een verticaal gat veel groter is dan de regelafstand.

    Zo valt het paginanummer onderaan de kolom er vanzelf af: dat staat vijf tot
    twintig regelhoogtes onder de laatste ingrediëntregel.
    """
    if len(regels) < 2:
        return [regels] if regels else []
    stappen = np.diff([r["y0"] for r in regels])
    afstand = float(np.median(stappen)) if len(stappen) else 0.0
    if afstand <= 0:
        return [regels]
    groepen, huidig = [], [regels[0]]
    for stap, r in zip(stappen, regels[1:]):
        if stap > factor * afstand:
            groepen.append(huidig)
            huidig = [r]
        else:
            huidig.append(r)
    groepen.append(huidig)
    return groepen
