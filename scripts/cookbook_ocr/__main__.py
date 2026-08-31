#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lees de ingrediëntenlijst van een gefotografeerde kookboekpagina.

    python3 scripts/cookbook_ocr <pdf-of-afbeelding> [--page N] [--json] [--debug]

Vereist tesseract met de nld-traineddata, en pypdfium2, Pillow, opencv en
pytesseract. Zie README.md in deze map.
"""

import argparse
import json
import os
import sys

# Tesseract verdeelt één pagina over vier OpenMP-threads en wordt daar op een
# drukke machine juist trager van: gemeten 56 s met één thread tegen minuten met
# vier. Wie het anders wil zet OMP_THREAD_LIMIT zelf.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pagina  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="cookbook_ocr", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bestand", help="pdf of afbeelding")
    p.add_argument("--page", type=int, default=0, help="paginanummer, 0-gebaseerd")
    p.add_argument("--scale", type=float, default=4.0,
                   help="renderschaal voor een pdf; lager dan 4 kost nauwkeurigheid")
    p.add_argument("--lang", default="nld", help="tesseract-taal")
    p.add_argument("--json", action="store_true", help="machineleesbare uitvoer")
    p.add_argument("--debug", action="store_true", help="diagnostiek op stderr")
    a = p.parse_args(argv)

    try:
        uit = pagina.lees_pagina(a.bestand, a.page, a.scale, a.lang)
    except FileNotFoundError:
        print(f"bestand niet gevonden: {a.bestand}", file=sys.stderr)
        return 2
    except ValueError as fout:
        print(fout, file=sys.stderr)
        return 2
    except Exception as fout:  # tesseract ontbreekt, taal onbekend, pdf stuk
        print(f"kon {a.bestand} niet lezen: {type(fout).__name__}: {fout}",
              file=sys.stderr)
        return 2

    if a.debug:
        for k in uit.get("kolommen", []):
            merk = "   <- gekozen" if k.get("gekozen") else ""
            print(f"[kolom] x {k['x0']}..{k['x1']}  {k['regels']:3d} regels  "
                  f"hoeveelheden {k['hoeveelheden']:.2f}{merk}", file=sys.stderr)
        for v in uit.get("breuken", []):
            herkomst = "scherp hergerenderd" if v["hergerenderd"] else "op renderschaal"
            print(f"[breuk] {v['gelezen']!r} ({v['hoogte']} px, {herkomst}) -> "
                  f"{v['teken']} — {v['uitleg']}", file=sys.stderr)
        for regel in uit.get("weggelaten", []):
            print(f"[weggelaten] {regel}", file=sys.stderr)

    if a.json:
        antwoord = {"blocks": uit["blocks"]}
        if uit.get("reden"):
            antwoord["reden"] = uit["reden"]
        if uit.get("weggelaten"):
            antwoord["weggelaten"] = uit["weggelaten"]
        print(json.dumps(antwoord, ensure_ascii=False, indent=2))
        return 0 if uit["blocks"] else 1
    if not uit["blocks"]:
        print(uit.get("reden", "niets gevonden"))
        return 1
    else:
        for blok in uit["blocks"]:
            if blok["header"]:
                print(f"\n{blok['header']}")
            for regel in blok["lines"]:
                print(f"  {regel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
