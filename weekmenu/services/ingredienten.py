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

Twee dingen mogen bij zo'n samenvoeging niet gebeuren, en daar gaat het meeste
werk in deze module naartoe:

  - een regel mag niet van betekenis veranderen. 'stuks' is bij Knoflook een
    bolletje van twaalf tenen en bij Knoflookteen één teen; wie alleen het
    ingredient_id omzet maakt van twee tenen vierentwintig. Zie
    _bevries_eenheden, en _eenheidsbotsingen voor de waarschuwing vooraf.
  - er mag geen besluit ontstaan dat je nooit genomen hebt. Wat je over de
    regel van de verliezer besloot ging over die regel, niet over het geheel.
    Zie _wis_weekbesluiten, en _voorraad_volgt_de_winnaar voor dezelfde
    afweging bij de voorraadkast.
"""
import re
from collections import defaultdict

from weekmenu.constants import _MEETEENHEDEN, _UNIT_BUY_ONE, _UNIT_CONVERSIONS
from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, IngredientAlias,
    IngredientUnitConversion, MaatOverslaan, MenuItem, PantryIngredient,
    QuickAddItem, RecipeIngredient, ShoppingCheck, ShoppingListExclusion,
    ShoppingListOverride, VariantApart,
)
from weekmenu.services.units import (
    _convert_unit_for_agg, _norm_unit, _normalize_ingredient,
)
from weekmenu.services.verpakking import _getal


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
# Dit zijn de rijen die iets over het PRODUCT vastleggen: 'een bos is zes
# stuks', 'deze spelling is iets anders'. Die blijven kloppen als de twee
# schrijfwijzen één product worden.
#
# pantry_ingredient stond hier ook in en hoort er niet: zie
# _voorraad_volgt_de_winnaar.
#
# ingredient_unit_conversion heeft in de database UNIQUE(ingredient_id,
# from_unit) staan, en _convert_unit_for_agg zoekt ook alleen op from_unit.
# Daarom is from_unit de sleutel en niet (from_unit, to_unit).
#
# maat_overslaan staat er ook in, en dat is bewust de andere kant op dan bij
# de weekbesluiten hieronder. 'Vraag niet meer wat één teen is' gaat over dít
# product en déze eenheid, niet over één regel in één week — en de
# receptregels die de vraag oproepen verhuizen mee naar de winnaar. Weggooien
# zou dus exact dezelfde vraag over exact dezelfde regels opnieuw stellen.
#
# De afweging van _voorraad_volgt_de_winnaar geldt hier niet: die rij kon
# stil iets van élke boodschappenlijst laten verdwijnen, deze verandert geen
# enkele berekening (zie het model) en houdt alleen een vraag tegen. Blijft
# hij daarentegen achter bij een verwijderd ingredient, dan gaat het wél mis:
# SQLite geeft dat vrijgekomen id aan het eerstvolgende nieuwe ingredient, en
# dat erft dan een besluit over een heel ander product.
_UNIEKE_TABELLEN = (
    (IngredientUnitConversion, ('from_unit',)),
    (VariantApart, ('sleutel',)),
    (MaatOverslaan, ('eenheid',)),
)

# Rijen die niet over het product gaan maar over één REGEL op de lijst van één
# week. Die verhuizen niet mee; zie _wis_weekbesluiten voor het waarom.
_WEEKBESLUITEN = (ShoppingListExclusion, ShoppingListOverride)

# Geen echt ingredient: _convert_unit_for_agg wil alleen een sleutel om de
# conversietabel op te vinden.
_LEESSLEUTEL = -1

# Eenheden die zelf een bundel tellingen zijn: een bosje is een handvol
# stuks, een netje een aantal limoenen. Alleen gebruikt om de vraag '1 … is
# hoeveel …' de goede kant op te zetten; zie _grofheid.
_BUNDELEENHEDEN = {
    'bos', 'bosje', 'bossen', 'bosjes', 'tros', 'krop', 'struik',
    'netje', 'net', 'zak', 'zakje', 'doos', 'doosje', 'bakje', 'pak', 'pakje',
    'pot', 'potje', 'blik', 'blikje', 'fles', 'rol', 'tray', 'krat',
}

# Meervoudsuitgangen die in het Nederlands niets aan het product veranderen.
# Bewust géén bijvoeglijke naamwoorden: 'witte bonen' en 'zwarte bonen' zijn
# echt verschillende producten en mogen nooit als kandidaat opduiken.
_MEERVOUD = ('tjes', 'jes', 'en', 's', 'je')


def variantsleutel(naam):
    """Naam zonder spaties en leestekens: 'rode wijnazijn' == 'rodewijnazijn'."""
    return re.sub(r'[^a-z0-9]', '', _normalize_ingredient((naam or '').lower()))


# ── samenvoegen ──────────────────────────────────────────────────────────

def voeg_samen(verliezer_id, winnaar_id, ah_van_id=None):
    """Voeg de verliezer op in de winnaar. Geeft (payload, statuscode).

    Alles gebeurt in één transactie: gaat er onderweg iets mis, dan staat de
    database er precies zo bij als ervoor. Een half samengevoegd ingredient —
    receptregels verhuisd maar de rij nog aanwezig — zou de boodschappenlijst
    stiller kapotmaken dan het probleem dat we oplossen.

    `ah_van_id` is het antwoord op de vraag welke AH-koppeling er overblijft
    als de twee er allebei een hebben. Zonder antwoord blijft die van de naam
    die je houdt; zie _erf_velden.
    """
    try:
        verliezer_id, winnaar_id = int(verliezer_id or 0), int(winnaar_id or 0)
    except (TypeError, ValueError):
        return {'status': 'error', 'message': 'ongeldige ingredient-id'}, 400

    if verliezer_id == winnaar_id:
        return {'status': 'error', 'message': 'een ingredient kan niet in zichzelf op'}, 400

    try:
        ah_van_id = int(ah_van_id) if ah_van_id else None
    except (TypeError, ValueError):
        ah_van_id = None
    if ah_van_id not in (verliezer_id, winnaar_id):
        ah_van_id = None

    verliezer = Ingredient.query.get(verliezer_id)
    winnaar = Ingredient.query.get(winnaar_id)
    if not verliezer or not winnaar:
        # De kaart is achterhaald: een eerdere klik heeft dit ingredient al
        # opgeruimd. Een gewone foutmelding zou het scherm alleen de knop
        # laten terugzetten; met een eigen status kan de kaart zichzelf
        # bijwerken in plaats van stil niets te doen.
        return {'status': 'vervallen',
                'message': 'een van deze twee ingrediënten bestaat niet meer — '
                           'dit voorstel is vervallen'}, 404

    verliezer_naam = verliezer.display
    verliezer_canoniek = verliezer.name

    try:
        # Eerst de weken vastleggen waarin de verliezer op de lijst stond, want
        # zodra zijn receptregels verhuisd zijn is dat niet meer te zien.
        weken_verliezer = _weken_op_de_lijst(verliezer_id)
        weken_winnaar = _weken_op_de_lijst(winnaar_id)

        # Dan de betekenis van de regels vastzetten, vóór de conversietabellen
        # samengaan — anders leest de winnaar ze met zijn eigen omrekening.
        omgerekend = _bevries_eenheden(verliezer, winnaar)
        db.session.flush()

        verplaatst = _verhuis_receptregels(verliezer_id, winnaar_id)

        # Aliassen kunnen niet botsen: alias is over de hele tabel uniek, dus
        # een verhuizing naar de winnaar houdt hem geldig.
        for alias in IngredientAlias.query.filter_by(ingredient_id=verliezer_id).all():
            alias.ingredient_id = winnaar_id

        for model, sleutelvelden in _UNIEKE_TABELLEN:
            _verhuis_unieke_rijen(model, sleutelvelden, verliezer_id, winnaar_id)

        _voorraad_volgt_de_winnaar(verliezer_id)
        _wis_weekbesluiten(verliezer_id, winnaar_id, weken_verliezer, weken_winnaar)

        # Handmatige boodschappen hebben geen UNIQUE: twee rijen voor dezelfde
        # week zouden blijven staan en dubbel meetellen. Optellen dus.
        _verhuis_unieke_rijen(
            CustomShoppingIngredient, ('year', 'week_number', 'unit'),
            verliezer_id, winnaar_id,
            samenvoegen=lambda blijft, gaat: setattr(
                blijft, 'amount', (blijft.amount or 0) + (gaat.amount or 0)))

        ah_melding = _erf_velden(verliezer, winnaar, ah_van_id)

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
        # Het id van de verliezer erbij, zodat het scherm de andere kaarten
        # kan opzoeken die hem noemen en niet meer kunnen.
        'verliezer_id': verliezer_id,
        'verliezer': verliezer_naam,
        'recepten_verplaatst': verplaatst,
        'omgerekend': omgerekend,
        'ah_melding': ah_melding,
    }, 200


def _conversietabel(ing):
    """De eigen omrekeningen van een ingredient: from_unit -> (to_unit, factor).

    Sleutel op from_unit zoals de boodschappenlijst hem opzoekt, dus zonder
    _norm_unit eroverheen — precies wat _build_shopping_dict doet.

    Bewust een eigen query en niet ing.unit_conversions: die backref laadt de
    collectie op het ingredient, en dan draait SQLAlchemy bij het verwijderen
    van de verliezer de verhuizing van die rijen weer terug.
    """
    return {c.from_unit: (c.to_unit, c.factor) for c
            in IngredientUnitConversion.query.filter_by(ingredient_id=ing.id).all()}


def _eigen_weten(conversies, eenheid):
    """Wat dit ingredient zélf over deze eenheid weet, of None.

    Dit is de enige vraag waar het samenvoegen op hoeft te letten. Een rij in
    ingredient_unit_conversion legt meestal iets over het PRODUCT vast: bij
    Knoflook is 1 stuks twaalf tenen, bij Sjalot is 1 stuks veertig gram. Dat
    weet je alleen van dát product, dus verandert het als een regel naar een
    ander ingredient verhuist — en alleen dán verandert een regel van betekenis.

    Dezelfde tabel wordt ook gebruikt om een gewone maat vast te leggen: kilo's
    naar grammen maal duizend, deciliters naar milliliters maal honderd.
    scripts/normalize_units.py --interactive zet zulke rijen met één enter neer,
    want hij vult de factor voor uit de algemene maattabel. Zo'n rij is geen
    weten van het ingredient: hij staat al in die maattabel, geldt bij elk
    ingredient even hard en houdt de hoeveelheid gelijk. Daarom telt hij hier
    niet mee — anders zou een samenvoeging 1,2 kg voor 1,2 g aanzien.

    Opgezocht zoals de boodschappenlijst hem opzoekt: de genormaliseerde eenheid
    tegen de rauwe from_unit, precies wat _build_shopping_dict doet.
    """
    van = _norm_unit(eenheid)
    naar, factor = conversies.get(van, (None, None))
    if naar is None or _UNIT_CONVERSIONS.get((van, _norm_unit(naar))) == factor:
        return None
    return _norm_unit(naar), factor


def _lees(eenheid, hoeveelheid, conversies, voorkeur):
    """Wat een regel betekent bij een ingredient met deze tabel en voorkeur.

    Dit is dezelfde functie als de boodschappenlijst gebruikt, met een verzonnen
    sleutel ervoor: eerst de eigen conversietabel, dan de algemene omrekentabel,
    anders blijft de eenheid staan. Zo kan het antwoord hier niet uit de pas
    gaan lopen met wat er straks op de lijst komt.

    Zonder `voorkeur` blijft die tweede stap uit en lees je alleen wat dít
    ingredient over de eenheid weet — wat _bevries_eenheden nodig heeft.
    """
    return _convert_unit_for_agg(
        _LEESSLEUTEL, _norm_unit(eenheid), hoeveelheid,
        {(_LEESSLEUTEL, van): naar for van, naar in conversies.items()},
        {_LEESSLEUTEL: voorkeur} if voorkeur else {})


def _regels_met_eenheid(ingredient_id):
    """Alles wat een getal én een eenheid draagt: receptregels en handmatige regels."""
    return (RecipeIngredient.query.filter_by(ingredient_id=ingredient_id).all()
            + CustomShoppingIngredient.query.filter_by(ingredient_id=ingredient_id).all())


def _bevries_eenheden(verliezer, winnaar):
    """Zet de betekenis van de regels vast vóórdat de conversietabellen samengaan.

    Een receptregel draagt alleen een getal en een eenheid; wát die eenheid
    betekent staat bij het ingredient. 'stuks' bij Knoflook is een bolletje van
    twaalf tenen, 'stuks' bij Knoflookteen is één teen. Verhuist zo'n regel
    alleen op ingredient_id, dan valt hij ineens onder de conversie van de
    winnaar en wordt 2 opeens 24 — en andersom net zo goed, want de conversie
    van de verliezer verhuist mee en gaat dan over de regels van de winnaar.

    Daarom eerst dit, aan beide kanten, en met één vraag per regel: weet het
    samengevoegde ingredient iets anders over de eenheid van deze regel dan het
    ingredient waar de regel nu bij hoort? Dat is precies wat _eigen_weten
    beantwoordt. Luidt het antwoord ja, dan schrijven we de oude betekenis in de
    regel zelf, zodat de regel na de samenvoeging nog hetzelfde zegt.

    Meer hoeft er niet vergeleken te worden. Alles wat níét in
    ingredient_unit_conversion staat — de algemene maattabel, de
    voorkeurseenheid die hem aanroept — geldt aan beide kanten even hard en
    verandert dus nooit door een samenvoeging. Kijk je er tóch op, dan zie je
    verschillen die er niet zijn en wordt 1,2 kg omgezet in 1,2 g. Gemeten op
    een kopie van data/weekmenu.db, kaart meervoud-198-237 (kg naast g) en
    kaart ah-21-336 (dl naast el).

    Rekent het samengevoegde ingredient die oude betekenis zelf óók nog om, dan
    zoekt _blijft_staan een schrijfwijze die hij wél met rust laat.

    Geeft terug wat er omgeschreven is, als leesbare regels voor de melding.
    """
    v_conv, w_conv = _conversietabel(verliezer), _conversietabel(winnaar)

    # Wat het samengevoegde ingredient straks weet: de tabel van de winnaar,
    # aangevuld met die van de verliezer waar de winnaar niets had (dat doet
    # _verhuis_unieke_rijen), en de voorkeurseenheid van de winnaar of anders
    # die van de verliezer (dat doet _erf_velden).
    samen_conv = dict(v_conv)
    samen_conv.update(w_conv)
    samen_voorkeur = winnaar.preferred_unit or verliezer.preferred_unit

    omgerekend = []
    for ing, eigen_conv in ((verliezer, v_conv), (winnaar, w_conv)):
        for regel in _regels_met_eenheid(ing.id):
            if _eigen_weten(eigen_conv, regel.unit) == _eigen_weten(samen_conv, regel.unit):
                continue

            hoeveelheid = regel.amount or 0
            oud = _lees(regel.unit, hoeveelheid, eigen_conv, None)
            vorm = _blijft_staan(oud, ing.preferred_unit, samen_conv, samen_voorkeur)
            if vorm is None or vorm == (regel.unit, regel.amount):
                continue

            eenheid, aantal = vorm
            omgerekend.append(f'{ing.display}: {hoeveelheid:g} {regel.unit} '
                              f'→ {aantal:g} {eenheid}')
            regel.unit, regel.amount = eenheid, aantal
    return omgerekend


def _blijft_staan(oud, eigen_voorkeur, samen_conv, samen_voorkeur):
    """De oude betekenis opschrijven zodat het samengevoegde ingredient hem laat staan.

    `oud` is wat de regel bij zijn eigen ingredient betekende: bijvoorbeeld
    2 stuks bij Knoflookteen, waar niets omgerekend werd. Rekent het
    samengevoegde ingredient diezelfde eenheid wél om (1 stuks = 12 teen), dan
    is 'oud' letterlijk overschrijven niet genoeg — de lijst maakt er alsnog
    24 teen van. We zoeken dus een eenheid die hij met rust laat, en zetten het
    aantal daar één op één in over.

    We proberen daarvoor drie schrijfwijzen, en de eerste die het samengevoegde
    ingredient met rust laat wint:

      1. de eenheid van 'oud' zelf. Laat hij die staan, dan is er niets aan de
         hand en houdt de regel gewoon zijn eigen woord.
      2. de eenheid waarin het ingredient van de regel zelf telt
         (preferred_unit). Dat is de meest letterlijke lezing van 'oud': 'stuks'
         bij Knoflookteen wordt 'teen', want een knoflookteen is er één.
      3. de eenheid waarin het samengevoegde ingredient telt (preferred_unit van
         de winnaar, anders van de verliezer). Weet ook die van niets, dan wijst
         de botsende omrekening zelf de eenheid aan waarin hij telt — bij
         Knoflook is dat 'teen'.

    Punt 3 dekt de regels zonder preferred_unit. Die vielen eerder terug op de
    oorspronkelijke eenheid; dan veranderde er niets en kwam het maal-twaalf
    onverkort terug. Twee van de 23 kaarten hebben nu al een kant zonder
    preferred_unit, en de ronde die per ingredient gaat omrekenen zet er
    conversies op.

    Eén op één omzetten is een keuze, geen berekening: was die eenheid bij de
    verliezer stiekem tóch een bundel — de app wist er alleen niets van — dan
    is één op één te weinig. Daarom waarschuwt de kandidatenlijst hierover vóór
    de klik; zie _eenheidsbotsingen.

    Wordt ook die teleenheid zelf omgerekend (preferred_unit 'stuks' naast een
    omrekening ván 'stuks'), dan is er geen eenheid meer die dit ingredient met
    rust laat, en is zijn omrekening het enige wat er over die eenheid bekend
    is. Dan geeft deze functie None terug: de regel blijft staan zoals hij
    stond en krijgt dezelfde behandeling als de regels van de winnaar zelf.
    Eén op één omzetten zou daar juist schade doen — 1 stuks sjalot wordt dan
    1 g in plaats van 40.
    """
    eenheid, aantal = oud

    # De eenheid waarin het samengevoegde ingredient telt. Weet hij dat niet,
    # dan wijst de botsende omrekening hem aan: dat is de eenheid waar hij naar
    # rekent. Die halen we uit de lezing zelf en niet uit een tweede greep in
    # samen_conv, want die tabel is op de rauwe from_unit gesleuteld en een
    # handmatige greep loopt daar vroeg of laat op stuk.
    telt_in = samen_voorkeur or _lees(eenheid, aantal, samen_conv, None)[0]

    for kandidaat in (eenheid, eigen_voorkeur, telt_in):
        if not kandidaat:
            continue
        genormaliseerd = _norm_unit(kandidaat)
        if _lees(kandidaat, aantal, samen_conv, None) == (genormaliseerd, aantal):
            return genormaliseerd, aantal
    return None


def _weken_op_de_lijst(ingredient_id):
    """De (jaar, week)-paren waarin dit ingredient op de boodschappenlijst stond."""
    weken = set()
    recepten = {ri.recipe_id for ri
                in RecipeIngredient.query.filter_by(ingredient_id=ingredient_id).all()}
    if recepten:
        for item in MenuItem.query.filter(MenuItem.recipe_id.in_(recepten)).all():
            if not item.skip_shopping_list:
                weken.add((item.year, item.week_number))
        for item in QuickAddItem.query.filter(QuickAddItem.recipe_id.in_(recepten)).all():
            weken.add((item.year, item.week_number))
    for ci in CustomShoppingIngredient.query.filter_by(ingredient_id=ingredient_id).all():
        weken.add((ci.year, ci.week_number))
    return weken


def _wis_weekbesluiten(verliezer_id, winnaar_id, weken_verliezer, weken_winnaar):
    """Weekbesluiten gaan over een regel op de lijst, niet over een ingredient.

    De regel van de verliezer verdwijnt met deze samenvoeging, dus verdwijnen
    zijn besluiten mee. 'Bosui deze week niet nodig' is geen 'Lente-Ui deze week
    niet nodig': verhuizen maakt een besluit dat je nooit genomen hebt, en doet
    dat onzichtbaar — de regel valt gewoon van de lijst en je merkt het pas in
    de winkel. Weggooien laat hooguit iets terugkomen dat je al weggeklikt had;
    dát zie je, en wegklikken kost één tik.

    De besluiten van de winnaar blijven staan. Die regel bestaat nog, onder
    dezelfde naam, en 'deze week even niet' of 'ik koop er drie' gaat over het
    product — precies wat je met het samenvoegen bevestigt.

    Afvinken ligt nét anders. Een vinkje is geen besluit over de lijst maar een
    feit: dit ligt al in de kar. De vraag is dus niet van wie het vinkje was,
    maar of het de regel dekt die na de samenvoeging overblijft.

    Drie gevallen, en ze volgen allemaal uit die ene vraag:
    - Allebei afgevinkt: samen dekken ze de hele regel. Eén vinkje blijft.
    - De winnaar afgevinkt terwijl de verliezer die week nog open stond: de
      regel wordt groter dan wat je afvinkte, dus het vinkje dekt hem niet meer
      en gaat eraf — anders verdwijnt het deel dat je nog moet halen uit zicht.
    - De verliezer afgevinkt terwijl de WINNAAR die week niets had: dan is de
      samengevoegde regel letterlijk de regel van de verliezer, even groot, en
      dekt zijn vinkje hem precies. Het verhuist mee. Gemeten op de echte data
      ging het bij alle vijf de kaarten die een vinkje wisten om juist dit
      geval: er kwam telkens iets terug op de lijst dat allang in de kar lag.
    """
    for model in _WEEKBESLUITEN:
        for rij in model.query.filter_by(ingredient_id=verliezer_id).all():
            db.session.delete(rij)

    van_winnaar = {(r.year, r.week_number) for r
                   in ShoppingCheck.query.filter_by(ingredient_id=winnaar_id).all()}

    afgevinkt = set()
    for rij in ShoppingCheck.query.filter_by(ingredient_id=verliezer_id).all():
        week = (rij.year, rij.week_number)
        afgevinkt.add(week)
        # Alleen meeverhuizen als het vinkje een regel dekt die er straks nog
        # is: de verliezer stond die week op de lijst en de winnaar niet.
        # Zonder regel is een vinkje een overblijfsel en gaat het gewoon weg.
        if week in weken_verliezer and week not in weken_winnaar and week not in van_winnaar:
            rij.ingredient_id = winnaar_id      # zelfde regel, zelfde vinkje
        else:
            db.session.delete(rij)

    for rij in ShoppingCheck.query.filter_by(ingredient_id=winnaar_id).all():
        week = (rij.year, rij.week_number)
        if week in weken_verliezer and week not in afgevinkt:
            db.session.delete(rij)


def _voorraad_volgt_de_winnaar(verliezer_id):
    """'Altijd in huis' ging over één schrijfwijze, niet over allebei.

    Dit is dezelfde familie als de weekbesluiten hierboven. 'Ik heb
    rodewijnazijn in huis' zei je terwijl 'rode wijnazijn' een aparte rij was;
    dat je die twee nu hetzelfde product noemt, maakt de fles in je kast niet
    groter. Verhuisde de voorraadrij mee naar een winnaar die er zelf geen had,
    dan gold het samengevoegde ingredient ineens overal als 'heb ik al' en
    verdween het uit ELKE boodschappenlijst — zonder iets op het scherm.

    Er waren twee redelijke uitwegen, en ze komen op hetzelfde neer: de rij van
    de verliezer weggooien (zoals bij de weekbesluiten), of hem alleen laten
    meeverhuizen als de winnaar er zelf ook een had — want in dat geval botst
    hij en gaat hij toch weg. In beide gevallen staat het samengevoegde
    ingredient in de kast precies dan als de winnaar erin stond.

    Die kant kiezen we bewust, want de twee fouten wegen niet even zwaar. Blijft
    de kast te leeg, dan komt er iets op de lijst dat je al had: dat zie je
    staan, en één tik zet het terug in de kast. Blijft de kast te vol, dan
    verdwijnt er iets van elke lijst en merk je het pas in de winkel. Daarom
    waarschuwt de kandidatenlijst hier ook vooraf; zie _voorraadverschil.
    """
    for rij in PantryIngredient.query.filter_by(ingredient_id=verliezer_id).all():
        db.session.delete(rij)


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


def _erf_velden(verliezer, winnaar, ah_van_id=None):
    """Wat de winnaar mist en de verliezer wel heeft, gaat mee.

    De AH-koppeling is de uitzondering waar een keuze bij hoort. 'Dit is
    hetzelfde product' zegt niets over wélk schap je bedoelt: 'limoen' hangt
    aan een losse limoen van € 0,79 en 'limoenen' aan een netje van vier van
    € 1,29. Wie zomaar die van de winnaar houdt, gooit de andere weg zonder
    het te laten zien — gemeten op data/weekmenu.db ging week 37 daarmee van
    één netje naar twee losse limoenen, en gaven dezelfde twee klikken in een
    andere volgorde een ander product.

    Daarom vraagt de kaart het (zie _ah_verschil) en beslist `ah_van_id` het:
    het ingredient waarvan de koppeling overblijft. Dat is een uitspraak over
    het product, niet over een naam, dus komt er in beide volgordes hetzelfde
    uit zolang je hetzelfde product aanwijst.

    Zonder antwoord blijft de koppeling van de naam die je houdt — en heeft
    die er geen, dan erft hij die van de verliezer: een halve koppeling
    weggooien maakt de lijst alleen maar dommer.

    Geeft terug wat er met de koppelingen gebeurd is, als tekst voor de
    bevestiging op het scherm.
    """
    neem_over = (verliezer.ah_product_id
                 and (ah_van_id == verliezer.id or not winnaar.ah_product_id))
    melding = _ah_melding(verliezer, winnaar, neem_over)
    if neem_over:
        for veld in _AH_VELDEN:
            setattr(winnaar, veld, getattr(verliezer, veld))

    for veld in ('preferred_unit', 'bron'):
        if not getattr(winnaar, veld) and getattr(verliezer, veld):
            setattr(winnaar, veld, getattr(verliezer, veld))
    return melding


def _ah_melding(verliezer, winnaar, neem_over):
    """In gewone taal welke AH-koppeling er overblijft, of '' als er niets speelt."""
    if verliezer.ah_product_id == winnaar.ah_product_id:
        return ''
    if neem_over and not winnaar.ah_product_id:
        return (f'De AH-koppeling van ‘{verliezer.display}’ '
                f'({_ah_omschrijving(verliezer)}) gaat mee naar '
                f'‘{winnaar.display}’.')
    blijft, vervalt = (verliezer, winnaar) if neem_over else (winnaar, verliezer)
    if not vervalt.ah_product_id:
        return ''
    return (f'AH-koppeling: ‘{winnaar.display}’ krijgt '
            f'{_ah_omschrijving(blijft)}; die van ‘{vervalt.display}’ '
            f'({_ah_omschrijving(vervalt)}) vervalt.')


def _ah_omschrijving(ing):
    """'AH Limoenen (#519646, verpakking 4 stuks, € 1,29)'."""
    if not ing.ah_product_id:
        return 'geen AH-koppeling'
    deel = [f'#{ing.ah_product_id}']
    if ing.ah_pkg_qty and ing.ah_pkg_unit:
        deel.append(f'verpakking {ing.ah_pkg_qty:g} {ing.ah_pkg_unit}')
    if ing.ah_product_price:
        deel.append(f'€ {ing.ah_product_price}')
    naam = ing.ah_product_name or 'AH-product'
    return f"{naam} ({', '.join(deel)})"


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


# ── de omrekening die de app zelf niet kan verzinnen ─────────────────────

def leg_omrekening_vast(ingredient_id, ander_id, van, naar, factor):
    """'1 bosje is vier stuks': wat jij weet en de app niet.

    Zonder zo'n regel blijven twee eenheden na het samenvoegen twee regels op
    de boodschappenlijst — precies wat het samenvoegen moest oplossen. De app
    mag er zelf niets voor verzinnen: hoeveel bosuitjes er in een bosje gaan
    weet alleen jij. Zie _gespleten_eenheden voor de vraag die hierbij hoort.

    De regel komt bij allebei de ingredienten te staan, want het is een
    uitspraak over het PRODUCT en niet over een van de twee namen. Zo krijg je
    dezelfde lijst welke naam je ook houdt, en klopt hij ook als je het paar
    daarna toch apart laat.
    """
    ing = Ingredient.query.get(ingredient_id) if ingredient_id else None
    ander = Ingredient.query.get(ander_id) if ander_id else None
    if not ing or not ander:
        return {'status': 'vervallen',
                'message': 'een van deze twee ingrediënten bestaat niet meer — '
                           'dit voorstel is vervallen'}, 404

    van, naar = _norm_unit(van), _norm_unit(naar)
    if not van or not naar or van == naar:
        return {'status': 'error', 'message': 'twee verschillende eenheden graag'}, 400
    if _UNIT_CONVERSIONS.get((van, naar)):
        return {'status': 'error',
                'message': f'‘{van}’ en ‘{naar}’ rekent de app zelf al om'}, 400

    getal = _getal(factor)
    if getal is None or getal <= 0:
        return {'status': 'error', 'message': 'geen bruikbaar getal'}, 400

    # Eén rij per ingredient: from_unit is uniek per ingredient, en dezelfde
    # twee ids twee keer zou de tweede rij op de database laten stuklopen.
    betrokken = [ing] if ing.id == ander.id else [ing, ander]
    for i in betrokken:
        if IngredientUnitConversion.query.filter_by(
                ingredient_id=i.id, from_unit=van).first():
            return {'status': 'error',
                    'message': f'er staat al een omrekening voor ‘{van}’ bij '
                               f'‘{i.display}’ — ververs de pagina'}, 400

    for i in betrokken:
        db.session.add(IngredientUnitConversion(
            ingredient_id=i.id, from_unit=van, to_unit=naar, factor=getal,
            reasoning='met de hand opgegeven bij het samenvoegen'))
        _ook_de_verpakking(i, van, naar, getal)
    db.session.commit()
    return {'status': 'ok', 'van': van, 'naar': naar, 'factor': getal}, 200


def _ook_de_verpakking(ing, van, naar, factor):
    """Is `van` de verpakkingseenheid, dan is dit ook het antwoord op de maatvraag.

    Zonder deze stap gaat de boodschappenlijst er juist op achteruit. De regels
    vallen dan wel samen — 1 bosje plus 1,5 stuks wordt 5,5 stuks — maar de
    verpakking telt in bosjes en weet nog steeds niet hoeveel stuks daarin
    gaan, dus valt hij terug op afronden en bestelt zes bosjes. Gemeten op een
    kopie van data/weekmenu.db: 46 verpakkingen werden er zo 48.

    'Eén bosje is vier stuks' is precies de vraag die /ah-producten stelt en in
    ah_conv_factor bewaart. Hetzelfde antwoord, dus zetten we het daar ook neer
    — maar alleen als de gebruiker het over déze verpakking heeft en er nog
    geen antwoord staat: een bestaand antwoord overschrijven zou een keuze
    ongevraagd omgooien.
    """
    if _norm_unit(ing.ah_pkg_unit) != van or ing.ah_conv_factor:
        return
    ing.ah_conv_factor, ing.ah_conv_unit = factor, naar
    for rij in MaatOverslaan.query.filter_by(ingredient_id=ing.id, eenheid=naar).all():
        db.session.delete(rij)


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
        # Net als bij voeg_samen: de kaart is achterhaald, en dat hoort hij te
        # zeggen in plaats van de knop stil terug te zetten.
        return {'status': 'vervallen',
                'message': 'een van deze twee ingrediënten bestaat niet meer — '
                           'dit voorstel is vervallen'}, 404
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
    tabellen = defaultdict(dict)
    for conv in IngredientUnitConversion.query.all():
        conversies[conv.ingredient_id].append(conv)
        tabellen[conv.ingredient_id][conv.from_unit] = (conv.to_unit, conv.factor)

    # Welke eenheden er per ingredient echt in regels staan — anders zou de
    # waarschuwing over een botsing gaan die niemand ooit tegenkomt.
    gebruikt = defaultdict(set)
    for model in (RecipeIngredient, CustomShoppingIngredient):
        for ing_id, eenheid in db.session.query(
                model.ingredient_id, model.unit).distinct().all():
            gebruikt[ing_id].add(_norm_unit(eenheid))

    # In één keer ophalen: dit scherm staat naast 400 ingredienten, een telling
    # per kandidaat zou tientallen losse queries kosten.
    aliassen = defaultdict(int)
    for rij in db.session.query(
            IngredientAlias.ingredient_id, db.func.count(IngredientAlias.id)
    ).group_by(IngredientAlias.ingredient_id).all():
        aliassen[rij[0]] = rij[1]

    # Weekbesluiten per ingredient, in één telling: de kaart moet melden dat
    # de besluiten van de verliezer vervallen (zie _wis_weekbesluiten).
    besluiten = defaultdict(lambda: [0, 0])
    for stand, model in enumerate(_WEEKBESLUITEN):
        for rij in db.session.query(
                model.ingredient_id, db.func.count(model.id)
        ).group_by(model.ingredient_id).all():
            besluiten[rij[0]][stand] = rij[1]

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
                'eenheidsbotsing': _eenheidsbotsingen(kop, ander, tabellen, gebruikt),
                'gespleten': _gespleten_eenheden(kop, ander, tabellen, gebruikt),
                'ah_verschil': _ah_verschil(kop, ander),
                'weekbesluiten': _weekbesluitmelding(kop, ander, besluiten),
                'voorraadverschil': _voorraadverschil(kop, ander, voorraad),
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


def _eenheidsbotsingen(a, b, tabellen, gebruikt):
    """Eenheden die deze twee ingredienten verschillend lezen, in gewone taal.

    Zonder deze regel op het scherm is het samenvoegen een sprong in het duister:
    'stuks' is bij Knoflook een bolletje van twaalf tenen en bij Knoflookteen één
    teen, en pas op de boodschappenlijst zou blijken dat er iets geks gebeurde.
    _bevries_eenheden houdt elke regel op zijn oude betekenis, maar bij een
    eenheid die de app niet kende gokt hij één op één (zie daar). Zo'n gok hoor
    je te zien vóór je klikt, niet erna.

    Waarschuwen doen we op precies dezelfde vraag als waar het samenvoegen op
    beslist — _eigen_weten — anders gaat het scherm iets anders melden dan er
    daarna gebeurt. Een rij die alleen de meetlat herhaalt (kg naar g maal
    duizend) verandert dus niets en haalt dus ook het scherm niet.

    Alleen eenheden die ook echt in regels voorkomen: een botsing die nergens
    staat verandert niets, en een waarschuwing die nooit ergens over gaat leert
    je hem wegkijken.

    `tabellen` en `gebruikt` komen kant en klaar van de aanroeper, want dit
    draait per kandidatenpaar en het scherm staat naast 400 ingredienten.
    """
    a_conv, b_conv = tabellen.get(a.id, {}), tabellen.get(b.id, {})
    in_gebruik = gebruikt.get(a.id, set()) | gebruikt.get(b.id, set())

    botsingen = []
    for eenheid in sorted(set(a_conv) | set(b_conv)):
        if _norm_unit(eenheid) not in in_gebruik:
            continue
        if _eigen_weten(a_conv, eenheid) == _eigen_weten(b_conv, eenheid):
            continue
        a_lezing = _lees(eenheid, 1.0, a_conv, a.preferred_unit)
        b_lezing = _lees(eenheid, 1.0, b_conv, b.preferred_unit)
        botsingen.append(
            f"‘{eenheid}’ betekent niet hetzelfde: bij {a.display} is 1 {eenheid} "
            f"{_toon_lezing(eenheid, a_lezing)}, bij {b.display} is 1 {eenheid} "
            f"{_toon_lezing(eenheid, b_lezing)}")
    return botsingen


def _gespleten_eenheden(a, b, tabellen, gebruikt):
    """Eenheden die ook ná het samenvoegen twee regels blijven.

    Dit is de belofte van de hele functie, en precies waar hij het stilst
    breekt. Gemeten op data/weekmenu.db: 'bosui', 'lente-ui' en 'lente-uitjes'
    zijn hetzelfde product, maar de een telt in stuks en de ander in bosjes.
    Na alle drie de voorgestelde samenvoegingen stond 'Lente-Ui' in week 37
    alsnog twee keer op de lijst — 1 bosje naast 1,5 stuks — met twee
    verpakkingen. _eenheidsbotsingen zag daar niets: die kijkt alleen naar
    ingredient_unit_conversion, en die rijen zijn er bij deze drie niet.

    De vraag hier is een andere: welke eenheden houdt het samengevoegde
    ingredient straks over? We lezen elke eenheid die echt in regels staat
    zoals de boodschappenlijst hem straks zal lezen — met de conversietabel
    van de twee samen en de voorkeurseenheid die overblijft. Komen daar meer
    eenheden uit, dan worden dat meer regels.

    Eén uitzondering: eenheden waarvan je er altijd één koopt (gram, milliliter,
    eetlepels) smelt de lijst zelf al samen tot één regel, zie _UNIT_BUY_ONE in
    _build_shopping_dict. Daar valt dus niets te melden.

    Verzinnen doen we niets: hoeveel bosuitjes er in een bosje gaan weet alleen
    de gebruiker. Bij precies twee eenheden vraagt de kaart het hem, en
    leg_omrekening_vast zet het antwoord neer.
    """
    samen_conv = dict(tabellen.get(b.id, {}))
    samen_conv.update(tabellen.get(a.id, {}))
    samen_voorkeur = a.preferred_unit or b.preferred_unit

    uit = {}
    for eenheid in sorted(gebruikt.get(a.id, set()) | gebruikt.get(b.id, set())):
        if not eenheid:
            continue
        uit.setdefault(_lees(eenheid, 1.0, samen_conv, samen_voorkeur)[0], eenheid)

    if len(uit) < 2 or all(e in _UNIT_BUY_ONE for e in uit):
        return None

    eenheden = sorted(uit)
    # De vraag gaat van grof naar fijn: '1 bosje is hoeveel stuks' kan een mens
    # beantwoorden, '1 gram is hoeveel stuks' niet. Tellen de twee even fijn
    # ('stuks' naast 'teen'), dan wint de eenheid waarin het samengevoegde
    # ingredient toch al telt.
    naar = min(eenheden, key=lambda e: (_grofheid(e), e != samen_voorkeur, e))
    van = [e for e in eenheden if e != naar]
    melding = (f'‘{"’ en ‘".join(eenheden)}’ vallen niet samen: het blijft na '
               f'het samenvoegen twee regels op de boodschappenlijst, elk met '
               f'een eigen verpakking. De app weet niet hoeveel {naar} er in '
               f'één {van[0]} gaan.')
    if len(eenheden) > 2:
        melding = (f'‘{"’, ‘".join(eenheden)}’ vallen niet samen: dat blijven '
                   f'na het samenvoegen evenveel regels op de boodschappenlijst.')
    return {'melding': melding,
            'van': van[0] if len(eenheden) == 2 else '',
            'naar': naar if len(eenheden) == 2 else ''}


def _grofheid(eenheid):
    """Hoe groot de eenheid is: 0 meten, 1 tellen, 2 een bundel van tellingen.

    Alleen om de vraag de goede kant op te zetten. Gram is de fijnste maat die
    er is, een bosje de grofste: '1 bosje is vier stuks' en '1 stuks is 150 g'
    zijn te beantwoorden, andersom niet.
    """
    if eenheid in _MEETEENHEDEN:
        return 0
    return 2 if eenheid in _BUNDELEENHEDEN else 1


def _ah_verschil(a, b):
    """Hangen deze twee aan verschillende AH-producten, dan hoor je te kiezen.

    'Dit is hetzelfde product' zegt niets over welk schap je bedoelt. Gemeten
    op data/weekmenu.db: 'limoen' hangt aan een losse limoen en 'limoenen' aan
    een netje van vier. Wie de koppeling van de verliezer stil weggooit maakt
    van één netje twee losse limoenen — duurder, en onzichtbaar.

    `keuze` bevat de twee ingredient-ids als er echt iets te kiezen valt; heeft
    maar één kant een koppeling, dan gaat die hoe dan ook mee en is er alleen
    iets te melden. Zie _erf_velden voor wat er met het antwoord gebeurt.
    """
    if a.ah_product_id == b.ah_product_id:
        return None
    if a.ah_product_id and b.ah_product_id:
        return {
            'melding': (f'Twee verschillende AH-producten: ‘{a.display}’ hangt '
                        f'aan {_ah_omschrijving(a)}, ‘{b.display}’ aan '
                        f'{_ah_omschrijving(b)}. Er blijft er één over — kies '
                        f'welke, want dat bepaalt hoeveel verpakkingen de lijst '
                        f'straks bestelt.'),
            'keuze': [a.id, b.id],
        }
    heeft, mist = (a, b) if a.ah_product_id else (b, a)
    return {
        'melding': (f'Alleen ‘{heeft.display}’ is aan een AH-product gekoppeld '
                    f'({_ah_omschrijving(heeft)}); ‘{mist.display}’ niet. Die '
                    f'koppeling gaat mee, welke naam je ook houdt.'),
        'keuze': [],
    }


def _weekbesluitmelding(a, b, besluiten):
    """Wat er met 'deze week even niet' gebeurt, vóór je klikt.

    De weekbesluiten van de verliezer vervallen; dat is een bewuste keuze en
    staat uitgelegd bij _wis_weekbesluiten. Maar de gebruiker ziet hem niet
    aankomen. Gemeten op een kopie van data/weekmenu.db: de 23 voorstellen
    raken acht weekbesluiten van week 37, en na alle 23 samenvoegingen komen er
    drie weggeklikte regels terug op de lijst — 'Bosui', 'magere yoghurt' en de
    cheddar. Dat is precies het verschil dat de lijst van die week langer en
    duurder maakt in plaats van korter.

    Welke kant verliest weet de kaart nog niet, dus noemen we ze allebei.
    """
    delen = []
    for ing in (a, b):
        weg, aangepast = besluiten.get(ing.id, (0, 0))
        stukjes = []
        if weg:
            stukjes.append(f'{weg} week weggeklikt' if weg == 1
                           else f'{weg} weken weggeklikt')
        if aangepast:
            stukjes.append(f'{aangepast} aangepast aantal' if aangepast == 1
                           else f'{aangepast} aangepaste aantallen')
        if stukjes:
            delen.append(f'‘{ing.display}’ heeft {" en ".join(stukjes)}')
    if not delen:
        return ''
    return (f'{"; ".join(delen)}. Zulke besluiten gaan over één regel in één '
            f'week, dus vervallen ze bij de naam die je niet houdt — die regels '
            f'komen dan weer op de boodschappenlijst.')


def _voorraadverschil(a, b, voorraad):
    """De ene staat in de voorraadkast en de andere niet — dat hoor je te zien.

    Het is dezelfde soort mededeling als de botsende eenheid: iets wat na de
    klik anders is dan je zou raden, en wat je erna alleen in de winkel merkt.
    'Ik heb rodewijnazijn in huis' zei je over die ene schrijfwijze; welke van
    de twee je nu houdt, bepaalt of het samengevoegde ingredient nog van de
    lijst geweerd wordt. Zie _voorraad_volgt_de_winnaar voor de keuze zelf.

    Staan ze er allebei in of allebei niet, dan is er niets te melden.
    """
    kast = [i for i in (a, b) if i.id in voorraad]
    buiten = [i for i in (a, b) if i.id not in voorraad]
    if len(kast) != 1 or len(buiten) != 1:
        return ''
    return (f'‘{kast[0].display}’ staat in de voorraadkast en '
            f'‘{buiten[0].display}’ niet. De voorraadrij blijft bij de naam die '
            f'je houdt: houd je ‘{buiten[0].display}’, dan staat het '
            f'samengevoegde ingrediënt niet meer in de kast en komt het weer '
            f'op de boodschappenlijst.')


def _toon_lezing(eenheid, lezing):
    """'12 teen', of 'gewoon 1 stuks' als het ingredient de eenheid laat staan."""
    naar, aantal = lezing
    if naar == _norm_unit(eenheid) and aantal == 1:
        return f'gewoon 1 {naar}'
    return f'{aantal:g} {naar}'


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
