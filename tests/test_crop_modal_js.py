"""De rekenkant van de bijsnijdmodal draait in node, niet in python.

Het gaat om wat de browser naar /recipe/<id>/crop stuurt: welke fracties er in
de body staan na openen, na een draai, en na een eigen selectie. Dat is de enige
plek waar 'alleen rechtzetten' stiekem een uitsnede kon worden. De testcode
staat in tests/js/crop_modal.test.js en heeft niets nodig behalve node zelf.
"""
import os
import shutil
import subprocess

import pytest

WORTEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(WORTEL, 'tests', 'js', 'crop_modal.test.js')


@pytest.mark.skipif(shutil.which('node') is None, reason='node niet beschikbaar')
def test_de_bijsnijdmodal_stuurt_de_juiste_fracties():
    uit = subprocess.run(['node', SCRIPT], cwd=WORTEL,
                         capture_output=True, text=True, timeout=60)
    assert uit.returncode == 0, uit.stdout + uit.stderr
