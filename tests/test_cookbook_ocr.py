# -*- coding: utf-8 -*-
"""Tests voor scripts/cookbook_ocr.

Deze tests draaien zonder tesseract en zonder de bron-pdf: ze voeden de
losse stappen met verzonnen regels en met zelfgerenderde glyphs. De pijplijn als
geheel is gemeten tegen de echte pagina; zie scripts/cookbook_ocr/README.md.
"""

import glob
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts", "cookbook_ocr"))

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")

import breuken  # noqa: E402
import ocrlines  # noqa: E402
import pagina  # noqa: E402

from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def _regel(text, x0, y0, hoogte=16, breedte=None):
    """Een regel zoals ocrlines.lines hem oplevert, met één woord per token."""
    woorden, x = [], x0
    for t in text.split():
        w = len(t) * 8
        woorden.append({"text": t, "x0": x, "x1": x + w,
                        "y0": y0, "y1": y0 + hoogte, "conf": 90.0})
        x += w + 6
    return {"text": text, "words": woorden, "x0": x0,
            "x1": breedte or x, "y0": y0, "y1": y0 + hoogte, "conf": 90.0,
            "kop": False}


# ── Herkennen van een hoeveelheid ───────────────────────────────────────────

@pytest.mark.parametrize("regel", [
    "1 mok (300 g) snelkookzilvervlies-",
    "200 g jonge bladspinazie",
    "½ bosje verse tijm",
    "% bosje verse tijm",          # zoals tesseract het leest, vóór herstel
    "2-3 eetlepels rodewijnazijn",
    "1,5 liter bouillon",
])
def test_hoeveelheid_herkend(regel):
    assert pagina.HOEVEELHEID.match(regel)


@pytest.mark.parametrize("regel", [
    "olijfolie",
    "worcestersaus",
    "Stroganoff",
    "zonder vetrandjes",
    "Doe 1 mok rijst met 2 mokken kokend water",
    "Parmezaanse kaas, voor erbij",
])
def test_geen_hoeveelheid(regel):
    assert not pagina.HOEVEELHEID.match(regel)


def test_hoeveelheidsaandeel_scheidt_de_kolommen():
    ingredienten = [_regel("2 kleine rode uien", 120, 0),
                    _regel("1 handvol augurken", 120, 30),
                    _regel("olijfolie", 120, 60)]
    bereiding = [_regel("Doe de uien in de pan", 500, 0),
                 _regel("en roer af en toe", 500, 30),
                 _regel("tot ze glazig zijn", 500, 60)]
    assert pagina.hoeveelheidsaandeel(ingredienten) > pagina.hoeveelheidsaandeel(bereiding)
    assert pagina.hoeveelheidsaandeel(bereiding) == 0.0


# ── Omgeslagen regels samenvoegen ───────────────────────────────────────────

def test_ingesprongen_regel_hoort_bij_de_regel_erboven():
    regels = [_regel("1 mok (300 g) snelkookzilvervlies-", 129, 0),
              _regel("of basmatirijst", 145, 30),
              _regel("½ bosje verse tijm", 129, 60)]
    uit = pagina.voeg_wraps_samen(regels, woordhoogte=16)
    assert [r["text"] for r in uit] == [
        "1 mok (300 g) snelkookzilvervlies- of basmatirijst",
        "½ bosje verse tijm",
    ]


def test_bolle_pagina_levert_geen_valse_inspringing():
    """De linkermarge schuift geleidelijk op; dat mag geen vervolgregel worden."""
    regels = [_regel(f"{n} iets", x, 30 * i)
              for i, (n, x) in enumerate([(1, 124), (2, 122), (3, 120), (4, 118),
                                          (5, 116), (6, 114), (7, 112), (8, 110)])]
    uit = pagina.voeg_wraps_samen(regels, woordhoogte=16)
    assert len(uit) == 8


def test_kop_breekt_de_inspringing_af():
    regels = [_regel("2 entrecotes van 200 g elk,", 124, 0),
              _regel("zonder vetrandjes", 142, 30),
              _regel("Stroganoff", 124, 60),
              _regel("300 g gemengde paddenstoelen", 130, 90)]
    regels[2]["kop"] = True
    uit = pagina.voeg_wraps_samen(regels, woordhoogte=16)
    assert [r["text"] for r in uit] == [
        "2 entrecotes van 200 g elk, zonder vetrandjes",
        "Stroganoff",
        "300 g gemengde paddenstoelen",
    ]


# ── Verticale groepen ───────────────────────────────────────────────────────

def test_paginanummer_valt_in_een_eigen_groep():
    regels = [_regel(f"{n} iets", 120, 30 * i) for i, n in enumerate(range(1, 8))]
    regels.append(_regel("72 RUND", 120, 900))
    groepen = ocrlines.verticale_groepen(regels)
    assert len(groepen) == 2
    assert [r["text"] for r in groepen[1]] == ["72 RUND"]


def test_gelijkmatige_regels_blijven_een_groep():
    regels = [_regel(f"{n} iets", 120, 30 * i) for i, n in enumerate(range(1, 10))]
    assert len(ocrlines.verticale_groepen(regels)) == 1


# ── Vuil van de scan ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tekst,vuil", [
    ("_", True), ("|", True), ("--", True), (".", True),
    ("%", False), ("½", False), ("1", False), ("olijfolie", False),
])
def test_vuilfilter_spaart_het_procentteken(tekst, vuil):
    assert ocrlines._is_vuil(tekst) is vuil


# ── Breuktekens ─────────────────────────────────────────────────────────────

def _render(teken, size=64):
    """Rendert een teken in elk systeemfont dat het kent."""
    for pad in sorted(glob.glob("/usr/share/fonts/**/*.ttf", recursive=True)):
        try:
            ft = ImageFont.truetype(pad, size)
        except OSError:
            continue
        im = Image.new("L", (size * 4, size * 4), 245)
        ImageDraw.Draw(im).text((size, size), teken, font=ft, fill=40)
        a = np.asarray(im)
        ys, xs = np.nonzero(a < 170)
        if len(xs) == 0:
            continue
        yield os.path.basename(pad), im.crop((xs.min() - 2, ys.min() - 2,
                                              xs.max() + 3, ys.max() + 3))


def test_gatentelling_scheidt_procent_van_half():
    """Het topologische onderscheid waar de hele correctie op rust."""
    for naam, glyph in _render("%"):
        assert breuken.count_holes(glyph) == 2, f"% in {naam}"
    for naam, glyph in _render("½"):
        assert breuken.count_holes(glyph) == 0, f"½ in {naam}"


@pytest.mark.parametrize("teken", ["½", "¼", "¾"])
def test_breuk_wordt_herkend(teken):
    goed = sum(breuken.herken_breuk(g)[0] == teken for _, g in _render(teken))
    totaal = sum(1 for _ in _render(teken))
    assert goed >= 0.9 * totaal, f"{teken}: maar {goed}/{totaal} herkend"


@pytest.mark.parametrize("teken", ["%", "0", "1", "2", "3", "4", "5", "6",
                                   "7", "8", "9", "w", "M", "Y", "V"])
def test_geen_breuk_verzonnen(teken):
    """Het belangrijkste: een echt teken mag nooit een breuk worden."""
    fout = [(naam, breuken.herken_breuk(g)[0])
            for naam, g in _render(teken) if breuken.herken_breuk(g)[0] is not None]
    assert not fout, f"{teken} werd een breuk in: {fout[:3]}"


def test_te_kleine_glyph_wordt_niet_beoordeeld():
    glyph = next(g for _, g in _render("½"))
    klein = glyph.resize((max(1, glyph.width // 8), breuken.MIN_HOOGTE - 1))
    teken, uitleg = breuken.herken_breuk(klein)
    assert teken is None
    assert "px hoog" in uitleg


# ── Cursiefdetectie ─────────────────────────────────────────────────────────

def _tekstbeeld(tekst, fontpad, size=40):
    ft = ImageFont.truetype(fontpad, size)
    im = Image.new("L", (size * len(tekst), size * 2), 245)
    ImageDraw.Draw(im).text((4, 4), tekst, font=ft, fill=40)
    return im.convert("RGB")


RECHT = "/usr/share/fonts/truetype/lato/Lato-Regular.ttf"
CURSIEF = "/usr/share/fonts/truetype/lato/Lato-Italic.ttf"


def test_cursief_meet_hoger_dan_recht():
    if not (os.path.exists(RECHT) and os.path.exists(CURSIEF)):
        pytest.skip("Lato niet geïnstalleerd")
    a = pagina.schuinstand(_tekstbeeld("Stroganoff", RECHT), 0, 0, 400, 80)
    b = pagina.schuinstand(_tekstbeeld("Stroganoff", CURSIEF), 0, 0, 400, 80)
    assert b - a >= pagina.CURSIEF_MARGE_ZWAK


def _kolombeeld(regels, fonts, size=26, regelafstand=34):
    """Rendert een kolommetje en levert de regels met hun echte bboxen."""
    hoogte = 40 + regelafstand * len(regels) + 60
    im = Image.new("L", (460, hoogte), 245)
    d = ImageDraw.Draw(im)
    uit, y = [], 20
    for tekst, fontpad, extra in regels:
        y += extra
        ft = ImageFont.truetype(fontpad, size)
        d.text((30, y), tekst, font=ft, fill=40)
        x0, y0, x1, y1 = d.textbbox((30, y), tekst, font=ft)
        uit.append({"text": tekst, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "kop": False,
                    "words": [{"text": t, "x0": x0, "x1": x1, "y0": y0, "y1": y1}
                              for t in tekst.split()]})
        y += regelafstand
    return im.convert("RGB"), uit


def test_kop_herkend_ondanks_bescheiden_cursief():
    """Lato-Italic haalt maar 7 graden; de witruimte erboven moet bijspringen."""
    if not (os.path.exists(RECHT) and os.path.exists(CURSIEF)):
        pytest.skip("Lato niet geïnstalleerd")
    beeld, regels = _kolombeeld([
        ("Rijst", CURSIEF, 0),
        ("1 mok bulghur", RECHT, 0),
        ("200 g spinazie", RECHT, 0),
        ("olijfolie", RECHT, 0),
        ("Zuur", CURSIEF, 26),
        ("2 kleine rode uien", RECHT, 0),
        ("1 handvol augurken", RECHT, 0),
    ], [])
    pagina.markeer_koppen(regels, beeld)
    assert [r["text"] for r in regels if r["kop"]] == ["Rijst", "Zuur"]


# ── Blokken, corridors en vervangingen ──────────────────────────────────────
# Deze tests bestaan omdat een mutatieproef liet zien dat de suite eromheen
# groen bleef: koppen negeren, de breukvervanging uitzetten, de corridor-
# reparatie slopen en lines() niet meer op y sorteren werden geen van alle
# opgemerkt.

def test_naar_blokken_groepeert_onder_de_kop():
    regels = [_regel("Rijst", 120, 0), _regel("1 mok bulghur", 120, 30),
              _regel("Zuur", 120, 90), _regel("2 uien", 120, 120),
              _regel("1 augurk", 120, 150)]
    regels[0]["kop"] = regels[2]["kop"] = True
    blokken = pagina.naar_blokken(regels)
    assert [(b["header"], b["lines"]) for b in blokken] == [
        ("Rijst", ["1 mok bulghur"]),
        ("Zuur", ["2 uien", "1 augurk"]),
    ]


def test_regels_voor_de_eerste_kop_krijgen_geen_kop():
    regels = [_regel("1 mok bulghur", 120, 0), _regel("Zuur", 120, 30),
              _regel("2 uien", 120, 60)]
    regels[1]["kop"] = True
    blokken = pagina.naar_blokken(regels)
    assert blokken[0]["header"] is None
    assert blokken[0]["lines"] == ["1 mok bulghur"]


def _kar(teken, x0, x1, y0=0, y1=15):
    return {"teken": teken, "x0": x0, "x1": x1, "y0": y0, "y1": y1}


def test_vervangt_het_juiste_teken_in_het_woord():
    regel = _regel("1 bosje tijm", 100, 0)
    woord = regel["words"][0]
    woord["text"] = "1%"
    woord["x0"], woord["x1"] = 100, 130
    kandidaat = {"woord": woord, "regel": regel, "index": 1,
                 "kar": _kar("%", 115, 130), "tekens": None}
    assert pagina._vervang(kandidaat, "½") is True
    assert woord["text"] == "1½"
    assert regel["text"].startswith("1½ ")


def test_overlappende_tekens_van_dezelfde_glyph_verdwijnen_mee():
    """Tesseract maakt van één ½-glyph soms 'Ya'; beide vakjes dekken dezelfde inkt."""
    regel = _regel("Ya blik kokosmelk", 100, 0)
    woord = regel["words"][0]
    woord["x0"], woord["x1"] = 111, 124
    tekens = [_kar("Y", 111, 117), _kar("a", 111, 124)]
    kandidaat = {"woord": woord, "regel": regel, "index": 1,
                 "kar": tekens[1], "tekens": tekens}
    assert pagina._vervang(kandidaat, "½") is True
    assert woord["text"] == "½"


def test_corridor_splitst_twee_kolommen_die_tesseract_samenvoegde():
    """Een goot over de volle hoogte hoort twee kolommen te scheiden."""
    def w(t, x0, x1, y0):
        return {"text": t, "x0": x0, "x1": x1, "y0": y0, "y1": y0 + 16,
                "conf": 90.0, "blok": 1, "alinea": 1, "regel": y0 // 30}
    # links een smalle kolom, rechts een brede, met één goot van 40 px ertussen
    # en binnen elke kolom alleen woordspaties van vier pixels
    woorden = []
    for i in range(6):
        woorden += [w("1", 100, 114, 30 * i), w("mok", 118, 160, 30 * i),
                    w("Doe", 200, 244, 30 * i), w("de", 248, 280, 30 * i)]
    kolom = {"blokken": [], "words": woorden}
    kolom["x0"], kolom["y0"], kolom["x1"], kolom["y1"] = ocrlines._omhullende(woorden)
    delen = ocrlines._splits_op_corridors(kolom, min_gap=8)
    assert len(delen) == 2
    assert delen[0]["x1"] < delen[1]["x0"]


def test_kolom_zonder_corridor_blijft_heel():
    def w(t, x0, y0):
        return {"text": t, "x0": x0, "x1": x0 + 40, "y0": y0, "y1": y0 + 16,
                "conf": 90.0, "blok": 1, "alinea": 1, "regel": y0 // 30}
    woorden = [w("1", 100 + 45 * (i % 3), 30 * i) for i in range(12)]
    kolom = {"blokken": [], "words": woorden}
    kolom["x0"], kolom["y0"], kolom["x1"], kolom["y1"] = ocrlines._omhullende(woorden)
    assert len(ocrlines._splits_op_corridors(kolom, min_gap=8)) == 1


def test_regels_komen_in_leesvolgorde():
    def w(t, y0, regel):
        return {"text": t, "x0": 10, "x1": 60, "y0": y0, "y1": y0 + 16,
                "conf": 90.0, "blok": 1, "alinea": 1, "regel": regel}
    # opzettelijk door elkaar aangeboden, zodat noch de volgorde van invoer
    # noch de omgekeerde daarvan toevallig goed is
    woorden = [w("midden", 100, 2), w("onder", 200, 3), w("boven", 10, 1)]
    assert [r["text"] for r in ocrlines.lines(woorden)] == ["boven", "midden", "onder"]


def test_woorden_binnen_een_regel_staan_van_links_naar_rechts():
    woorden = [
        {"text": "bulghur", "x0": 80, "x1": 140, "y0": 10, "y1": 26, "conf": 90.0,
         "blok": 1, "alinea": 1, "regel": 1},
        {"text": "1", "x0": 10, "x1": 20, "y0": 10, "y1": 26, "conf": 90.0,
         "blok": 1, "alinea": 1, "regel": 1},
        {"text": "mok", "x0": 30, "x1": 70, "y0": 10, "y1": 26, "conf": 90.0,
         "blok": 1, "alinea": 1, "regel": 1},
    ]
    assert ocrlines.lines(woorden)[0]["text"] == "1 mok bulghur"


# ── De breukherkenning op de grootte waarop hij echt werkt ──────────────────

def test_geen_breuk_verzonnen_op_de_patchgrootte_van_de_pijplijn():
    """De pijplijn biedt patches van ongeveer BREUK_HOOGTE px aan, niet van 64."""
    fout = []
    for teken in ("%", "0", "1", "4", "8", "w", "M", "Y", "V", "X"):
        for naam, glyph in _render(teken, size=28):
            h = pagina.BREUK_HOOGTE
            op_maat = glyph.resize((max(1, glyph.width * h // glyph.height), h),
                                   Image.LANCZOS)
            uit, _ = breuken.herken_breuk(op_maat)
            if uit is not None:
                fout.append((teken, naam, uit))
    assert not fout, f"verzonnen breuken: {fout[:5]}"


def test_sterke_cursiefdrempel_doet_er_werkelijk_toe():
    """Een uitgesproken cursief moet ook zonder extra witruimte een kop zijn."""
    if not (os.path.exists(RECHT) and os.path.exists(CURSIEF)):
        pytest.skip("Lato niet geïnstalleerd")
    beeld, regels = _kolombeeld([
        ("1 mok bulghur", RECHT, 0),
        ("Zuur", CURSIEF, 0),          # geen extra lucht erboven
        ("2 kleine rode uien", RECHT, 0),
    ], [])
    # de zwakke regel mag hier niet helpen: er is geen extra witruimte
    pagina.markeer_koppen(regels, beeld, marge=6.0)
    assert [r["text"] for r in regels if r["kop"]] == ["Zuur"]


# ── Verticale groepen mogen niets stil laten verdwijnen ─────────────────────

def test_blokken_met_veel_lucht_ertussen_blijven_allebei():
    """Extra witruimte tussen twee blokken mag er geen laten verdwijnen."""
    blok_a = [_regel(f"{n} iets", 120, 30 * i) for i, n in enumerate(range(1, 6))]
    blok_b = [_regel(f"{n} nog iets", 120, 400 + 30 * i)
              for i, n in enumerate(range(1, 5))]
    gehouden, weggelaten = pagina.splits_groepen(blok_a + blok_b)
    assert len(gehouden) == 9
    assert weggelaten == []


def test_paginanummer_valt_af_en_wordt_gemeld():
    regels = [_regel(f"{n} iets", 120, 30 * i) for i, n in enumerate(range(1, 8))]
    regels.append(_regel("72 RUND", 120, 900))
    gehouden, weggelaten = pagina.splits_groepen(regels)
    assert [r["text"] for r in gehouden] == [r["text"] for r in regels[:-1]]
    assert weggelaten == ["72 RUND"], "wat afvalt moet gemeld worden, niet verdwijnen"


def test_kleine_glyph_op_een_afbeelding_wordt_niet_beoordeeld():
    klein = {"teken": "%", "x0": 0, "x1": 14, "y0": 0, "y1": breuken.MIN_HOOGTE - 1}
    groot = {"teken": "%", "x0": 0, "x1": 14, "y0": 0, "y1": breuken.MIN_HOOGTE + 5}
    assert pagina.mag_beoordelen(klein, herrenderbaar=False) is False
    assert pagina.mag_beoordelen(groot, herrenderbaar=False) is True
    # uit een pdf kunnen we het gebied scherper opvragen, dan mag elke hoogte
    assert pagina.mag_beoordelen(klein, herrenderbaar=True) is True


def test_paginavoet_in_de_marge_valt_af():
    """'84 RUND' staat links van de kolom; dat verraadt de paginavoet."""
    regels = [_regel(f"{n} iets", 117, 30 * i) for i, n in enumerate(range(1, 6))]
    regels.append(_regel("84 RUND", 91, 190))
    gehouden, weggelaten = pagina.zonder_paginavoet(regels, woordhoogte=16)
    assert [r["text"] for r in gehouden] == [r["text"] for r in regels[:-1]]
    assert weggelaten == ["84 RUND"]


def test_bolle_pagina_kost_geen_laatste_ingredient():
    """De linkermarge schuift geleidelijk op; dat is geen paginavoet."""
    regels = [_regel(f"{n} iets", x, 30 * i)
              for i, (n, x) in enumerate([(1, 124), (2, 121), (3, 118),
                                          (4, 115), (5, 112), (6, 110)])]
    gehouden, weggelaten = pagina.zonder_paginavoet(regels, woordhoogte=16)
    assert len(gehouden) == 6 and weggelaten == []
