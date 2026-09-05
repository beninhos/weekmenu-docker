"""Receptkaart-modus: twee pagina's zijn één recept, en de tabel is leidend.

Merkloos: een achterkant is de pagina waarop een ingrediëntentabel wordt
gevonden (services/tabel.py), een voorkant is de andere. Een merklogo telt
alleen als bevestiging. Een paar dat niet klopt levert geen concept op maar
wél een melding met paginanummers: een half recept is erger dan geen.
"""
import re

from weekmenu.services.kaartsignaturen import (bereidingstijd, is_benodigdheden_kop,
                                               is_voorkant)
from weekmenu.services.tabel import tabelrijen
from weekmenu.services.units import _norm_unit, _parse_amount

_REDEN = {
    'meerdere kolommen': 'de tabel heeft meerdere hoeveelheidkolommen, dat kan de app nog niet',
}
_PERSONEN = re.compile(r'voor (\d+) personen')


def _personen(*teksten):
    """Aantal personen uit de eerste tekst die 'voor N personen' bevat, of None.

    Kaarten voor 1–6 personen hebben meerdere hoeveelheidkolommen; zonder dit
    getal weigert tabelrijen zo'n tabel (reden 'meerdere kolommen').
    """
    for tekst in teksten:
        treffer = _PERSONEN.search(tekst or '')
        if treffer:
            return int(treffer.group(1))
    return None


def paren(texts, annotaties):
    """Pagina's op volgorde tot paren (voor, achter); geeft (paren, meldingen)."""
    uit, meldingen = [], []
    for i in range(0, len(texts) - 1, 2):
        a, b = i + 1, i + 2
        personen = _personen(texts[a - 1], texts[b - 1])
        tabellen = {n: tabelrijen(annotaties[n - 1] or {}, personen=personen) for n in (a, b)}
        met_tabel = [n for n in (a, b) if tabellen[n][0] is not None]
        if len(met_tabel) == 1:
            achter = met_tabel[0]
            uit.append({'voor': a if achter == b else b, 'achter': achter,
                        'rijen': tabellen[achter][0]})
            continue
        if len(met_tabel) == 2:
            waarom = 'op beide staat een ingrediëntentabel'
        else:
            kandidaten = [(n, tabellen[n][1]) for n in (a, b)
                          if tabellen[n][1] not in ('geen tabel', None)]
            gemapt = [reden for _, reden in kandidaten if reden in _REDEN]
            if gemapt:
                waarom = _REDEN[gemapt[0]]
            elif kandidaten:
                n, reden = kandidaten[0]
                waarom = f'de tabel op pagina {n} is niet te lezen ({reden})'
            else:
                waarom = 'op geen van beide staat een ingrediëntentabel'
        meldingen.append(f"Pagina's {a} en {b} zijn niet als één kaart te lezen: {waarom}.")
    if len(texts) % 2:
        meldingen.append(f'Pagina {len(texts)} heeft geen tegenhanger en is overgeslagen.')
    return uit, meldingen


def zonder_tabelregels(achtertekst, rijen):
    """Achterkant zonder de cellen van de tabel, zodat een anker er nooit op valt."""
    cellen = {c.strip().lower() for r in rijen for c in (r['naam'], r['hoeveelheid']) if c}
    return '\n'.join(regel for regel in achtertekst.split('\n')
                     if re.sub(r'\s+', ' ', regel).strip().lower() not in cellen)


def kaart_invoer(voortekst, achtertekst, rijen, voor, achter):
    """De tekst die het model krijgt: voorkant, schone tabelrijen, achterkant."""
    tabel = '\n'.join(f"{r['naam']} | {r['hoeveelheid']}" for r in rijen)
    return (f'--- Voorkant (pagina {voor}) ---\n{voortekst.strip()}\n\n'
            f'--- Ingrediënten (tabel) ---\n{tabel}\n\n'
            f'--- Achterkant (pagina {achter}) ---\n{zonder_tabelregels(achtertekst, rijen).strip()}')


def benodigdheden(tekst):
    """De regels onder de kop 'Benodigdheden', letterlijk, tot een regel die
    niet op een komma eindigt (hooguit vier regels). None zonder kop."""
    regels = (tekst or '').split('\n')
    for i, regel in enumerate(regels):
        if is_benodigdheden_kop(regel):
            uit = []
            for volgende in regels[i + 1:i + 5]:
                volgende = volgende.strip()
                if not volgende:
                    break
                uit.append(volgende)
                if not volgende.endswith(','):
                    break
            return ' '.join(uit) or None
    return None
