"""Wat een receptkaart per merk verraadt.

Alles wat merkspecifiek is aan de kaartmodus staat hier, in één lijst; de
rest (paren, tabelrijen uit geometrie, controle tegen de tabel, ankers over
twee pagina's) is merkloos. Een nieuw merk is een nieuw dict, geen nieuwe
code. Zonder treffer werken alle aanroepers gewoon door: geen bevestiging
van een voorkant, geen voorraadblok, geen bereidingstijd.
"""
import re

MERKEN = [
    {
        'naam': 'HelloFresh',
        # Het logo staat in kapitalen, en de OCR zet de titel er soms tussen:
        # 'HELLO Patatje oorlog met hamburger\nFRESH'. Bewust hoofdlettergevoelig.
        'voorkant': re.compile(r'\bHELLO[\s\S]{0,80}?FRESH\b'),
        'voorraadkop': re.compile(r'^\s*zelf toevoegen\s*$', re.IGNORECASE),
        'benodigdheden': re.compile(r'^\s*benodigdheden\s*$', re.IGNORECASE),
        # Drie kaartlay-outs voor dezelfde tijd: 'Bereidingstijd: N min.' (de
        # hoofdvorm, staat eerst zodat 'Oventijd' er nooit overheen wint),
        # 'Totale tijd: N min.' (ook als bereik 'N-M min.', dan de ondergrens)
        # en een kale 'N min.' achter een categorielabel zoals 'BALANS' of
        # '(totaal voor 2 personen)' zonder woord ervoor.
        'bereidingstijd': re.compile(r'bereidingstijd\s*:?\s*(\d+)\s*min', re.IGNORECASE),
        'bereidingstijd_alt': [
            re.compile(r'totale\s+tijd\s*:?\s*(\d+)(?:\s*-\s*\d+)?\s*min', re.IGNORECASE),
            re.compile(r'(\d+)\s*min\.?\s*\(totaal voor \d+ personen\)', re.IGNORECASE),
        ],
    },
]


def is_voorkant(tekst):
    """Bevat de paginatekst een merklogo dat alleen op de voorkant staat?"""
    return any(m['voorkant'].search(tekst or '') for m in MERKEN)


def is_voorraadkop(regel):
    return any(m['voorraadkop'].match(regel or '') for m in MERKEN)


def is_benodigdheden_kop(regel):
    return any(m['benodigdheden'].match(regel or '') for m in MERKEN)


def bereidingstijd(tekst):
    """Minuten uit 'Bereidingstijd: 40 min.', of None.

    'Bereidingstijd' gaat voor de kaartvarianten in 'bereidingstijd_alt'
    ('Totale tijd: N min.' en een kale 'N min. (totaal voor … personen)'),
    zodat 'Bereidingstijd: 40 min. Oventijd: 15 min.' bij 40 blijft.
    """
    for m in MERKEN:
        treffer = m['bereidingstijd'].search(tekst or '')
        if treffer:
            return int(treffer.group(1))
        for patroon in m.get('bereidingstijd_alt', []):
            treffer = patroon.search(tekst or '')
            if treffer:
                return int(treffer.group(1))
    return None
