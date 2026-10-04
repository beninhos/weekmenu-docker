"""Afgevinkt blijft afgevinkt; toevoegen zet alleen het nieuwe op de lijst.

Rutger, 4 okt 2026: 'Ik wil als ik iets afvink, dat het is afgevinkt. Voeg ik
iets opnieuw toe, moet dat geen impact hebben op wat ik eerder heb gedaan.'
Een vinkje en een kruisje leggen daarom een hoeveelheid vast, geen status.
"""
from datetime import date, datetime

from weekmenu.extensions import db
from weekmenu.models import (
    CustomShoppingIngredient, Ingredient, MenuItem, QuickAddItem, Recipe,
    RecipeIngredient, ShoppingCheck, ShoppingListExclusion,
)
from weekmenu.services import afgehandeld
from weekmenu.services.shopping import build_combined_shopping_list, lopende_weken

JAAR, WEEK = date.today().isocalendar()[0], date.today().isocalendar()[1]


def _ing(naam):
    ing = Ingredient.query.filter_by(name=naam).first()
    if not ing:
        ing = Ingredient(name=naam, display_name=naam, category='overig')
        db.session.add(ing)
        db.session.flush()
    return ing


def _recept(naam, regels, serves=2):
    r = Recipe(name=naam, serves=serves)
    db.session.add(r)
    db.session.flush()
    for ing_naam, hoeveel, eenheid in regels:
        db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=_ing(ing_naam).id,
                                        amount=hoeveel, unit=eenheid))
    db.session.commit()
    return r


def _plan(r, personen, dag=1, jaar=JAAR, week=WEEK):
    db.session.add(MenuItem(day_of_week=dag, meal_type='diner', recipe_id=r.id,
                            people_count=personen, week_number=week, year=jaar))
    db.session.commit()


def _open(naam):
    ing = _ing(naam)
    return sum(x['amount'] for x in build_combined_shopping_list()['open']
               if x['ingredient_id'] == ing.id)


def _chili():
    return _recept('Chili', [('kidneybonen', 1, 'blik'), ('rundergehakt', 200, 'g')])


# ── De opslag: per week per ingredient een hoeveelheid per eenheid ────────

def test_afvinken_telt_hoeveelheden_per_eenheid_op(app):
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    afgehandeld.vink_af(2026, 40, 7, {'blik': 6, 'g': 50})
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) == {'blik': 7, 'g': 50}


def test_een_rij_zonder_getal_betekent_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES
    assert afgehandeld.lees(None) == {}


def test_afvinken_bovenop_alles_blijft_alles(app):
    db.session.add(ShoppingCheck(year=2026, week_number=40, ingredient_id=7))
    db.session.commit()
    afgehandeld.vink_af(2026, 40, 7, {'blik': 1})
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES


def test_weghalen_zet_de_datum_voor_het_afgevinkt_blok(app):
    afgehandeld.haal_weg(2026, 40, 2, {'g': 200})
    db.session.commit()
    rij = ShoppingListExclusion.query.one()
    assert afgehandeld.lees(rij) == {'g': 200}
    assert rij.weggehaald_op is not None


def test_afsluiten_dateert_een_nieuw_vinkje_op_de_maandag_van_die_week(app):
    afgehandeld.sluit_af(2026, 32, 7)
    db.session.commit()
    rij = ShoppingCheck.query.one()
    assert afgehandeld.lees(rij) is afgehandeld.ALLES
    assert rij.checked_at.date() == date.fromisocalendar(2026, 32, 1)


def test_meegroeien_naar_rato_van_wat_al_afgehandeld_was(app):
    # Chili-week: nodig 7 blik, 1 gekocht; recept +50% geeft 3,5 extra.
    afgehandeld.vink_af(2026, 40, 158, {'blik': 1})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 158, 'blik', extra=3.5, nodig_oud=7)
    assert afgehandeld.lees(ShoppingCheck.query.one()) == {'blik': 1.5}


def test_meegroeien_verdeelt_over_vinkje_en_kruisje_en_nooit_meer_dan_het_extra(app):
    afgehandeld.vink_af(2026, 40, 1, {'g': 600})
    afgehandeld.haal_weg(2026, 40, 1, {'g': 600})
    db.session.commit()
    afgehandeld.groei_mee(2026, 40, 1, 'g', extra=100, nodig_oud=1000)  # 120% afgehandeld
    a = afgehandeld.lees(ShoppingCheck.query.one())['g']
    w = afgehandeld.lees(ShoppingListExclusion.query.one())['g']
    assert round(a + w - 1200, 6) == 100
    assert round(a - w, 6) == 0


# ── De lijst: open = nodig - afgevinkt - weggehaald ──────────────────────

def test_rekenregel_open_is_nodig_min_afgevinkt_min_weggehaald(app):
    r = _chili()
    _plan(r, 2)
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.haal_weg(JAAR, WEEK, _ing('rundergehakt').id, {'g': 200})
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=12, year=JAAR, week_number=WEEK))
    db.session.commit()
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_een_eenheid_die_niet_meer_bestaat_verbergt_niets(app):
    ui = _ing('ui')
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=ui.id, amount=2, unit='stuks'))
    db.session.commit()
    afgehandeld.vink_af(JAAR, WEEK, ui.id, {'stuks': 2})
    CustomShoppingIngredient.query.delete()
    db.session.commit()
    _plan(_recept('Soep', [('ui', 100, 'g')], serves=2), 2)
    assert _open('ui') == 100


def test_drie_derden_afvinken_laat_geen_ruis_open(app):
    r = _recept('Taart', [('bloem', 1, 'kg')], serves=3)
    _plan(r, 3)
    for _ in range(3):
        afgehandeld.vink_af(JAAR, WEEK, _ing('bloem').id, {'kg': 1 / 3})
    db.session.commit()
    assert not [x for x in build_combined_shopping_list()['open']
                if x['ingredient_id'] == _ing('bloem').id]


def test_een_oude_rij_zonder_getal_dekt_alles_zoals_voorheen(app):
    r = _chili()
    _plan(r, 2)
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK,
                                 ingredient_id=_ing('kidneybonen').id))
    db.session.add(ShoppingListExclusion(year=JAAR, week_number=WEEK,
                                         ingredient_id=_ing('rundergehakt').id))
    db.session.add(CustomShoppingIngredient(year=JAAR, week_number=WEEK,
                                            ingredient_id=_ing('rundergehakt').id,
                                            amount=100, unit='g'))
    db.session.commit()
    assert _open('kidneybonen') == 0
    assert _open('rundergehakt') == 100   # een oud kruisje verborg nooit losse items


def test_afgevinkt_blok_toont_wat_er_de_laatste_14_dagen_afgevinkt_is(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    _plan(r, 14)
    db.session.add(ShoppingCheck(year=2026, week_number=13,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 3, 23, 12)))
    afgehandeld.vink_af(JAAR, WEEK, _ing('kidneybonen').id, {'blik': 7})
    db.session.commit()
    blok = [x for x in build_combined_shopping_list()['checked']
            if x['ingredient_id'] == _ing('kidneybonen').id]
    assert [(x['soort'], x['amount']) for x in blok] == [('afgevinkt', 7)]


def test_een_week_met_alleen_weggehaalde_regels_loopt_niet_meer(app):
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    afgehandeld.haal_weg(2026, 13, _ing('kidneybonen').id, {'blik': 1})
    afgehandeld.vink_af(2026, 13, _ing('rundergehakt').id, {'g': 200})
    db.session.commit()
    assert (2026, 13) not in lopende_weken()


def test_een_ingredient_zonder_hoeveelheid_staat_open_tot_je_het_afvinkt(app):
    # 'Naar smaak' (hoeveelheid 0, zoals de aragilde olie op de live-data) is
    # een herinnering: hij hoort op de lijst tot je hem afvinkt of wegklikt.
    _plan(_recept('Salade', [('olijfolie', 0, '')]), 2)
    olie = _ing('olijfolie').id
    assert [x['amount'] for x in build_combined_shopping_list()['open']
            if x['ingredient_id'] == olie] == [0]
    afgehandeld.vink_af(JAAR, WEEK, olie, {'': 0})
    db.session.commit()
    lijst = build_combined_shopping_list()
    assert not [x for x in lijst['open'] if x['ingredient_id'] == olie]
    assert [(x['soort'], x['amount']) for x in lijst['checked']
            if x['ingredient_id'] == olie] == [('afgevinkt', 0)]


# ── Gebaren op /boodschappen ──────────────────────────────────────────────

def test_afvinken_legt_de_open_hoeveelheid_vast_en_wist_de_aantal_override(app, client):
    from weekmenu.models import ShoppingListOverride
    r = _chili()
    _plan(r, 2)
    kb = _ing('kidneybonen')
    db.session.add(ShoppingListOverride(year=JAAR, week_number=WEEK, ingredient_id=kb.id, qty=3))
    db.session.commit()
    assert client.post(f'/api/boodschappen/item/{kb.id}/check',
                       json={'checked': True}).status_code == 200
    assert afgehandeld.lees(ShoppingCheck.query.filter_by(ingredient_id=kb.id).one()) == {'blik': 1}
    assert ShoppingListOverride.query.count() == 0
    _plan(r, 12, dag=6)
    assert _open('kidneybonen') == 6


def test_weghalen_dekt_ook_een_los_item_zonder_het_te_verwijderen(app, client):
    ui = _ing('ui')
    pad = f'/api/shopping-list/{JAAR}/{WEEK}/add-item'
    client.post(pad, json={'ingredient_id': ui.id, 'amount': 2, 'unit': 'stuks'})
    client.post(f'/api/boodschappen/item/{ui.id}/remove')
    assert _open('ui') == 0
    assert CustomShoppingIngredient.query.count() == 1
    client.post(pad, json={'ingredient_id': ui.id, 'amount': 1, 'unit': 'stuks'})
    assert _open('ui') == 1


def test_vinkje_uitzetten_opent_alleen_de_weken_van_de_laatste_14_dagen(app, client):
    # Op de live-data opende dit week 13, 18 en 33 mee: 9 + 1 blik i.p.v. 7.
    r = _chili()
    _plan(r, 2, week=13, jaar=2026)
    db.session.add(ShoppingCheck(year=2026, week_number=13,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 3, 23, 12)))
    _plan(r, 14)
    kb = _ing('kidneybonen').id
    client.post(f'/api/boodschappen/item/{kb}/check', json={'checked': True})
    assert _open('kidneybonen') == 0
    assert client.post(f'/api/boodschappen/item/{kb}/check',
                       json={'checked': False}).status_code == 200
    assert _open('kidneybonen') == 7


def test_terugzetten_haalt_alleen_het_kruisje_weg(app, client):
    r = _chili()
    _plan(r, 2)
    gehakt = _ing('rundergehakt').id
    client.post(f'/api/boodschappen/item/{gehakt}/remove')
    blok = build_combined_shopping_list()['checked']
    assert [(x['soort'], x['amount']) for x in blok
            if x['ingredient_id'] == gehakt] == [('weggehaald', 200)]
    assert client.post(f'/api/boodschappen/item/{gehakt}/terugzetten').status_code == 200
    assert _open('rundergehakt') == 200
    assert client.post(f'/api/boodschappen/item/{gehakt}/terugzetten').status_code == 404


# ── Toevoegen zet alleen het nieuwe op de lijst ───────────────────────────

def test_chili_week_los_recept_erbij_geeft_alleen_de_nieuwe_hoeveelheid(app, client):
    r = _chili()
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')       # dinsdag gekocht
    assert client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 12}).status_code == 200
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_plannen_met_uitgevinkt_ingredient_haalt_alleen_dat_receptdeel_weg(app):
    from weekmenu.services.menu import plan_recipe
    r = _chili()
    _plan(r, 2)
    andere = [ri.id for ri in r.ingredients if ri.ingredient.name != 'rundergehakt']
    plan_recipe(r.id, 6, 'diner', WEEK, JAAR, 12, andere)
    assert _open('rundergehakt') == 200     # dinsdag nog nodig, zondag 'heb ik al'


def test_personen_erbij_zet_alleen_het_verschil_erop(app, client):
    from weekmenu.services.menu import update_week_menu

    def menu(p):
        return [{'day': 1, 'meals': {'diner': {'recipe_id': r.id, 'people_count': p}}}]

    r = _chili()
    update_week_menu(WEEK, JAAR, menu(2))
    client.post('/api/boodschappen/check-all')
    update_week_menu(WEEK, JAAR, menu(4))
    assert _open('kidneybonen') == 1
    update_week_menu(WEEK, JAAR, menu(2))
    assert _open('kidneybonen') == 0


def test_zelfde_maaltijd_neemt_het_losse_recept_over(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    resp = client.post('/update_menu', json={
        'week': WEEK, 'year': JAAR, 'neem_los_recept_over': [qid],
        'menu': [{'day': 6, 'meals': {'diner': {'recipe_id': r.id, 'people_count': 12}}}]})
    assert resp.status_code == 200
    assert QuickAddItem.query.count() == 0
    assert _open('kidneybonen') == 6


def test_zelfde_maaltijd_via_de_receptenplanner(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    resp = client.post('/api/planner/plan', json={
        'recipe_id': r.id, 'day': 6, 'meal_type': 'diner', 'week': WEEK, 'year': JAAR,
        'people_count': 12, 'ingredient_ids': [ri.id for ri in r.ingredients],
        'neem_los_recept_over': [qid]})
    assert resp.status_code == 200
    assert QuickAddItem.query.count() == 0
    assert _open('kidneybonen') == 6


def test_een_los_recept_uit_een_andere_week_wordt_nooit_overgenomen(app, client):
    r = _chili()
    qi = QuickAddItem(recipe_id=r.id, people_count=12, year=JAAR, week_number=WEEK)
    db.session.add(qi)
    db.session.commit()
    andere_week = WEEK + 1 if WEEK < 52 else 1
    client.post('/update_menu', json={
        'week': andere_week, 'year': JAAR, 'neem_los_recept_over': [qi.id],
        'menu': [{'day': 6, 'meals': {'diner': {'recipe_id': r.id, 'people_count': 12}}}]})
    assert QuickAddItem.query.count() == 1


def test_plus_recept_erbij_maakt_een_tweede_los_recept(app, client):
    r = _chili()
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    client.post('/api/boodschappen/extra',
                json={'recipe_id': r.id, 'people_count': 4, 'erbij': True})
    assert QuickAddItem.query.count() == 2
    assert _open('kidneybonen') == 8


def test_gekocht_blijft_in_huis_als_het_losse_recept_weg_en_terug_komt(app, client):
    r = _chili()
    qid = client.post('/api/boodschappen/extra',
                      json={'recipe_id': r.id, 'people_count': 12}).get_json()['id']
    client.post('/api/boodschappen/check-all')
    client.delete(f'/api/boodschappen/extra/{qid}')
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    assert _open('kidneybonen') == 0


# ── Recept bewerken: gekocht is gekocht ───────────────────────────────────

def _bewerk(client, r, regels):
    return client.post(f'/recipe/{r.id}/edit', data={
        'name': r.name, 'page': '', 'serves': str(r.serves), 'cookbook': '', 'url': '',
        'instructions': '', 'ingredient[]': [n for n, _, _ in regels],
        'ingredient_id[]': ['' for _ in regels], 'amount[]': [str(h) for _, h, _ in regels],
        'unit[]': [u for _, _, u in regels], 'category[]': ['overig' for _ in regels],
        'preparation[]': ['' for _ in regels], 'pantry_flag[]': ['0' for _ in regels]})


def test_meer_van_een_gekocht_ingredient_zet_niets_op_de_lijst(app, client):
    r = _recept('Patatje', [('aardappelen', 1000, 'g')])
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')
    assert _bewerk(client, r, [('aardappelen', 1500, 'g')]).status_code == 302
    assert _open('aardappelen') == 0


def test_half_gekocht_groeit_alleen_het_open_deel_mee(app, client):
    r = _chili()
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')
    _plan(r, 12, dag=6)
    _bewerk(client, r, [('kidneybonen', 1.5, 'blik'), ('rundergehakt', 200, 'g')])
    assert _open('kidneybonen') == 9


def test_een_nieuw_ingredient_verschijnt_ook_als_een_ander_recept_het_al_kocht(app, client):
    soep = _recept('Soep', [('ui', 1, 'stuks')])
    chili = _chili()
    _plan(soep, 2)
    _plan(chili, 2, dag=3)
    client.post('/api/boodschappen/check-all')
    _bewerk(client, chili, [('kidneybonen', 1, 'blik'), ('rundergehakt', 200, 'g'),
                            ('ui', 1, 'stuks')])
    assert _open('ui') == 1


def test_recept_inkorten_zet_niets_terug(app, client):
    r = _chili()
    _plan(r, 2)
    client.post('/api/boodschappen/check-all')
    _bewerk(client, r, [('kidneybonen', 0.5, 'blik'), ('rundergehakt', 200, 'g')])
    assert _open('kidneybonen') == 0 and _open('rundergehakt') == 0


# ── Eenmalig vullen na v23 ────────────────────────────────────────────────

def _vlag():
    from weekmenu.models import Settings
    db.session.add(Settings(key='afgehandeld_vullen', value='1'))
    db.session.commit()


def test_vullen_laat_de_lijst_gelijk_en_toevoegen_zet_daarna_alleen_het_nieuwe_erop(app):
    from weekmenu.models import Settings
    r = _chili()
    _plan(r, 2)
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK,
                                 ingredient_id=_ing('kidneybonen').id))
    db.session.add(ShoppingListExclusion(year=JAAR, week_number=WEEK,
                                         ingredient_id=_ing('rundergehakt').id))
    db.session.commit()
    _vlag()
    voor = build_combined_shopping_list()['open']

    assert afgehandeld.vul_hoeveelheden_aan() == 2

    assert build_combined_shopping_list()['open'] == voor
    assert Settings.query.filter_by(key='afgehandeld_vullen').first() is None
    _plan(r, 12, dag=6)
    assert _open('kidneybonen') == 6
    assert _open('rundergehakt') == 1200


def test_vullen_zonder_vlag_doet_niets(app):
    db.session.add(ShoppingCheck(year=JAAR, week_number=WEEK, ingredient_id=1))
    db.session.commit()
    assert afgehandeld.vul_hoeveelheden_aan() == 0
    assert afgehandeld.lees(ShoppingCheck.query.one()) is afgehandeld.ALLES


def test_een_afgesloten_week_verschijnt_na_vullen_niet_in_het_afgevinkt_blok(app):
    r = _chili()
    _plan(r, 2, week=32, jaar=2026)
    db.session.add(ShoppingCheck(year=2026, week_number=32,
                                 ingredient_id=_ing('kidneybonen').id,
                                 checked_at=datetime(2026, 8, 3, 12)))
    db.session.commit()
    _vlag()
    afgehandeld.vul_hoeveelheden_aan()
    assert not build_combined_shopping_list()['checked']


# ── Het scherm ────────────────────────────────────────────────────────────

def test_de_pagina_geeft_de_losse_recepten_van_die_week_mee(app, client):
    r = _chili()
    client.post('/api/boodschappen/extra', json={'recipe_id': r.id, 'people_count': 12})
    for pad in (f'/week/{JAAR}/{WEEK}', '/boodschappen', '/receptenplanner'):
        html = client.get(pad).get_data(as_text=True)
        assert '"recipe_id": %d' % r.id in html, pad
        assert 'zelfde-maaltijd.js' in html, pad


def test_het_afgevinkt_blok_toont_weggehaald_met_een_terugzetknop(app, client):
    r = _chili()
    _plan(r, 2)
    client.post(f'/api/boodschappen/item/{_ing("rundergehakt").id}/remove')
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'weggehaald</span>' in html and 'terugzetten(%d)' % _ing('rundergehakt').id in html
