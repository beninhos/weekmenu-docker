"""Varianten van hetzelfde product samenvoegen tot één ingredient.

Elke schrijfwijze werd tot nu toe een eigen ingredientrij: 'knoflook' naast
'knoflookteen', 'bosui' naast 'lente-ui' naast 'lente-uitjes'. Op de
boodschappenlijst betekent dat twee regels met elk een eigen
verpakkingsberekening — twee bolletjes knoflook voor vier tenen, terwijl één
bolletje twaalf tenen heeft.

Deze module lost dat op zoals de rest van de app zulke dingen doet: hij stelt
voor en legt het bewijs op tafel, maar verandert niets uit zichzelf. Elke
samenvoeging komt van een klik op /twijfelgevallen.

De verliezer verdwijnt niet spoorloos: zijn naam blijft achter als
IngredientAlias op de winnaar, zodat een volgende import diezelfde spelling
meteen bij het goede ingredient uitkomt en het probleem niet terugkomt.
"""
import re
from collections import defaultdict

from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, IngredientAlias,
    IngredientUnitConversion, PantryIngredient, RecipeIngredient,
    ShoppingCheck, ShoppingListExclusion, ShoppingListOverride, VariantApart,
)
from weekmenu.services.units import _norm_unit, _normalize_ingredient


# AH-velden verhuizen als blok: een halve koppeling (id zonder verpakking) is
# erger dan geen koppeling, want dan rekent de lijst met lucht.
_AH_VELDEN = (
    'ah_product_id', 'ah_product_name', 'ah_product_size', 'ah_product_price',
    'ah_product_image', 'ah_product_bonus', 'ah_product_updated', 'ah_product_color',
    'ah_product_was_price', 'ah_product_bonus_mechanism', 'ah_product_brand',
    'ah_product_category', 'ah_pkg_qty', 'ah_pkg_unit', 'ah_conv_factor', 'ah_conv_unit',
)

# Tabellen waarin een ingredient hoogstens één rij per sleutel mag hebben —
# hetzelfde lijstje als in migratie v14, met erbij op welke velden die
# uniciteit geldt. v14 gooide de rij van de verliezer altijd weg; hier
# verhuist hij als de winnaar op die sleutel nog niets heeft staan.
#
# ingredient_unit_conversion heeft in de database UNIQUE(ingredient_id,
# from_unit) staan, en _convert_unit_for_agg zoekt ook alleen op from_unit.
# Daarom is from_unit de sleutel en niet (from_unit, to_unit).
_UNIEKE_TABELLEN = (
    (PantryIngredient, ()),
    (IngredientUnitConversion, ('from_unit',)),
    (ShoppingListExclusion, ('year', 'week_number')),
    (ShoppingListOverride, ('year', 'week_number')),
    (ShoppingCheck, ('year', 'week_number')),
    (VariantApart, ('sleutel',)),
)

# Meervoudsuitgangen die in het Nederlands niets aan het product veranderen.
# Bewust géén bijvoeglijke naamwoorden: 'witte bonen' en 'zwarte bonen' zijn
# echt verschillende producten en mogen nooit als kandidaat opduiken.
_MEERVOUD = ('tjes', 'jes', 'en', 's', 'je')


def variantsleutel(naam):
    """Naam zonder spaties en leestekens: 'rode wijnazijn' == 'rodewijnazijn'."""
    return re.sub(r'[^a-z0-9]', '', _normalize_ingredient((naam or '').lower()))


# ── samenvoegen ──────────────────────────────────────────────────────────

def voeg_samen(verliezer_id, winnaar_id):
    """Voeg de verliezer op in de winnaar. Geeft (payload, statuscode).

    Alles gebeurt in één transactie: gaat er onderweg iets mis, dan staat de
    database er precies zo bij als ervoor. Een half samengevoegd ingredient —
    receptregels verhuisd maar de rij nog aanwezig — zou de boodschappenlijst
    stiller kapotmaken dan het probleem dat we oplossen.
    """
    try:
        verliezer_id, winnaar_id = int(verliezer_id or 0), int(winnaar_id or 0)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'ongeldige ingredient-id'}, 400

    if verliezer_id == winnaar_id:
        return {'status': 'error', 'message': 'een ingredient kan niet in zichzelf op'}, 400

    verliezer = Ingredient.query.get(verliezer_id)
    winnaar = Ingredient.query.get(winnaar_id)
    if not verliezer or not winnaar:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404

    verliezer_naam = verliezer.display
    verliezer_canoniek = verliezer.name

    try:
        verplaatst = _verhuis_receptregels(verliezer_id, winnaar_id)

        # Aliassen kunnen niet botsen: alias is over de hele tabel uniek, dus
        # een verhuizing naar de winnaar houdt hem geldig.
        for alias in IngredientAlias.query.filter_by(ingredient_id=verliezer_id).all():
            alias.ingredient_id = winnaar_id

        for model, sleutelvelden in _UNIEKE_TABELLEN:
            _verhuis_unieke_rijen(model, sleutelvelden, verliezer_id, winnaar_id)

        # Handmatige boodschappen hebben geen UNIQUE: twee rijen voor dezelfde
        # week zouden blijven staan en dubbel meetellen. Optellen dus.
        _verhuis_unieke_rijen(
            CustomShoppingIngredient, ('year', 'week_number', 'unit'),
            verliezer_id, winnaar_id,
            samenvoegen=lambda blijft, gaat: setattr(
                blijft, 'amount', (blijft.amount or 0) + (gaat.amount or 0)))

        _erf_velden(verliezer, winnaar)

        # Het besluit 'deze twee zijn apart' is met deze klik achterhaald.
        _wis_apart_tussen(verliezer, winnaar)

        db.session.flush()
        _leg_alias_vast(verliezer_canoniek, winnaar_id)
        _leg_alias_vast(verliezer_naam, winnaar_id)

        db.session.delete(verliezer)
        db.session.commit()
    except Exception as fout:                       # noqa: BLE001 — alles terugdraaien
        db.session.rollback()
        return {'status': 'error', 'message': f'samenvoegen mislukt: {fout}'}, 500

    return {
        'status': 'ok',
        'winnaar_id': winnaar.id,
        'winnaar': winnaar.display,
        'verliezer': verliezer_naam,
        'recepten_verplaatst': verplaatst,
    }, 200


def _verhuis_receptregels(verliezer_id, winnaar_id):
    """Receptregels naar de winnaar; binnen één recept smelten gelijke regels samen.

    'knoflook 2 teen' en 'knoflookteen 1 teen' in hetzelfde recept horen na de
    samenvoeging één regel van 3 tenen te zijn. Verschilt de bereiding, dan
    blijven het twee regels: 'geperst' en 'fijngesneden' optellen tot
    'geperst' zou informatie weggooien die de kok nodig heeft.
    """
    def sleutel(ri):
        return (ri.recipe_id, _norm_unit(ri.unit), (ri.preparation or '').strip().lower())

    bezet = {}
    for ri in RecipeIngredient.query.filter_by(ingredient_id=winnaar_id).all():
        bezet.setdefault(sleutel(ri), ri)

    verplaatst = 0
    for ri in RecipeIngredient.query.filter_by(ingredient_id=verliezer_id).all():
        tweeling = bezet.get(sleutel(ri))
        if tweeling is not None:
            tweeling.amount = (tweeling.amount or 0) + (ri.amount or 0)
            db.session.delete(ri)
        else:
            ri.ingredient_id = winnaar_id
            bezet[sleutel(ri)] = ri
        verplaatst += 1
    return verplaatst


def _verhuis_unieke_rijen(model, sleutelvelden, verliezer_id, winnaar_id, samenvoegen=None):
    """Rijen van de verliezer overzetten, botsingen in het voordeel van de winnaar."""
    bezet = {}
    for rij in model.query.filter_by(ingredient_id=winnaar_id).all():
        bezet.setdefault(tuple(getattr(rij, veld) for veld in sleutelvelden), rij)

    for rij in model.query.filter_by(ingredient_id=verliezer_id).all():
        sleutel = tuple(getattr(rij, veld) for veld in sleutelvelden)
        botsing = bezet.get(sleutel)
        if botsing is None:
            rij.ingredient_id = winnaar_id
            bezet[sleutel] = rij
        else:
            if samenvoegen:
                samenvoegen(botsing, rij)
            db.session.delete(rij)


def _erf_velden(verliezer, winnaar):
    """Wat de winnaar mist en de verliezer wel heeft, gaat mee."""
    if not winnaar.ah_product_id and verliezer.ah_product_id:
        for veld in _AH_VELDEN:
            setattr(winnaar, veld, getattr(verliezer, veld))

    for veld in ('preferred_unit', 'bron'):
        if not getattr(winnaar, veld) and getattr(verliezer, veld):
            setattr(winnaar, veld, getattr(verliezer, veld))


def _wis_apart_tussen(verliezer, winnaar):
    """Een eerder 'toch apart' tussen deze twee vervalt met de samenvoeging."""
    sleutels = {variantsleutel(verliezer.name), variantsleutel(verliezer.display),
                variantsleutel(winnaar.name), variantsleutel(winnaar.display)}
    for rij in VariantApart.query.filter(
            VariantApart.ingredient_id.in_([verliezer.id, winnaar.id])).all():
        if rij.sleutel in sleutels:
            db.session.delete(rij)


def _leg_alias_vast(tekst, ingredient_id):
    """Zorg dat deze spelling voortaan bij dit ingredient uitkomt."""
    sleutel = _normalize_ingredient((tekst or '').lower().strip())
    if not sleutel:
        return
    bestaand = IngredientAlias.query.filter_by(alias=sleutel).first()
    if bestaand:
        bestaand.ingredient_id = ingredient_id
    else:
        db.session.add(IngredientAlias(alias=sleutel, ingredient_id=ingredient_id))


# ── 'zelfde product' en 'toch apart' ─────────────────────────────────────

def koppel_alias(naam, ingredient_id):
    """'Zelfde product': deze spelling hoort bij dat bestaande ingredient.

    Bestaat de spelling al als eigen ingredientrij, dan is een alias niet
    genoeg — die rij zou blijven staan en op de lijst blijven verschijnen.
    Dan is dit een volwaardige samenvoeging, en de klik is de bevestiging.
    """
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    if not ing:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404

    canoniek = _normalize_ingredient((naam or '').lower().strip())
    if not canoniek:
        return {'status': 'error', 'message': 'naam verplicht'}, 400

    dubbel = Ingredient.query.filter_by(name=canoniek).first()
    if dubbel and dubbel.id != ing.id:
        payload, code = voeg_samen(dubbel.id, ing.id)
        if code == 200:
            payload['samengevoegd'] = True
        return payload, code

    try:
        _leg_alias_vast(canoniek, ing.id)
        db.session.commit()
    except Exception as fout:                       # noqa: BLE001
        db.session.rollback()
        return {'status': 'error', 'message': f'vastleggen mislukt: {fout}'}, 500

    return {'status': 'ok', 'samengevoegd': False,
            'ingredient_id': ing.id, 'naam': ing.display}, 200


def markeer_apart(naam, ingredient_id):
    """'Toch apart': vraag deze spelling nooit meer bij dit ingredient na."""
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    if not ing:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404

    sleutel = variantsleutel(naam)
    if not sleutel:
        return {'status': 'error', 'message': 'naam verplicht'}, 400

    bestaand = VariantApart.query.filter_by(sleutel=sleutel, ingredient_id=ing.id).first()
    if not bestaand:
        db.session.add(VariantApart(sleutel=sleutel, ingredient_id=ing.id))
        db.session.commit()
    return {'status': 'ok'}, 200


def markeer_paar_apart(a_id, b_id):
    """Twee bestaande ingredienten uit elkaar houden — beide kanten op.

    Beide richtingen, want de kandidatenlijst kan het paar de volgende keer
    andersom voorstellen (de winnaar hangt af van wie de meeste recepten heeft).
    """
    a = Ingredient.query.get(a_id) if a_id else None
    b = Ingredient.query.get(b_id) if b_id else None
    if not a or not b:
        return {'status': 'error', 'message': 'ingredient bestaat niet'}, 404
    if a.id == b.id:
        return {'status': 'error', 'message': 'twee verschillende ingredienten nodig'}, 400

    for bron, doel in ((a, b), (b, a)):
        sleutel = variantsleutel(bron.name)
        if not sleutel:
            continue
        if not VariantApart.query.filter_by(sleutel=sleutel, ingredient_id=doel.id).first():
            db.session.add(VariantApart(sleutel=sleutel, ingredient_id=doel.id))
    db.session.commit()
    return {'status': 'ok'}, 200


def apart_paren():
    """Alle vastgelegde 'nee'-besluiten als set van (sleutel, ingredient_id)."""
    return {(v.sleutel, v.ingredient_id) for v in VariantApart.query.all()}


# ── kandidatenlijst ──────────────────────────────────────────────────────

def samenvoeg_kandidaten():
    """Paren die waarschijnlijk hetzelfde product zijn, met het bewijs erbij.

    Drie signalen, van sterk naar zwak:
      ah           allebei aan hetzelfde AH-product gekoppeld — dat heb jij
                   zelf gekozen, dus dit is het sterkste signaal dat er is
      schrijfwijze dezelfde naam op spaties en streepjes na
      meervoud     de een is het meervoud van de ander

    Bij een groep van drie ('bosui', 'lente-ui', 'lente-uitjes') komt het
    ingredient met de meeste recepten vooraan te staan en worden de anderen
    er los naast gezet: je bevestigt dan twee keer, en ziet bij elke stap wat
    er gebeurt. Paren die je 'apart' hebt genoemd vallen weg.
    """
    ingredienten = Ingredient.query.all()
    if len(ingredienten) < 2:
        return []

    per_id = {i.id: i for i in ingredienten}
    recepten = defaultdict(int)
    for rij in db.session.query(
            RecipeIngredient.ingredient_id, db.func.count(RecipeIngredient.id)
    ).group_by(RecipeIngredient.ingredient_id).all():
        recepten[rij[0]] = rij[1]

    voorraad = {p.ingredient_id for p in PantryIngredient.query.all()}
    conversies = defaultdict(list)
    for conv in IngredientUnitConversion.query.all():
        conversies[conv.ingredient_id].append(conv)

    # In één keer ophalen: dit scherm staat naast 400 ingredienten, een telling
    # per kandidaat zou tientallen losse queries kosten.
    aliassen = defaultdict(int)
    for rij in db.session.query(
            IngredientAlias.ingredient_id, db.func.count(IngredientAlias.id)
    ).group_by(IngredientAlias.ingredient_id).all():
        aliassen[rij[0]] = rij[1]

    apart = apart_paren()
    gezien = set()
    paren = []

    for reden, bewijs, groep in _groepen(ingredienten):
        # De koploper wordt het voorstel: die heeft de meeste receptregels, dus
        # daar hoeft het minste te verhuizen.
        geordend = sorted(groep, key=lambda i: (-recepten[i.id], i.id))
        kop = geordend[0]
        for ander in geordend[1:]:
            stel = (min(kop.id, ander.id), max(kop.id, ander.id))
            if stel in gezien:
                continue
            if _is_apart(kop, ander, apart):
                continue
            gezien.add(stel)
            paren.append({
                'sleutel': f'{reden}-{stel[0]}-{stel[1]}',
                'reden': reden,
                'bewijs': bewijs,
                'ingredienten': [
                    _kandidaat(per_id[i.id], recepten, voorraad, conversies, aliassen)
                    for i in (kop, ander)
                ],
            })

    volgorde = {'ah': 0, 'schrijfwijze': 1, 'meervoud': 2}
    paren.sort(key=lambda p: (volgorde.get(p['reden'], 9),
                              -sum(i['recepten'] for i in p['ingredienten']),
                              p['ingredienten'][0]['naam']))
    return paren


def _groepen(ingredienten):
    """(reden, bewijs, [ingredienten]) per signaal."""
    per_ah = defaultdict(list)
    per_sleutel = defaultdict(list)
    per_naam = {}
    for ing in ingredienten:
        if ing.ah_product_id:
            per_ah[ing.ah_product_id].append(ing)
        per_sleutel[variantsleutel(ing.name)].append(ing)
        per_naam.setdefault(ing.name, ing)

    for product_id, groep in per_ah.items():
        if len(groep) > 1:
            naam = next((i.ah_product_name for i in groep if i.ah_product_name), None)
            label = f'{naam} (#{product_id})' if naam else f'#{product_id}'
            yield 'ah', f'Allebei gekoppeld aan hetzelfde AH-product: {label}', groep

    for sleutel, groep in per_sleutel.items():
        if sleutel and len(groep) > 1:
            yield 'schrijfwijze', 'Zelfde naam op spaties en streepjes na', groep

    for naam, ing in per_naam.items():
        for staart in _MEERVOUD:
            if not naam.endswith(staart):
                continue
            enkelvoud = per_naam.get(naam[:-len(staart)])
            if enkelvoud is not None and enkelvoud.id != ing.id:
                yield ('meervoud',
                       f"'{ing.display}' is '{enkelvoud.display}' met een "
                       f"Nederlandse uitgang erachter",
                       [enkelvoud, ing])
                break


def _is_apart(a, b, apart):
    """Heeft de gebruiker dit paar al uit elkaar gehouden?"""
    return ((variantsleutel(a.name), b.id) in apart
            or (variantsleutel(b.name), a.id) in apart)


def _kandidaat(ing, recepten, voorraad, conversies, aliassen):
    """Alles wat je moet weten om te kiezen, zonder in de database te kijken."""
    return {
        'id': ing.id,
        'naam': ing.display,
        'canoniek': ing.name,
        'categorie': ing.category,
        'preferred_unit': ing.preferred_unit or '',
        'recepten': recepten.get(ing.id, 0),
        'in_voorraad': ing.id in voorraad,
        'conversies': [f'{c.from_unit} → {c.to_unit} (×{c.factor:g})'
                       for c in conversies.get(ing.id, [])],
        'ah_product_id': ing.ah_product_id,
        'ah_product_name': ing.ah_product_name,
        'verpakking': (f'{ing.ah_pkg_qty:g} {ing.ah_pkg_unit}'
                       if ing.ah_pkg_qty and ing.ah_pkg_unit else ''),
        'aliassen': aliassen.get(ing.id, 0),
    }
