"""Een telbare receptmaat tegenover een verpakking die weegt.

"10 stuks kerstomaatjes" en "een pak van 380 g" hebben geen eenheid gemeen,
dus viel de berekening terug op "rond het aantal maar af": tien pakken, bijna
vier kilo tomaat. De brug tussen die twee is één getal — wat één stuk is —
en dat getal weet alleen een mens.

Dit bestand doet drie dingen: het stelt die vraag in de richting waarin je hem
zou beantwoorden (een ui weegt 150 gram, niet: een gram is 0,0067 ui), het doet
een voorstel met de bron erbij, en het wijst de gevallen aan waar het nu
misgaat. Opslaan gebeurt in het bestaande formaat van `ah_conv_factor` /
`ah_conv_unit` — hoeveel recepteenheden er in één verpakkingseenheid gaan —
zodat `_calc_ah_qty` ongewijzigd blijft.

Niets gebeurt vanzelf: een voorstel wordt pas een conversie als je erop klikt.
"""
import math
import re

from weekmenu.constants import _KEUKENMATEN, _MEETEENHEDEN, _UNIT_CONVERSIONS
from weekmenu.extensions import db
from weekmenu.models import Ingredient, MaatOverslaan, Recipe, RecipeIngredient
from weekmenu.services.units import (
    _calc_ah_qty, _norm_unit, _normalize_ingredient, format_amount, verpakkingsroute,
)

# Waarin je het antwoord opschrijft als de verpakking in kilo's of liters staat:
# een ui weeg je in grammen, ook al ligt hij in een zak van 1 kg.
_ANTWOORDEENHEID = {'kg': 'g', 'l': 'ml', 'cl': 'ml', 'dl': 'ml'}

_AANTAL_IN_NAAM = re.compile(r'(?<![\d,.+])(\d{1,2})\s*(?:stuks|stuk|-?pack)\b')


# ── de richting van de vraag ─────────────────────────────────────────────

def vraagrichting(pkg_eenheid):
    """'per_stuk' bij een verpakking die weegt, anders 'per_verpakking'.

    Bij 380 g tomaten is de vraag "wat weegt één tomaat"; bij een netje van
    2 bollen knoflook is de vraag "hoeveel tenen zitten er in één bol". Allebei
    zeg je zo hardop; het omgekeerde niet.
    """
    return 'per_stuk' if _norm_unit(pkg_eenheid) in _MEETEENHEDEN else 'per_verpakking'


def antwoordeenheid(pkg_eenheid):
    """De eenheid waarin het antwoord op de per-stuk-vraag wordt opgeschreven."""
    norm = _norm_unit(pkg_eenheid)
    return _ANTWOORDEENHEID.get(norm, norm)


def _getal(waarde):
    """Tekst of getal naar float, of None als het niets bruikbaars is.

    'NaN' en 'inf' komen door float() heen maar overleven daarna elke
    vergelijking ('nan <= 0' is False, 'not nan' ook), waardoor ze ongemerkt
    tot in de database rollen en de maat stil wissen. Alleen een echt eindig
    getal telt.
    """
    try:
        uit = float(str(waarde).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return uit if math.isfinite(uit) else None


def _reken_om(waarde, van, naar):
    """Zelfde soort eenheid omrekenen (g→kg, ml→l). None als er geen brug is."""
    van, naar = _norm_unit(van), _norm_unit(naar)
    if not van or not naar or van == naar:
        return waarde
    factor = _UNIT_CONVERSIONS.get((van, naar))
    return waarde * factor if factor else None


def _afronden(waarde):
    """Een voorstel afronden op wat je in een keuken zou opschrijven."""
    if waarde is None:
        return None
    rond = round(waarde, 2) if waarde >= 1 else round(waarde, 4)
    return int(rond) if rond == int(rond) else rond


def conversie_uit_antwoord(richting, waarde, antwoord_eenheid=None, pkg_eenheid=None):
    """Het antwoord op de gestelde vraag → `ah_conv_factor`.

    `ah_conv_factor` is en blijft "hoeveel recepteenheden gaan er in één
    verpakkingseenheid". Bij 'per_verpakking' is het antwoord dat getal al;
    bij 'per_stuk' is het antwoord de omgekeerde breuk, en staat het bovendien
    in grammen terwijl de verpakking in kilo's telt. Beide bochten zitten hier,
    zodat het formulier alleen hoeft door te geven wat de gebruiker intikte.
    """
    getal = _getal(waarde)
    if getal is None or getal <= 0:
        return None
    if richting == 'per_verpakking':
        return getal
    in_pkg = _reken_om(getal, antwoord_eenheid or pkg_eenheid, pkg_eenheid)
    if not in_pkg or in_pkg <= 0:
        return None
    return 1.0 / in_pkg


def antwoord_uit_conversie(richting, factor, antwoord_eenheid=None, pkg_eenheid=None):
    """De weg terug, zodat het formulier laat zien wat er is ingevuld."""
    getal = _getal(factor)
    if getal is None or getal <= 0:
        return None
    if richting == 'per_verpakking':
        return _afronden(getal)
    return _afronden(_reken_om(1.0 / getal, pkg_eenheid, antwoord_eenheid or pkg_eenheid))


# ── het voorstel ─────────────────────────────────────────────────────────

def _past_op_naam(trefwoord, naam):
    """Zoals de categoriegokker: korte trefwoorden alleen als heel woord."""
    tekst = _normalize_ingredient(naam or '')
    tref = _normalize_ingredient(trefwoord)
    if len(tref) <= 3:
        return re.search(r'(^|[^a-z])' + re.escape(tref) + r'([^a-z]|$)', tekst) is not None
    return tref in tekst


def _uit_productnaam(ing, recept_eenheid, pkg_eenheid):
    """"AH Scharrel kipfilet 3 stuks" van 600 g zegt: 200 g per filet.

    De sterkste bron die er is, want jij hebt dat product zelf gekozen en het
    aantal staat er letterlijk bij. Alleen bruikbaar als het recept in stuks
    telt — bij plakken of tenen zegt "3 stuks" niets over één plak.
    """
    if recept_eenheid != 'stuks' or pkg_eenheid not in _MEETEENHEDEN:
        return None
    m = _AANTAL_IN_NAAM.search((ing.ah_product_name or '').lower())
    if not m:
        return None
    aantal = int(m.group(1))
    if not 2 <= aantal <= 24:
        return None
    maat = f'{format_amount(ing.ah_pkg_qty)} {ing.ah_pkg_unit}'
    return (ing.ah_pkg_qty / aantal,
            f'de productnaam noemt {aantal} stuks bij {maat}')


def _uit_keukenmaten(ing, recept_eenheid, pkg_eenheid):
    """Hoeveel verpakkingseenheid er in één recepteenheid gaat, uit de tabel."""
    for trefwoord, van, waarde, naar in _KEUKENMATEN:
        if not _past_op_naam(trefwoord, ing.name):
            continue
        van_n, naar_n = _norm_unit(van), _norm_unit(naar)
        if van_n == recept_eenheid:
            per_recept = _reken_om(waarde, naar_n, pkg_eenheid)
        elif naar_n == recept_eenheid:
            # De rij staat andersom opgeschreven: 1 bol = 10 tenen.
            per_recept = _reken_om(1.0 / waarde, van_n, pkg_eenheid)
        else:
            continue
        if per_recept and per_recept > 0:
            return (per_recept,
                    f'keukenmaat: 1 {van} {trefwoord} ≈ {format_amount(waarde)} {naar}')
    return None


def schat_maat(ing, recept_eenheid):
    """Voorstel voor 'wat is één stuk', met de bron erbij — of None.

    Geen voorstel is een geldige uitkomst: liever niets dan een verzonnen
    getal waar je niet aan kunt zien waar het vandaan komt.
    """
    if not ing or not ing.ah_pkg_qty or not ing.ah_pkg_unit:
        return None
    recept = _norm_unit(recept_eenheid)
    pkg = _norm_unit(ing.ah_pkg_unit)
    if not recept or recept == pkg:
        return None

    # Van betrouwbaar naar minder betrouwbaar: eerst wat het product zelf zegt,
    # dan de keukenmaten, en anders niets.
    gevonden = (_uit_productnaam(ing, recept, pkg)
                or _uit_keukenmaten(ing, recept, pkg))
    if gevonden is None:
        return None

    per_recept, bron = gevonden          # 1 recepteenheid = per_recept × pkg
    richting = vraagrichting(pkg)
    toon = antwoordeenheid(pkg) if richting == 'per_stuk' else recept
    if richting == 'per_stuk':
        waarde = _afronden(_reken_om(per_recept, pkg, toon))
    else:
        waarde = _afronden(1.0 / per_recept)
    if not waarde or waarde <= 0:
        return None
    return {'waarde': waarde, 'richting': richting, 'eenheid': pkg,
            'toon_eenheid': toon, 'bron': bron}


# ── de gevallen waar het nu misgaat ──────────────────────────────────────

def _qty_met_conversie(ing, amount, factor):
    """Wat de lijst zou bestellen met deze conversie, zonder hem op te slaan."""
    if not factor or factor <= 0 or not ing.ah_pkg_qty:
        return None
    return max(1, math.ceil(amount / factor / ing.ah_pkg_qty))


def _zwaarste_regels():
    """Per (ingredient, recepteenheid) de regel die de meeste verpakkingen kost.

    Op het aantal verpakkingen en niet op de hoeveelheid, want die twee lopen
    niet gelijk: 24 tenen knoflook bestelt één zakje (boven de twintig geeft
    `_calc_default_qty` het op) en 5 tenen bestelt er vijf. Op hoeveelheid
    sorteren zou juist die 24 als koploper kiezen en het geval daarmee
    onzichtbaar maken.

    Eén query voor alle receptregels: dit draait bij het openen van
    /ah-producten, naast 400 ingredientkaarten.
    """
    zwaarste = {}
    rijen = (db.session.query(RecipeIngredient, Ingredient, Recipe.name)
             .join(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
             .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
             .all())
    for ri, ing, receptnaam in rijen:
        eenheid = _norm_unit(ri.unit)
        qty = _calc_ah_qty(ing, ri.amount, eenheid)
        vorig = zwaarste.get((ing.id, eenheid))
        if vorig is None:
            zwaarste[(ing.id, eenheid)] = {'ingredient': ing, 'amount': ri.amount,
                                           'recept': receptnaam, 'regels': 1, 'qty': qty}
        else:
            vorig['regels'] += 1
            if (qty, ri.amount) > (vorig['qty'], vorig['amount']):
                vorig.update(amount=ri.amount, recept=receptnaam, qty=qty)
    return zwaarste


def _per_verpakking_totaal(waarde, pkg_qty, eenheid):
    """"20 teen", het doorgerekende totaal van een verpakking — of None.

    De opgeslagen factor gaat per verpakkingsEENHEID, want `_calc_ah_qty`
    deelt daarna nóg eens door `ah_pkg_qty`. Bij een netje van twee bollen
    staat er dus 10 teen in het veld terwijl er twintig in het netje zitten.
    Wie die 10 als 'het hele netje' leest vult 20 in en bestelt de helft te
    weinig, zonder dat iets dat tegenspreekt. Daarom rekent het scherm het
    voor. Bij een verpakking van één valt het samen en zwijgt hij.
    """
    if not waarde or not pkg_qty or pkg_qty <= 1:
        return None
    return f'{format_amount(waarde * pkg_qty)} {eenheid}'


def _kandidaat(ing, eenheid, regel):
    """Eén geval zoals het scherm het toont: wat er nu gebeurt en wat het scheelt."""
    voorstel = schat_maat(ing, eenheid)
    straks = None
    if voorstel:
        factor = conversie_uit_antwoord(voorstel['richting'], voorstel['waarde'],
                                        voorstel['toon_eenheid'], ing.ah_pkg_unit)
        straks = _qty_met_conversie(ing, regel['amount'], factor)

    nu = regel['qty']
    richting = vraagrichting(ing.ah_pkg_unit)
    return {
        'ingredient_id': ing.id,
        'naam': ing.display,
        'eenheid': eenheid,
        'vraagt': f'{format_amount(regel["amount"])} {eenheid}',
        'recept': regel['recept'],
        'regels': regel['regels'],
        'product': ing.ah_product_name or '',
        'verpakking': f'{format_amount(ing.ah_pkg_qty)} {ing.ah_pkg_unit}',
        'pkg_eenheid': _norm_unit(ing.ah_pkg_unit),
        'pkg_aantal': ing.ah_pkg_qty,
        'richting': richting,
        'toon_eenheid': (antwoordeenheid(ing.ah_pkg_unit)
                         if richting == 'per_stuk' else eenheid),
        'totaal': (_per_verpakking_totaal(voorstel['waarde'], ing.ah_pkg_qty, eenheid)
                   if voorstel and richting == 'per_verpakking' else None),
        'nu': nu,
        'straks': straks,
        'te_veel': nu - (straks or 1),
        # Een ingredient houdt één maat vast. Staat er al een voor een andere
        # eenheid, dan overschrijf je die — dat hoort op het scherm te staan
        # en niet stil te gebeuren.
        'vervangt': (_norm_unit(ing.ah_conv_unit)
                     if ing.ah_conv_factor and _norm_unit(ing.ah_conv_unit) != eenheid
                     else None),
        'voorstel': ({'waarde': voorstel['waarde'], 'bron': voorstel['bron']}
                     if voorstel else None),
    }


def alle_verpakkingsgevallen():
    """De open gevallen én de weggeklikte, uit één ronde over de receptregels.

    Alleen de route 'gokken' telt mee: dáár heeft de berekening geen brug
    tussen de recepteenheid en de verpakking. Twee blikken bonen voor 800 g en
    twee netjes voor vier uien rekenen wél door en blijven dus buiten dit
    scherm — die kloppen.

    De weggeklikte gevallen staan er apart bij, want 'Niet vragen' mag geen
    eenrichtingsdeur zijn: één misklik en het geval was alleen nog terug te
    halen door zelf een getal in te typen. Ze worden op dezelfde manier
    opgebouwd als de open gevallen en niet uit de overslaan-tabel gelezen, dus
    een geval dat inmiddels langs een andere weg is opgelost verdwijnt ook
    hier — de rij blijft dan als een stille aantekening staan.

    Zwaarste eerst: hoeveel verpakkingen er overbodig zijn.
    """
    overgeslagen = {(m.ingredient_id, m.eenheid) for m in MaatOverslaan.query.all()}
    gevallen = {'open': [], 'overgeslagen': []}

    for (ing_id, eenheid), regel in _zwaarste_regels().items():
        ing = regel['ingredient']
        if verpakkingsroute(ing, eenheid) != 'gokken':
            continue
        if regel['qty'] <= 1:
            continue
        vak = 'overgeslagen' if (ing_id, eenheid) in overgeslagen else 'open'
        gevallen[vak].append(_kandidaat(ing, eenheid, regel))

    for lijst in gevallen.values():
        lijst.sort(key=lambda k: (-k['te_veel'], -k['nu'], k['naam'].lower()))
    return gevallen


def verpakkingskandidaten():
    """Waar de boodschappenlijst nu meer verpakkingen bestelt dan nodig."""
    return alle_verpakkingsgevallen()['open']


def maatvraag(ing):
    """Hoe het formulier op /ah-producten de maatvraag stelt voor dit product.

    Ook de weg terug: wat er is opgeslagen, teruggerekend naar het antwoord
    op de vraag zoals hij gesteld werd, zodat je in het veld terugziet wat je
    hebt ingevuld en niet de omgekeerde breuk.
    """
    if not ing or not ing.ah_pkg_qty or not ing.ah_pkg_unit:
        return None
    richting = vraagrichting(ing.ah_pkg_unit)
    toon = antwoordeenheid(ing.ah_pkg_unit)
    waarde = (antwoord_uit_conversie(richting, ing.ah_conv_factor, toon, ing.ah_pkg_unit)
              if ing.ah_conv_factor else None)
    return {'richting': richting, 'toon_eenheid': toon,
            'pkg_eenheid': _norm_unit(ing.ah_pkg_unit),
            'pkg_aantal': ing.ah_pkg_qty,
            'verpakking': f'{format_amount(ing.ah_pkg_qty)} {_norm_unit(ing.ah_pkg_unit)}',
            'totaal': (_per_verpakking_totaal(waarde, ing.ah_pkg_qty, ing.ah_conv_unit)
                       if richting == 'per_verpakking' else None),
            'eenheid': ing.ah_conv_unit or '', 'waarde': waarde}


# ── vastleggen, altijd op een klik ───────────────────────────────────────

def bevestig_maat(ingredient_id, eenheid, waarde, richting, antwoord_eenheid=None):
    """Sla vast wat één stuk is, in het bestaande conversieformaat."""
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    if not ing:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404
    if not ing.ah_pkg_qty or not ing.ah_pkg_unit:
        return {'status': 'error', 'message': 'verpakking onbekend'}, 400

    norm = _norm_unit(eenheid)
    if not norm:
        return {'status': 'error', 'message': 'geen recepteenheid opgegeven'}, 400

    richting = richting or vraagrichting(ing.ah_pkg_unit)
    factor = conversie_uit_antwoord(
        richting, waarde,
        antwoord_eenheid or antwoordeenheid(ing.ah_pkg_unit), ing.ah_pkg_unit)
    if not factor:
        return {'status': 'error', 'message': 'geen bruikbaar getal'}, 400

    ing.ah_conv_factor, ing.ah_conv_unit = factor, norm
    for rij in MaatOverslaan.query.filter_by(ingredient_id=ing.id, eenheid=norm).all():
        db.session.delete(rij)
    db.session.commit()

    regel = _zwaarste_regels().get((ing.id, norm))
    qty = _calc_ah_qty(ing, regel['amount'], norm) if regel else None
    return {'status': 'ok', 'factor': factor, 'qty': qty}, 200


def sla_maat_over(ingredient_id, eenheid):
    """'Niet vragen': de berekening blijft staan, het scherm loopt leeg."""
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    if not ing:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404
    norm = _norm_unit(eenheid)
    if not norm:
        return {'status': 'error', 'message': 'geen recepteenheid opgegeven'}, 400
    if not MaatOverslaan.query.filter_by(ingredient_id=ing.id, eenheid=norm).first():
        db.session.add(MaatOverslaan(ingredient_id=ing.id, eenheid=norm))
        db.session.commit()
    return {'status': 'ok'}, 200


def vraag_maat_toch(ingredient_id, eenheid):
    """De weg terug uit 'Niet vragen'.

    Eén misklik naast Bevestig haalde de kaart weg langs het enige pad dat
    hem ook weer weghaalt; wat overbleef was zelf een getal verzinnen in
    'Verpakking instellen'. Dit zet het geval gewoon terug tussen de open
    vragen.
    """
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    if not ing:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404
    norm = _norm_unit(eenheid)
    if not norm:
        return {'status': 'error', 'message': 'geen recepteenheid opgegeven'}, 400
    for rij in MaatOverslaan.query.filter_by(ingredient_id=ing.id, eenheid=norm).all():
        db.session.delete(rij)
    db.session.commit()
    return {'status': 'ok'}, 200
