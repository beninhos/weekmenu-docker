"""Varianten van hetzelfde product samenvoegen tot één boodschappenregel.

'knoflook' en 'knoflookteen' waren twee ingredientrijen, dus twee regels op de
lijst met elk een eigen verpakkingsberekening: twee bolletjes voor vier tenen.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, IngredientAlias,
    IngredientUnitConversion, MenuItem, PantryIngredient, Recipe,
    RecipeIngredient, ShoppingListOverride, VariantApart,
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
