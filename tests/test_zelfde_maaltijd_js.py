"""Het venster 'Is dit dezelfde maaltijd?' draait in node, niet in python.

Het gaat om de keuze die het venster teruggeeft: wegklikken is annuleren, en
een dubbelklik vlak na openen beantwoordt de vraag niet. De testcode staat in
tests/js/zelfde_maaltijd.test.js en heeft niets nodig behalve node zelf.
"""
import os
import shutil
import subprocess

import pytest

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(WORTEL, 'tests', 'js', 'zelfde_maaltijd.test.js')


@pytest.mark.skipif(shutil.which('node') is None, reason='node niet beschikbaar')
def test_het_venster_kiest_alleen_wat_je_echt_aanklikt():
    uit = subprocess.run(['node', SCRIPT], cwd=WORTEL,
                         capture_output=True, text=True, timeout=60)
    assert uit.returncode == 0, uit.stdout + uit.stderr
