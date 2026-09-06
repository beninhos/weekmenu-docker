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
        # De OCR zet het logo soms vóór de titel ('HELLO Kalkoenmedaillon-
        # stukjes ... FRESH') en het model neemt dat woord over. Alleen als
        # los woord (of twee) aan het begin; 'Hellofresh-bowl' blijft staan.
        'titelprefix': re.compile(r'^\s*hello(\s+fresh)?\s+(?=\S)', re.IGNORECASE),
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


def zonder_logo(titel, kaarttekst):
    """De titel zonder het merklogo dat de OCR ervoor plakte.

    Alleen voor een merk dat op de kaart zelf herkend is: 'Hello' aan het begin
    van een titel zonder HelloFresh-logo op de voorkant is gewoon de titel.
    """
    titel = titel or ''
    for m in MERKEN:
        patroon = m.get('titelprefix')
        if patroon and m['voorkant'].search(kaarttekst or ''):
            titel = patroon.sub('', titel, count=1)
    return titel.strip()


def is_voorraadkop(regel):
    return any(m['voorraadkop'].match(regel or '') for m in MERKEN)


def is_benodigdheden_kop(regel):
    return any(m['benodigdheden'].match(regel or '') for m in MERKEN)


def bereidingstijd(tekst):
    """Minuten uit 'Bereidingstijd: 40 min.', of None.

    Eerst het hoofdpatroon van élk merk, pas daarna de kaartvarianten in
    'bereidingstijd_alt' ('Totale tijd: N min.' en een kale 'N min. (totaal
    voor … personen)'). Zo blijft 'Bereidingstijd: 40 min. Oventijd: 15 min.'
    bij 40, en wint de losse terugvalvorm van het ene merk nooit van de exacte
    tijd van het andere — merkvolgorde in MERKEN mag de uitkomst niet bepalen.
    """
    tekst = tekst or ''
    for patronen in ([m['bereidingstijd'] for m in MERKEN],
                     [p for m in MERKEN for p in m.get('bereidingstijd_alt', [])]):
        for patroon in patronen:
            treffer = patroon.search(tekst)
            if treffer:
                return int(treffer.group(1))
    return None
