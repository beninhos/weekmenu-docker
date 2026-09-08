"""Varianten van hetzelfde product samenvoegen tot één boodschappenregel.

'knoflook' en 'knoflookteen' waren twee ingredientrijen, dus twee regels op de
lijst met elk een eigen verpakkingsberekening: twee bolletjes voor vier tenen.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, IngredientAlias,
    IngredientUnitConversion, MaatOverslaan, MenuItem, PantryIngredient, Recipe,
    RecipeIngredient, ShoppingCheck, ShoppingListExclusion, ShoppingListOverride,
    VariantApart,
)
from weekmenu.services.ingredienten import (
    markeer_apart, markeer_paar_apart, koppel_alias, samenvoeg_kandidaten, voeg_samen,
)
from weekmenu.services.recipes import _resolve_or_create_ingredient
from weekmenu.services.shopping import build_combined_shopping_list

VANDAAG = date(2026, 7, 11)   # zaterdag, ISO-week 28


# ── bouwstenen ───────────────────────────────────────────────────────────

def _ing(naam, **velden):
    ing = Ingredient(name=naam, display_name=velden.pop('display_name', naam.capitalize()),
                     category=velden.pop('category', 'Groente, Fruit & Aardappelen'))
    for veld, waarde in velden.items():
        setattr(ing, veld, waarde)
    db.session.add(ing)
    db.session.flush()
    db.session.add(IngredientAlias(alias=naam, ingredient_id=ing.id))
    db.session.flush()
    return ing


def _recept(naam, ing, hoeveelheid, eenheid='teen', serves=4, bereiding=None):
    r = Recipe(name=naam, serves=serves)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=hoeveelheid, unit=eenheid,
                                    preparation=bereiding))
    db.session.flush()
    return r


def _knoflookpaar():
    """De echte situatie uit data/weekmenu.db: zelfde AH-product, één conversie."""
    winnaar = _ing('knoflook', display_name='Knoflook', preferred_unit='teen',
                   ah_product_id=4160, ah_product_name='AH Knoflook',
                   ah_pkg_qty=2.0, ah_pkg_unit='stuks')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='stuks',
                                            to_unit='teen', factor=12.0))
    verliezer = _ing('knoflookteen', display_name='Knoflookteen', preferred_unit='teen',
                     ah_product_id=4160, ah_product_name='AH Knoflook',
                     ah_pkg_qty=2.0, ah_pkg_unit='stuks')
    db.session.commit()
    return winnaar, verliezer


# ── samenvoegen ──────────────────────────────────────────────────────────

def test_samenvoegen_haalt_receptregels_van_beide_kanten_bij_elkaar(app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', winnaar, 3)
    _recept('Soep', verliezer, 2)
    db.session.commit()

    payload, code = voeg_samen(verliezer.id, winnaar.id)

    assert code == 200
    assert payload['recepten_verplaatst'] == 1
    assert Ingredient.query.get(verliezer.id) is None
    assert RecipeIngredient.query.filter_by(ingredient_id=winnaar.id).count() == 2


def test_samenvoegen_smelt_twee_regels_in_hetzelfde_recept_samen(app):
    winnaar, verliezer = _knoflookpaar()
    r = _recept('Aioli', winnaar, 2)
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=verliezer.id,
                                    amount=1, unit='teen'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regels = RecipeIngredient.query.filter_by(recipe_id=r.id).all()
    assert len(regels) == 1
    assert regels[0].amount == 3


def test_samenvoegen_laat_een_andere_bereiding_een_eigen_regel(app):
    winnaar, verliezer = _knoflookpaar()
    r = _recept('Aioli', winnaar, 2, bereiding='geperst')
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=verliezer.id,
                                    amount=1, unit='teen', preparation='fijngesneden'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regels = RecipeIngredient.query.filter_by(recipe_id=r.id).all()
    assert len(regels) == 2
    assert sorted(x.preparation for x in regels) == ['fijngesneden', 'geperst']


def test_samenvoegen_houdt_bij_een_botsing_de_rij_van_de_winnaar(app):
    winnaar, verliezer = _knoflookpaar()
    db.session.add(PantryIngredient(ingredient_id=winnaar.id))
    db.session.add(PantryIngredient(ingredient_id=verliezer.id))
    db.session.add(ShoppingListOverride(year=2026, week_number=28,
                                        ingredient_id=winnaar.id, qty=1))
    db.session.add(ShoppingListOverride(year=2026, week_number=28,
                                        ingredient_id=verliezer.id, qty=9))
    db.session.commit()

    payload, code = voeg_samen(verliezer.id, winnaar.id)

    assert code == 200
    assert PantryIngredient.query.count() == 1
    overrides = ShoppingListOverride.query.all()
    assert len(overrides) == 1
    assert overrides[0].qty == 1              # die van de winnaar
    assert overrides[0].ingredient_id == winnaar.id


def test_samenvoegen_verhuist_een_rij_die_de_winnaar_nog_niet_had(app):
    winnaar, verliezer = _knoflookpaar()
    db.session.add(CustomShoppingIngredient(year=2026, week_number=28,
                                            ingredient_id=verliezer.id,
                                            amount=4, unit='teen'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    rijen = CustomShoppingIngredient.query.all()
    assert len(rijen) == 1
    assert rijen[0].ingredient_id == winnaar.id


def test_samenvoegen_telt_dezelfde_handmatige_regel_bij_elkaar_op(app):
    winnaar, verliezer = _knoflookpaar()
    db.session.add(CustomShoppingIngredient(year=2026, week_number=28,
                                            ingredient_id=winnaar.id, amount=2, unit='teen'))
    db.session.add(CustomShoppingIngredient(year=2026, week_number=28,
                                            ingredient_id=verliezer.id, amount=4, unit='teen'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    rijen = CustomShoppingIngredient.query.all()
    assert len(rijen) == 1
    assert rijen[0].amount == 6


def test_samenvoegen_neemt_de_conversie_van_de_verliezer_over(app):
    winnaar = _ing('bosui', preferred_unit='stuks')
    verliezer = _ing('lente-ui', preferred_unit='stuks')
    db.session.add(IngredientUnitConversion(ingredient_id=verliezer.id, from_unit='bos',
                                            to_unit='stuks', factor=6.0))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    convs = IngredientUnitConversion.query.filter_by(ingredient_id=winnaar.id).all()
    assert [(c.from_unit, c.to_unit, c.factor) for c in convs] == [('bos', 'stuks', 6.0)]


def test_samenvoegen_houdt_de_conversie_van_de_winnaar_bij_dezelfde_eenheid(app):
    winnaar, verliezer = _knoflookpaar()
    db.session.add(IngredientUnitConversion(ingredient_id=verliezer.id, from_unit='stuks',
                                            to_unit='teen', factor=8.0))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    convs = IngredientUnitConversion.query.filter_by(ingredient_id=winnaar.id).all()
    assert len(convs) == 1
    assert convs[0].factor == 12.0            # die van de winnaar


def test_samenvoegen_neemt_de_ah_koppeling_over_als_de_winnaar_er_geen_heeft(app):
    winnaar = _ing('avocado')
    verliezer = _ing('eetrijpe avocado', ah_product_id=129400,
                     ah_product_name='AH Avocado', ah_pkg_qty=1.0, ah_pkg_unit='stuks')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert winnaar.ah_product_id == 129400
    assert winnaar.ah_pkg_qty == 1.0


def test_samenvoegen_laat_de_ah_koppeling_van_de_winnaar_staan(app):
    winnaar = _ing('yoghurt', ah_product_id=60746, ah_product_name='AH Yoghurt')
    verliezer = _ing('magere yoghurt', ah_product_id=99999, ah_product_name='Iets anders')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert winnaar.ah_product_id == 60746
    assert winnaar.ah_product_name == 'AH Yoghurt'


def test_samenvoegen_weigert_een_onbekend_ingredient_en_laat_niets_half_achter(app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', verliezer, 3)
    db.session.commit()

    payload, code = voeg_samen(verliezer.id, 999999)

    assert code == 404
    assert Ingredient.query.get(verliezer.id) is not None
    assert RecipeIngredient.query.filter_by(ingredient_id=verliezer.id).count() == 1


def test_samenvoegen_weigert_zichzelf(app):
    winnaar, _ = _knoflookpaar()
    payload, code = voeg_samen(winnaar.id, winnaar.id)
    assert code == 400


# ── de alias die het probleem bij de bron dichtzet ───────────────────────

def test_de_naam_van_de_verliezer_wordt_een_alias_van_de_winnaar(app):
    winnaar, verliezer = _knoflookpaar()
    voeg_samen(verliezer.id, winnaar.id)

    gevonden = _resolve_or_create_ingredient('Knoflookteen')

    assert gevonden.id == winnaar.id
    assert Ingredient.query.filter_by(name='knoflookteen').first() is None


# ── kandidatenlijst ──────────────────────────────────────────────────────

def test_kandidaten_vinden_knoflook_en_knoflookteen_via_het_ah_product(app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', winnaar, 3)
    db.session.commit()

    paren = samenvoeg_kandidaten()

    knoflook = [p for p in paren if p['reden'] == 'ah']
    assert len(knoflook) == 1
    namen = [i['naam'] for i in knoflook[0]['ingredienten']]
    assert namen == ['Knoflook', 'Knoflookteen']       # meeste recepten voorop
    assert '4160' in knoflook[0]['bewijs']


def test_kandidaat_draagt_genoeg_bewijs_om_zonder_database_te_kiezen(app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', winnaar, 3)
    db.session.add(PantryIngredient(ingredient_id=verliezer.id))
    db.session.commit()

    paar = samenvoeg_kandidaten()[0]
    eerste, tweede = paar['ingredienten']

    assert eerste['recepten'] == 1 and tweede['recepten'] == 0
    assert eerste['preferred_unit'] == 'teen'
    assert eerste['conversies'] and 'teen' in eerste['conversies'][0]
    assert tweede['conversies'] == []
    assert tweede['in_voorraad'] is True and eerste['in_voorraad'] is False


def test_kandidaten_vinden_dezelfde_naam_met_andere_spatiering(app):
    _ing('rode wijnazijn', category='Oliën, Sauzen & Smaakmakers')
    _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    db.session.commit()

    redenen = {p['reden'] for p in samenvoeg_kandidaten()}
    assert 'schrijfwijze' in redenen


def test_kandidaten_vinden_een_meervoud(app):
    _ing('limoen')
    _ing('limoenen')
    db.session.commit()

    redenen = {p['reden'] for p in samenvoeg_kandidaten()}
    assert 'meervoud' in redenen


def test_kandidaten_laten_witte_en_zwarte_bonen_met_rust(app):
    _ing('witte bonen', category='Conserven & Peulvruchten')
    _ing('zwarte bonen', category='Conserven & Peulvruchten')
    db.session.commit()

    assert samenvoeg_kandidaten() == []


def test_een_apart_gemarkeerd_paar_komt_niet_meer_terug(app):
    winnaar, verliezer = _knoflookpaar()
    assert len(samenvoeg_kandidaten()) == 1

    markeer_paar_apart(winnaar.id, verliezer.id)

    assert samenvoeg_kandidaten() == []


# ── het echte doel: één regel op de boodschappenlijst ────────────────────

def _week_van(vandaag):
    iso = vandaag.isocalendar()
    return iso[0], iso[1]


def _twee_recepten_in_het_menu(winnaar, verliezer):
    r1 = _recept('Pasta aglio', winnaar, 2)
    r2 = _recept('Soep', verliezer, 2)
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r1.id,
                            week_number=week, year=jaar))
    db.session.add(MenuItem(day_of_week=1, meal_type='avond', recipe_id=r2.id,
                            week_number=week, year=jaar))
    db.session.commit()


def test_boodschappenlijst_geeft_na_samenvoegen_een_regel_in_plaats_van_twee(app):
    """De koppeling zoals hij nu in data/weekmenu.db staat, zonder omrekening."""
    winnaar, verliezer = _knoflookpaar()
    _twee_recepten_in_het_menu(winnaar, verliezer)

    voor = build_combined_shopping_list(today=VANDAAG)['open']
    assert len([r for r in voor if 'noflook' in r['name']]) == 2

    voeg_samen(verliezer.id, winnaar.id)

    na = [r for r in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in r['name']]
    assert len(na) == 1
    assert na[0]['amount'] == 4                            # 2 + 2 tenen
    assert na[0]['name'] == 'Knoflook'


def test_een_verpakkingsberekening_in_plaats_van_twee(app):
    """Met de omrekening erbij (12 tenen per bolletje, 2 bolletjes per zakje).

    Twee losse rijen ronden allebei apart naar boven af: 1 + 1 zakje voor vier
    tenen. Samengevoegd wordt er één keer afgerond, en dat is één zakje.
    """
    winnaar, verliezer = _knoflookpaar()
    for ing in (winnaar, verliezer):
        ing.ah_conv_factor, ing.ah_conv_unit = 12.0, 'teen'
    _twee_recepten_in_het_menu(winnaar, verliezer)

    voor = build_combined_shopping_list(today=VANDAAG)['open']
    assert sum(r['qty'] for r in voor if 'noflook' in r['name']) == 2

    voeg_samen(verliezer.id, winnaar.id)

    na = [r for r in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in r['name']]
    assert len(na) == 1
    assert na[0]['qty'] == 1


# ── dezelfde eenheid, twee betekenissen ──────────────────────────────────
#
# Dit is de echte situatie in data/weekmenu.db: ingredient 24 (Knoflook) weet
# dat 1 stuks twaalf tenen is, ingredient 146 (Knoflookteen) weet dat niet en
# heeft drie receptregels in 'stuks' waar 'stuks' gewoon 'teen' betekent.
# Verhuist zo'n regel alleen op ingredient_id, dan valt hij onder de conversie
# van de winnaar en wordt 2 opeens 2 × 12 = 24.

def test_stuks_bij_de_verliezer_wordt_niet_ineens_een_bolletje(app):
    winnaar, verliezer = _knoflookpaar()      # winnaar: 1 stuks = 12 teen
    r = _recept('Soep', verliezer, 2, eenheid='stuks')   # bij hem: 1 stuks = 1 teen
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2, 'teen')


def test_de_lijst_telt_vier_tenen_en_niet_zesentwintig(app):
    """Gemeten op data/weekmenu.db: recept 61 (2 stuks) + recept 33 (2 teen)."""
    winnaar, verliezer = _knoflookpaar()
    r1 = _recept('Pasta aglio', winnaar, 2)                  # 2 teen
    r2 = _recept('Soep', verliezer, 2, eenheid='stuks')      # ook 2 tenen
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r1.id,
                            week_number=week, year=jaar))
    db.session.add(MenuItem(day_of_week=1, meal_type='avond', recipe_id=r2.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    na = [r for r in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in r['name']]
    assert len(na) == 1
    assert (na[0]['amount'], na[0]['unit']) == (4, 'teen')


def test_andersom_gaat_het_net_zo_goed(app):
    """De kant zónder conversie wint. De conversie verhuist dan mee, en mag de
    regels van de winnaar niet alsnog maal twaalf doen."""
    kant_met, kant_zonder = _knoflookpaar()
    bol = _recept('Aioli', kant_met, 1, eenheid='stuks')       # 1 bolletje = 12 teen
    teen = _recept('Soep', kant_zonder, 2, eenheid='stuks')    # 2 tenen
    jaar, week = _week_van(VANDAAG)
    for dag, r in ((0, bol), (1, teen)):
        db.session.add(MenuItem(day_of_week=dag, meal_type='avond', recipe_id=r.id,
                                week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(kant_met.id, kant_zonder.id)

    # De regel van de winnaar telde in tenen en houdt dat, ook nu de conversie
    # van de verliezer op zijn ingredient staat.
    teenregel = RecipeIngredient.query.filter_by(recipe_id=teen.id).one()
    assert (teenregel.amount, teenregel.unit) == (2, 'teen')

    na = [r for r in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in r['name']]
    assert len(na) == 1
    assert (na[0]['amount'], na[0]['unit']) == (14, 'teen')     # 12 + 2


def test_een_handmatige_regel_van_de_verliezer_houdt_ook_zijn_betekenis(app):
    winnaar, verliezer = _knoflookpaar()
    jaar, week = _week_van(VANDAAG)
    db.session.add(CustomShoppingIngredient(year=jaar, week_number=week,
                                            ingredient_id=verliezer.id,
                                            amount=3, unit='stuks'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    rij = CustomShoppingIngredient.query.one()
    assert (rij.amount, rij.unit) == (3, 'teen')


def test_een_eenheid_die_allebei_hetzelfde_lezen_blijft_staan(app):
    """Geen conversie in het spel, dus niets om te bevriezen."""
    winnaar = _ing('paprika', preferred_unit='stuks')
    verliezer = _ing('paprika rood', preferred_unit='stuks')
    r = _recept('Wok', verliezer, 2, eenheid='stuks')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2, 'stuks')


# Zonder preferred_unit had de bevriezing niets om op terug te vallen: de oude
# betekenis kwam er dan uit als de oorspronkelijke eenheid, en de bewaking
# eronder sloeg de regel helemaal over. Twee van de 23 kaarten hebben nu al een
# kant zonder preferred_unit (ah-84-231 en meervoud-54-301), en de ronde die
# per ingredient gaat omrekenen zet er conversies op.

def test_zonder_voorkeurseenheid_blijft_de_betekenis_ook_staan(app):
    """De verliezer weet niet waarin hij telt, de winnaar leest stuks als 12 teen."""
    winnaar = _ing('knoflook', display_name='Knoflook', preferred_unit='teen')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='stuks',
                                            to_unit='teen', factor=12.0))
    verliezer = _ing('knoflookteen', display_name='Knoflookteen')   # preferred_unit NULL
    r = _recept('Soep', verliezer, 2, eenheid='stuks')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2, 'teen')


def test_zonder_voorkeurseenheid_telt_de_lijst_twee_tenen_en_niet_vierentwintig(app):
    winnaar = _ing('knoflook', display_name='Knoflook', preferred_unit='teen')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='stuks',
                                            to_unit='teen', factor=12.0))
    verliezer = _ing('knoflookteen', display_name='Knoflookteen')
    r = _recept('Soep', verliezer, 2, eenheid='stuks')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in x['name']]
    assert len(na) == 1
    assert (na[0]['amount'], na[0]['unit']) == (2, 'teen')


def test_zonder_voorkeurseenheid_gaat_het_andersom_net_zo(app):
    """Nu is het de winnaar die niet weet waarin hij telt; de conversie van de
    verliezer verhuist mee en mag zijn regels niet alsnog maal twaalf doen."""
    winnaar = _ing('knoflookteen', display_name='Knoflookteen')     # preferred_unit NULL
    verliezer = _ing('knoflook', display_name='Knoflook', preferred_unit='teen')
    db.session.add(IngredientUnitConversion(ingredient_id=verliezer.id, from_unit='stuks',
                                            to_unit='teen', factor=12.0))
    r = _recept('Soep', winnaar, 2, eenheid='stuks')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2, 'teen')

    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'noflook' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (2, 'teen')


# Kilo's naar grammen en deciliters naar milliliters is geen weten van dít
# ingredient maar gewone maatkennis: het staat in de algemene omrekentabel,
# geldt aan beide kanten en houdt de hoeveelheid gelijk. Alleen de eigen
# omrekening van een ingredient kan een regel van betekenis laten veranderen,
# en alleen daarop hoort de bevriezing te kijken.

def test_kilos_worden_niet_bevroren_tot_grammen(app):
    """Gemeten op een kopie van data/weekmenu.db, kaart meervoud-198-237:
    'Kruimige aardappel' telt in kg, 'kruimige aardappelen' in g. Van 1,2 kg
    mag nooit 1,2 g worden."""
    winnaar = _ing('kruimige aardappelen', display_name='Kruimige aardappelen',
                   preferred_unit='g')
    verliezer = _ing('kruimige aardappel', display_name='Kruimige aardappel',
                     preferred_unit='kg')
    r = _recept('Stamppot', verliezer, 1.2, eenheid='kg')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (1.2, 'kg')
    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'ardappel' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (1200, 'g')


# Dezelfde maatkennis kan ook als eigen rij bij het ingredient staan.
# scripts/normalize_units.py --interactive zet ze zo neer: hij vult de factor
# voor met UNIT_CONVERSIONS.get((other, choice)), dus kg naar g maal duizend
# met één enter. Zo'n rij zegt over de aardappel niets wat de meetlat niet ook
# zegt, en mag dus niets in beweging zetten.

def test_een_eigen_omrekening_die_de_meetlat_herhaalt_bevriest_niets(app):
    winnaar = _ing('kruimige aardappelen', display_name='Kruimige aardappelen',
                   preferred_unit='g')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='kg',
                                            to_unit='g', factor=1000.0))
    verliezer = _ing('kruimige aardappel', display_name='Kruimige aardappel',
                     preferred_unit='kg')
    r = _recept('Stamppot', verliezer, 1.2, eenheid='kg')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    uitkomst = voeg_samen(verliezer.id, winnaar.id)[0]

    assert uitkomst['omgerekend'] == []
    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (1.2, 'kg')
    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'ardappel' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (1200, 'g')


def test_de_meetlat_herhalen_hangt_niet_aan_een_voorkeurseenheid(app):
    """Dezelfde rij, maar nu weet geen van beide kanten waarin hij telt. Of een
    rij alleen de meetlat herhaalt hangt van die rij af, niet van waar het
    ingredient toevallig in telt."""
    winnaar = _ing('kruimige aardappelen', display_name='Kruimige aardappelen')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='kg',
                                            to_unit='g', factor=1000.0))
    verliezer = _ing('kruimige aardappel', display_name='Kruimige aardappel')
    r = _recept('Stamppot', verliezer, 1.2, eenheid='kg')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (1.2, 'kg')
    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'ardappel' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (1200, 'g')


def test_een_eigen_omrekening_die_de_meetlat_herhaalt_geeft_geen_waarschuwing(app):
    """De waarschuwing vooraf hoort over precies dezelfde rijen te gaan als de
    bevriezing erna: rekent zo'n rij alleen maten om, dan valt er niets te
    melden."""
    a = _ing('kruimige aardappelen', display_name='Kruimige aardappelen',
             preferred_unit='g')
    db.session.add(IngredientUnitConversion(ingredient_id=a.id, from_unit='kg',
                                            to_unit='g', factor=1000.0))
    b = _ing('kruimige aardappel', display_name='Kruimige aardappel',
             preferred_unit='kg')
    _recept('Stamppot', b, 1.2, eenheid='kg')
    db.session.commit()

    paar = [p for p in samenvoeg_kandidaten()
            if {i['naam'] for i in p['ingredienten']}
            == {'Kruimige aardappelen', 'Kruimige aardappel'}][0]
    assert paar['eenheidsbotsing'] == []


def test_deciliters_worden_niet_bevroren_tot_eetlepels(app):
    """Gemeten op een kopie van data/weekmenu.db, kaart ah-21-336: 'Yoghurt'
    telt in ml en 'magere yoghurt' in el. Een regel van 2,5 dl werd 2,5 el —
    ruim twee deciliter weg — terwijl er aan geen van beide kanten een eigen
    omrekening staat."""
    winnaar = _ing('yoghurt', display_name='Yoghurt', preferred_unit='ml',
                   category='Zuivel, Eieren & Boter')
    verliezer = _ing('magere yoghurt', display_name='magere yoghurt',
                     preferred_unit='el', category='Zuivel, Eieren & Boter')
    r = _recept('Smoothie', verliezer, 2.5, eenheid='dl')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2.5, 'dl')
    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'oghurt' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (250, 'ml')


def test_zonder_enige_voorkeurseenheid_wijst_de_omrekening_de_eenheid_aan(app):
    """Weet geen van beide kanten waarin hij telt, dan blijft de eenheid over
    waar de botsende omrekening naartoe wijst."""
    winnaar = _ing('knoflook', display_name='Knoflook')          # preferred_unit NULL
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='stuks',
                                            to_unit='teen', factor=12.0))
    verliezer = _ing('knoflookteen', display_name='Knoflookteen')  # ook NULL
    r = _recept('Soep', verliezer, 2, eenheid='stuks')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (2, 'teen')


def test_een_omrekening_vanuit_de_teleenheid_zelf_laat_de_regel_staan(app):
    """Rekent het samengevoegde ingredient zijn eigen teleenheid om — hier
    'stuks' naar gram — dan is er geen eenheid meer die hij met rust laat, en
    is zijn omrekening het enige wat er over 'stuks' bekend is. Eén op één
    omzetten zou van 1 sjalot 1 gram maken; de regel blijft dus staan en telt
    net als de regels van de winnaar zelf voor 40 g."""
    winnaar = _ing('sjalot', display_name='Sjalot', preferred_unit='stuks')
    db.session.add(IngredientUnitConversion(ingredient_id=winnaar.id, from_unit='stuks',
                                            to_unit='g', factor=40.0))
    verliezer = _ing('sjalotje', display_name='Sjalotje')        # preferred_unit NULL
    r = _recept('Stoof', verliezer, 1, eenheid='stuks')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    regel = RecipeIngredient.query.filter_by(recipe_id=r.id).one()
    assert (regel.amount, regel.unit) == (1, 'stuks')
    na = [x for x in build_combined_shopping_list(today=VANDAAG)['open']
          if 'jalot' in x['name']]
    assert (na[0]['amount'], na[0]['unit']) == (40, 'g')


def test_de_kandidaat_waarschuwt_voor_de_botsende_eenheid(app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Soep', verliezer, 2, eenheid='stuks')
    db.session.commit()

    paar = samenvoeg_kandidaten()[0]

    assert paar['eenheidsbotsing']
    tekst = ' '.join(paar['eenheidsbotsing'])
    assert 'stuks' in tekst and '12 teen' in tekst


def test_zonder_omrekening_geen_waarschuwing(app):
    """Geen van beide kanten kent een omrekening, dus valt er niets te botsen."""
    _ing('limoen', preferred_unit='stuks')
    _ing('limoenen', preferred_unit='stuks')
    db.session.commit()

    assert samenvoeg_kandidaten()[0]['eenheidsbotsing'] == []


def test_een_botsing_die_in_geen_enkele_regel_staat_geeft_geen_waarschuwing(app):
    """De filter op eenheden die echt gebruikt worden.

    'stuks' lezen deze twee verschillend — de winnaar als twaalf tenen, de
    verliezer als één — maar geen enkele regel telt in stuks, dus is er niets
    om voor te waarschuwen. Op die filter rust dat er op data/weekmenu.db maar
    één van de 23 kaarten een waarschuwing draagt; zonder hem gaat hij over
    botsingen die niemand tegenkomt, en leer je hem wegkijken.
    """
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', winnaar, 3, eenheid='teen')
    _recept('Soep', verliezer, 2, eenheid='teen')
    db.session.commit()

    assert samenvoeg_kandidaten()[0]['eenheidsbotsing'] == []


def test_het_scherm_toont_de_waarschuwing_voor_je_klikt(client, app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Soep', verliezer, 2, eenheid='stuks')
    db.session.commit()

    body = client.get('/twijfelgevallen').get_data(as_text=True)

    assert 'betekent niet hetzelfde' in body


# ── weekbesluiten gaan over een regel, niet over een ingredient ──────────

def test_een_uitsluiting_van_de_verliezer_haalt_de_regel_van_de_winnaar_niet_weg(app):
    """Gemeten op data/weekmenu.db: 'Lente-Ui, 1 bosje' verdween uit week 2026-37
    doordat de uitsluiting van 'Bosui' op Lente-Ui landde."""
    winnaar = _ing('lente-ui', display_name='Lente-Ui', preferred_unit='stuks')
    verliezer = _ing('bosui', display_name='Bosui', preferred_unit='stuks')
    r = _recept('Wok', winnaar, 1, eenheid='bosje')
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.add(ShoppingListExclusion(year=jaar, week_number=week,
                                         ingredient_id=verliezer.id))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    namen = [x['name'] for x in build_combined_shopping_list(today=VANDAAG)['open']]
    assert 'Lente-Ui' in namen
    assert ShoppingListExclusion.query.count() == 0


def test_een_override_van_de_verliezer_verhuist_niet(app):
    winnaar, verliezer = _knoflookpaar()
    jaar, week = _week_van(VANDAAG)
    db.session.add(ShoppingListOverride(year=jaar, week_number=week,
                                        ingredient_id=verliezer.id, qty=9))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingListOverride.query.count() == 0


def test_een_afvinkje_van_de_verliezer_verdwijnt_met_zijn_regel(app):
    winnaar, verliezer = _knoflookpaar()
    jaar, week = _week_van(VANDAAG)
    db.session.add(ShoppingCheck(year=jaar, week_number=week,
                                 ingredient_id=verliezer.id))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingCheck.query.count() == 0


def test_afvinkjes_aan_beide_kanten_blijven_er_een(app):
    """Allebei in de kar gelegd: het vinkje dekt de samengevoegde regel nog."""
    winnaar, verliezer = _knoflookpaar()
    _twee_recepten_in_het_menu(winnaar, verliezer)
    jaar, week = _week_van(VANDAAG)
    for ing in (winnaar, verliezer):
        db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=ing.id))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    rijen = ShoppingCheck.query.all()
    assert len(rijen) == 1 and rijen[0].ingredient_id == winnaar.id


def test_het_vinkje_van_de_winnaar_vervalt_als_de_verliezer_nog_open_stond(app):
    """De regel wordt groter dan wat je afvinkte; dan mag hij niet verdwijnen."""
    winnaar, verliezer = _knoflookpaar()
    _twee_recepten_in_het_menu(winnaar, verliezer)
    jaar, week = _week_van(VANDAAG)
    db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=winnaar.id))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingCheck.query.count() == 0
    namen = [x['name'] for x in build_combined_shopping_list(today=VANDAAG)['open']]
    assert 'Knoflook' in namen


def test_het_vinkje_van_de_winnaar_blijft_in_een_week_zonder_de_verliezer(app):
    winnaar, verliezer = _knoflookpaar()
    r = _recept('Pasta aglio', winnaar, 2)
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=r.id,
                            week_number=week, year=jaar))
    db.session.add(ShoppingCheck(year=jaar, week_number=week, ingredient_id=winnaar.id))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert ShoppingCheck.query.count() == 1


# ── de voorraadkast gaat over één schrijfwijze ───────────────────────────
#
# Gemeten op data/weekmenu.db: van de 23 kaarten hebben er twee precies één
# voorraadkant — [141, 181] rodewijnazijn + rode wijnazijn (141 staat in de
# kast) en [196, 427] Kippen bouillonblokje + Kippenbouillonblokje (427 staat
# erin). Verhuisde die rij mee naar de winnaar, dan gold het samengevoegde
# ingredient als 'heb ik in huis' en verdween het uit elke boodschappenlijst.

def _azijnpaar():
    kast = _ing('rodewijnazijn', display_name='Rodewijnazijn',
                category='Oliën, Sauzen & Smaakmakers', preferred_unit='el')
    los = _ing('rode wijnazijn', display_name='Rode wijnazijn',
               category='Oliën, Sauzen & Smaakmakers', preferred_unit='el')
    db.session.commit()
    return kast, los


def _in_het_menu(recept):
    jaar, week = _week_van(VANDAAG)
    db.session.add(MenuItem(day_of_week=0, meal_type='avond', recipe_id=recept.id,
                            week_number=week, year=jaar))
    db.session.commit()


def test_de_voorraadrij_van_de_verliezer_verhuist_niet_mee(app):
    kast, los = _azijnpaar()
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    _in_het_menu(_recept('Dressing', los, 1, eenheid='el'))

    voeg_samen(kast.id, los.id)

    assert PantryIngredient.query.count() == 0
    namen = [x['name'] for x in build_combined_shopping_list(today=VANDAAG)['open']]
    assert 'Rode wijnazijn' in namen


def test_de_voorraadrij_van_de_winnaar_blijft_wel_staan(app):
    """Die gaat over de naam die blijft; daar verandert het samenvoegen niets aan."""
    kast, los = _azijnpaar()
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    _in_het_menu(_recept('Dressing', los, 1, eenheid='el'))

    voeg_samen(los.id, kast.id)

    rijen = PantryIngredient.query.all()
    assert len(rijen) == 1 and rijen[0].ingredient_id == kast.id
    namen = [x['name'] for x in build_combined_shopping_list(today=VANDAAG)['open']]
    assert 'Rodewijnazijn' not in namen


def test_de_kandidaat_meldt_dat_maar_een_kant_in_de_voorraadkast_staat(app):
    kast, los = _azijnpaar()
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    db.session.commit()

    paar = samenvoeg_kandidaten()[0]

    assert 'Rodewijnazijn' in paar['voorraadverschil']
    assert 'Rode wijnazijn' in paar['voorraadverschil']


def test_zonder_verschil_in_de_voorraadkast_geen_melding(app):
    kast, los = _azijnpaar()
    for ing in (kast, los):
        db.session.add(PantryIngredient(ingredient_id=ing.id))
    db.session.commit()

    assert samenvoeg_kandidaten()[0]['voorraadverschil'] == ''


def test_het_scherm_meldt_het_voorraadverschil_voor_je_klikt(client, app):
    kast, los = _azijnpaar()
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    db.session.commit()

    body = client.get('/twijfelgevallen').get_data(as_text=True)

    assert 'staat in de voorraadkast' in body


# ── 'Niet vragen' gaat over het product, dus verhuist het mee ────────────

def _knoflook_met_overslaan():
    """Het knoflookpaar waarbij 'teen' bij de verliezer is weggeklikt."""
    winnaar, verliezer = _knoflookpaar()
    db.session.add(MaatOverslaan(ingredient_id=verliezer.id, eenheid='teen'))
    db.session.commit()
    return winnaar, verliezer


def test_niet_vragen_verhuist_naar_de_winnaar(app):
    winnaar, verliezer = _knoflook_met_overslaan()

    voeg_samen(verliezer.id, winnaar.id)

    rijen = [(r.ingredient_id, r.eenheid) for r in MaatOverslaan.query.all()]
    assert rijen == [(winnaar.id, 'teen')]


def test_niet_vragen_aan_beide_kanten_blijft_een_rij(app):
    winnaar, verliezer = _knoflook_met_overslaan()
    db.session.add(MaatOverslaan(ingredient_id=winnaar.id, eenheid='teen'))
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    rijen = [(r.ingredient_id, r.eenheid) for r in MaatOverslaan.query.all()]
    assert rijen == [(winnaar.id, 'teen')]


def test_de_weggeklikte_vraag_komt_niet_terug_op_de_winnaar(app):
    """Het scherm mag na de samenvoeging niet opnieuw beginnen te vragen."""
    from weekmenu.services.verpakking import verpakkingskandidaten

    winnaar, verliezer = _knoflook_met_overslaan()
    _recept('Soep', verliezer, 5, eenheid='teen')
    db.session.commit()

    voeg_samen(verliezer.id, winnaar.id)

    assert verpakkingskandidaten() == []


def test_een_nieuw_ingredient_erft_het_overslaan_niet(app):
    """SQLite geeft het vrijgekomen id aan de volgende rij.

    De verliezer is meestal juist de nieuwste rij uit een verse import, dus
    zijn id is het hoogste. Blijft er een weesrij achter, dan erft het
    eerstvolgende nieuwe ingredient een besluit over een ander product.
    """
    winnaar, verliezer = _knoflook_met_overslaan()
    weg = verliezer.id
    assert weg > winnaar.id

    voeg_samen(verliezer.id, winnaar.id)

    nieuw = _ing('papadum', category='Overig')
    db.session.commit()
    assert nieuw.id == weg                       # het id is hergebruikt
    assert MaatOverslaan.query.filter_by(ingredient_id=nieuw.id).count() == 0


# ── 'Toch apart' echt onthouden ──────────────────────────────────────────

def test_toch_apart_zet_de_vraag_uit(app):
    from weekmenu.services.pantry import annotate_pantry_status

    kast = _ing('rodewijnazijn', display_name='Rodewijnazijn',
                category='Oliën, Sauzen & Smaakmakers')
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    db.session.commit()

    rij = annotate_pantry_status([{'name': 'rode wijnazijn', 'amount': 1, 'unit': 'el',
                                   'category': 'Oliën, Sauzen & Smaakmakers'}])[0]
    assert rij['pantry_hint'] == 'variant'

    markeer_apart('rode wijnazijn', kast.id)

    rij = annotate_pantry_status([{'name': 'rode wijnazijn', 'amount': 1, 'unit': 'el',
                                   'category': 'Oliën, Sauzen & Smaakmakers'}])[0]
    assert rij['pantry_hint'] != 'variant'
    assert rij['variant_of'] is None


def test_toch_apart_werkt_ook_op_een_bestaande_receptregel(app):
    from weekmenu.services.pantry import hints_for_recipe_rows

    kast = _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    los = _ing('rode wijnazijn', category='Oliën, Sauzen & Smaakmakers')
    db.session.add(PantryIngredient(ingredient_id=kast.id))
    r = _recept('Dressing', los, 1, eenheid='el')
    db.session.commit()

    hints = hints_for_recipe_rows(r.ingredients)
    assert list(hints.values())[0]['hint'] == 'variant'

    markeer_apart('rode wijnazijn', kast.id)

    hints = hints_for_recipe_rows(r.ingredients)
    assert list(hints.values())[0]['hint'] != 'variant'


def test_zelfde_product_legt_de_spelling_vast_als_alias(app):
    kast = _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    db.session.commit()

    payload, code = koppel_alias('Rode wijnazijn', kast.id)

    assert code == 200
    assert payload['samengevoegd'] is False
    assert _resolve_or_create_ingredient('rode wijnazijn').id == kast.id


def test_zelfde_product_voegt_samen_als_de_spelling_al_een_eigen_rij_is(app):
    kast = _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    los = _ing('rode wijnazijn', category='Oliën, Sauzen & Smaakmakers')
    _recept('Dressing', los, 1, eenheid='el')
    db.session.commit()
    los_id = los.id

    payload, code = koppel_alias('rode wijnazijn', kast.id)

    assert code == 200
    assert payload['samengevoegd'] is True
    assert Ingredient.query.get(los_id) is None
    assert RecipeIngredient.query.filter_by(ingredient_id=kast.id).count() == 1


# ── scherm en endpoints ──────────────────────────────────────────────────

def test_twijfelgevallen_toont_het_paar_met_wat_er_gebeurt(client, app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Pasta aglio', winnaar, 3)
    db.session.commit()

    body = client.get('/twijfelgevallen').get_data(as_text=True)

    assert 'Knoflookteen' in body
    assert 'Dubbele ingrediënten' in body
    assert 'wordt een alias' in body


def test_endpoint_voegt_samen(client, app):
    winnaar, verliezer = _knoflookpaar()
    _recept('Soep', verliezer, 2)
    db.session.commit()
    verliezer_id = verliezer.id

    resp = client.post('/api/ingredienten/samenvoegen',
                       json={'winnaar_id': winnaar.id, 'verliezer_id': verliezer_id})

    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'
    assert Ingredient.query.get(verliezer_id) is None


def test_endpoint_slaat_een_paar_over(client, app):
    winnaar, verliezer = _knoflookpaar()

    resp = client.post('/api/ingredienten/apart',
                       json={'ingredient_id': winnaar.id, 'ander_id': verliezer.id})

    assert resp.status_code == 200
    assert VariantApart.query.count() == 2      # beide richtingen
    assert samenvoeg_kandidaten() == []


def test_endpoint_onthoudt_een_getypte_spelling_als_apart(client, app):
    kast = _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    db.session.commit()

    resp = client.post('/api/ingredienten/apart',
                       json={'ingredient_id': kast.id, 'naam': 'rode wijnazijn'})

    assert resp.status_code == 200
    assert VariantApart.query.count() == 1


def test_endpoint_legt_zelfde_product_vast(client, app):
    kast = _ing('rodewijnazijn', category='Oliën, Sauzen & Smaakmakers')
    db.session.commit()

    resp = client.post('/api/ingredienten/alias',
                       json={'ingredient_id': kast.id, 'naam': 'rode wijnazijn'})

    assert resp.status_code == 200
    assert IngredientAlias.query.filter_by(alias='rode wijnazijn').first().ingredient_id == kast.id


def test_ah_scherm_wijst_naar_de_dubbelen(client, app):
    _knoflookpaar()

    body = client.get('/ah-producten').get_data(as_text=True)

    assert 'Nakijken' in body
    assert '#dubbel' in body
