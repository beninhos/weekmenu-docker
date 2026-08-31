# -*- coding: utf-8 -*-
"""Breuktekens terugwinnen die Tesseract niet kán uitvoeren.

Geen enkel meegeleverd Tesseract-model kent ½ ¼ ¾: die tekens staan niet in de
unicharset van nld, eng of het Latin-scriptmodel (na te gaan met
`combine_tessdata -u`). Tesseract kiest daarom het dichtstbijzijnde teken dat het
wél kent, en welk teken dat is hangt af van de omgeving. In deze ene pdf zagen we
½ terugkomen als '%', als 'Y', als 'M', als 'W' en als het tekenpaar 'Ya', en ¼
als '4'. Een correctie die alleen naar '%' kijkt vangt dus maar een deel.

Herstellen kan alleen door de pixels opnieuw te bekijken, en dat gebeurt hier met
twee signalen:

* Topologie. '%' bestaat uit twee gesloten rondjes en heeft dus twee gaten, '½'
  bestaat uit een 1, een schuine streep en een 2 en heeft er nul. Dat verschil
  overleeft blur en ruis veel beter dan enige vormvergelijking.
* Vorm. Het genormaliseerde silhouet van de glyph wordt vergeleken met datzelfde
  teken uit alle systeemfonts. Het alfabet bevat naast de breuken ook alle
  cijfers en letters, zodat de uitkomst 'dit is gewoon een 4' óók mogelijk is.
  Alleen als een breukteken als beste uit het hele alfabet komt, én met een
  duidelijke voorsprong, grijpen we in.
"""

import glob

import cv2
import numpy as np

BREUKEN = ("½", "¼", "¾")

# Het alfabet waarmee een verdachte glyph vergeleken wordt. De cijfers zijn de
# echte concurrentie, want een breuk staat op de plek van een hoeveelheid; de
# letters zitten erbij omdat Tesseract juist daarop uitwijkt als hij de breuk niet
# kan schrijven.
ALFABET = tuple("0123456789%abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ") + BREUKEN

# Onder deze glyphhoogte lopen de rondjes van een '%' dicht en telt de topologie
# nul gaten, waardoor een procentteken op een breuk gaat lijken. Gemeten over alle
# systeemfonts: vanaf 20 px geen enkele verwisseling meer, daaronder wel.
MIN_HOOGTE = 20


def _binarize(patch):
    """Grijswaardenpatch -> binair masker met inkt = 255, zo nodig opgeschaald."""
    g = np.asarray(patch, dtype=np.uint8)
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)
    f = max(1.0, 120.0 / max(1, g.shape[0]))
    if f > 1.0:
        g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    _, ink = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink


def count_holes(patch, min_area_frac=0.004):
    """Aantal ingesloten gaten in de inkt (het Euler-getal van de glyph).

    De achtergrond wordt gelabeld; alles wat de beeldrand niet raakt is een gat.
    Gaten kleiner dan `min_area_frac` van het vlak zijn ruis.
    """
    ink = cv2.copyMakeBorder(_binarize(patch), 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=0)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((ink == 0).astype(np.uint8), 4)
    rand = set(lab[0, :]) | set(lab[-1, :]) | set(lab[:, 0]) | set(lab[:, -1])
    drempel = min_area_frac * ink.size
    return sum(1 for i in range(1, n)
               if i not in rand and stats[i, cv2.CC_STAT_AREA] > drempel)


def _norm_shape(patch, size=48):
    """Silhouet van de glyph, uitgesneden en op een vast raster geschaald."""
    ink = _binarize(patch)
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return np.zeros((size, size), bool)
    ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.resize(ink, (size, size), interpolation=cv2.INTER_AREA) > 127


_TEMPLATES = None


def templates():
    """Silhouetten van het hele alfabet, in elk systeemfont dat het teken kent."""
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    from PIL import Image, ImageDraw, ImageFont
    fonts = sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True))
    tpl = {}
    for teken in ALFABET:
        vormen = []
        for pad in fonts:
            try:
                ft = ImageFont.truetype(pad, 64)
            except OSError:
                continue
            im = Image.new("L", (200, 200), 255)
            ImageDraw.Draw(im).text((25, 25), teken, font=ft, fill=0)
            a = np.asarray(im)
            ys, xs = np.nonzero(a < 128)
            if len(xs) == 0:
                continue
            vormen.append(_norm_shape(im.crop((xs.min(), ys.min(),
                                               xs.max() + 1, ys.max() + 1))))
        if vormen:
            tpl[teken] = vormen
    _TEMPLATES = tpl
    return tpl


def template_scores(patch):
    """Per teken de beste overeenkomst met het silhouet, tussen 0 en 1."""
    vorm = _norm_shape(patch)
    return {teken: max(float(np.mean(vorm == v)) for v in vormen)
            for teken, vormen in templates().items()}


def herken_breuk(patch, marge=0.02):
    """Is deze glyph een breukteken, en zo ja welk?

    Geeft (teken, uitleg). `teken` is None als het géén breuk is; dan blijft de
    lezing van Tesseract staan. We grijpen alleen in als een breukteken als beste
    uit het hele alfabet komt én met een duidelijke voorsprong: een verzonnen
    breuk in een boodschappenlijst is erger dan een gemiste.
    """
    hoogte = np.asarray(patch).shape[0]
    if hoogte < MIN_HOOGTE:
        return None, f"glyph is maar {hoogte} px hoog, te klein om te beoordelen"
    scores = template_scores(patch)
    if not scores:
        return None, "geen systeemfonts gevonden om mee te vergelijken"
    rangschikking = sorted(scores.items(), key=lambda kv: -kv[1])
    beste, beste_score = rangschikking[0]
    if beste not in BREUKEN:
        return None, f"lijkt het meest op {beste!r} ({beste_score:.2f}), geen breuk"

    tweede = next((s for t, s in rangschikking[1:] if t not in BREUKEN), 0.0)
    if beste_score - tweede < marge:
        return None, (f"{beste} en de dichtstbijzijnde niet-breuk liggen te dicht bij "
                      f"elkaar ({beste_score:.2f} tegen {tweede:.2f})")

    gaten = count_holes(patch)
    if gaten >= 2:
        return None, f"{gaten} gesloten rondjes: dit is een procentteken, geen breuk"
    if beste == "½" and gaten != 0:
        return None, f"vorm zegt ½ maar er zit {gaten} gat in; te onzeker"
    return beste, (f"{gaten} gaten en het silhouet past het best bij {beste} "
                   f"({beste_score:.2f} tegen {tweede:.2f} voor de beste niet-breuk)")
