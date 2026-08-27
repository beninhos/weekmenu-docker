from datetime import date, datetime, timedelta

from weekmenu.extensions import db
from weekmenu.models import (
    Ingredient, MenuItem, QuickAddItem, Recipe, RecipeIngredient,
    ShoppingCheck, CustomShoppingIngredient,
)
from weekmenu.services.shopping import build_combined_shopping_list, window_weeks

TODAY = date(2026, 7, 11)  # zaterdag, ISO-week 28


def _mk_recipe(name, ing_name, amount, unit='g', serves=4):
    ing = Ingredient.query.filter_by(name=ing_name).first()
    if not ing:
        ing = Ingredient(name=ing_name, display_name=ing_name, category='overig')
        db.session.add(ing)
        db.session.flush()
    r = Recipe(name=name, serves=serves)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=amount, unit=unit))
    db.session.flush()
    return r, ing


def _plan(recipe, year, week, day=0):
    db.session.add(MenuItem(day_of_week=day, meal_type='avond',
                            recipe_id=recipe.id, week_number=week, year=year))
    db.session.flush()


def test_window_weeks_covers_prev_to_plus_two(app):
    weeks = window_weeks(today=TODAY)
    assert (2026, 27) in weeks and (2026, 28) in weeks
    assert (2026, 29) in weeks and (2026, 30) in weeks


def test_same_ingredient_two_weeks_merges_and_checks_partially(app):
    r1, ing = _mk_recipe('Dal wk28', 'rode linzen', 200)
    r2, _ = _mk_recipe('Dal wk29', 'rode linzen', 300)
    _plan(r1, 2026, 28)
    _plan(r2, 2026, 29)

    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['name'].lower().startswith('rode linzen')]
    assert len(rows) == 1
    assert rows[0]['amount'] == 500  # 200 + 300 samengevoegd

    # week 28 afvinken → alleen 300 nog open
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert rows[0]['amount'] == 300

    # beide weken afgevinkt → rij naar checked
    db.session.add(ShoppingCheck(year=2026, week_number=29, ingredient_id=ing.id,
                                 via_ah=True))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]
    checked = [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert checked and checked[0]['via_ah'] is True


def test_open_row_includes_recipe_hint(app):
    r1, ing = _mk_recipe('Pasta bolognese', 'gehakt', 300)
    r2, _ = _mk_recipe('Taco maandag', 'gehakt', 200)
    _plan(r1, 2026, 28)
    _plan(r2, 2026, 29)

    result = build_combined_shopping_list(today=TODAY)
    row = next(x for x in result['open'] if x['ingredient_id'] == ing.id)
    assert row['recipes'] == ['Pasta bolognese', 'Taco maandag']


def test_excluded_week_does_not_leak_into_recipe_hint(app):
    from weekmenu.models import ShoppingListExclusion

    r1, ing = _mk_recipe('Soep wk28', 'wortel', 200)
    r2, _ = _mk_recipe('Ander recept wk29', 'wortel', 300)
    _plan(r1, 2026, 28)
    _plan(r2, 2026, 29)
    db.session.add(ShoppingListExclusion(year=2026, week_number=29, ingredient_id=ing.id))
    db.session.commit()

    result = build_combined_shopping_list(today=TODAY)
    row = next(x for x in result['open'] if x['ingredient_id'] == ing.id)
    assert row['amount'] == 200
    assert row['recipes'] == ['Soep wk28']


def test_manual_item_has_no_recipe_hint(app):
    ing = Ingredient(name='statiegeldflesje', display_name='Statiegeldflesje', category='overig')
    db.session.add(ing)
    db.session.commit()
    iso = date.today().isocalendar()
    db.session.add(CustomShoppingIngredient(year=iso[0], week_number=iso[1],
                                            ingredient_id=ing.id, amount=1, unit='stuks'))
    db.session.commit()

    result = build_combined_shopping_list()
    row = next(x for x in result['open'] if x['ingredient_id'] == ing.id)
    assert row['recipes'] == []


def test_checked_older_than_14_days_hidden(app):
    r, ing = _mk_recipe('Soep', 'prei', 2, unit='stuks')
    _plan(r, 2026, 28)
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id,
                                 checked_at=datetime(2026, 6, 1)))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]


def test_quick_add_recipe_counts_and_old_manual_week_included(app):
    r, ing = _mk_recipe('Feestje', 'chips', 3, unit='zak')
    # QuickAddItem in een week buiten het venster (3 weken terug, week 25)
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=4,
                                week_number=25, year=2026))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert any(q['recipe_id'] == r.id for q in result['quick_add'])


def test_send_dict_to_ah_returns_sent_ids(app, monkeypatch):
    from weekmenu.services import shopping as shopping_svc

    r, ing = _mk_recipe('Dal', 'linzen-ah', 200)
    ing.ah_product_id = 12345
    _plan(r, 2026, 28)
    r2, ing2 = _mk_recipe('Soep', 'ongekoppeld-ding', 1, unit='stuks')
    _plan(r2, 2026, 28)
    db.session.commit()

    monkeypatch.setattr(shopping_svc, 'ah_get_access_token', lambda: 'token')

    class FakeResp:
        status_code = 404
        def json(self): return {}
        def raise_for_status(self): pass
    class FakeReq:
        def get(self, *a, **kw): return FakeResp()
        def patch(self, *a, **kw): return FakeResp()
        def put(self, *a, **kw): return FakeResp()
    monkeypatch.setattr(shopping_svc, 'requests', FakeReq())

    from weekmenu.services.shopping import _build_shopping_dict, send_dict_to_ah
    payload, status, sent_ids = send_dict_to_ah(_build_shopping_dict(2026, 28), {})
    assert status == 200
    assert payload['status'] == 'ok'
    assert ing.id in sent_ids
    assert ing2.id not in sent_ids
    assert 'ongekoppeld-ding' in ' '.join(payload['not_linked'])


def test_check_endpoint_checks_all_weeks(app, client):
    r1, ing = _mk_recipe('A', 'kikkererwten', 200)
    r2, _ = _mk_recipe('B', 'kikkererwten', 100)
    iso = date.today().isocalendar()
    nxt = (date.today() + timedelta(days=7)).isocalendar()
    _plan(r1, iso[0], iso[1])
    _plan(r2, nxt[0], nxt[1])
    db.session.commit()

    resp = client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': True})
    assert resp.status_code == 200
    assert ShoppingCheck.query.filter_by(ingredient_id=ing.id).count() == 2

    resp = client.post(f'/api/boodschappen/item/{ing.id}/check', json={'checked': False})
    assert resp.status_code == 200
    assert ShoppingCheck.query.filter_by(ingredient_id=ing.id).count() == 0


def test_check_unknown_ingredient_404(app, client):
    assert client.post('/api/boodschappen/item/99999/check',
                       json={'checked': True}).status_code == 404


def test_extra_add_and_delete(app, client):
    r, ing = _mk_recipe('Shakshuka', 'eieren-extra', 3, unit='stuks')
    db.session.commit()
    resp = client.post('/api/boodschappen/extra',
                       json={'recipe_id': r.id, 'people_count': 2})
    assert resp.status_code == 200
    qid = resp.get_json()['id']
    assert QuickAddItem.query.get(qid) is not None

    assert client.delete(f'/api/boodschappen/extra/{qid}').status_code == 200
    assert QuickAddItem.query.get(qid) is None


def test_add_item_current_week_appears_open(app, client):
    ing = Ingredient(name='verse munt', display_name='Verse munt', category='groente')
    db.session.add(ing)
    db.session.commit()
    iso = date.today().isocalendar()

    resp = client.post(f'/api/shopping-list/{iso[0]}/{iso[1]}/add-item',
                       json={'ingredient_id': ing.id, 'amount': 1, 'unit': 'bosje'})
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'ok'

    result = build_combined_shopping_list()
    rows = [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert rows, 'los toegevoegd item moet open op de gecombineerde lijst staan'


def test_old_urls_redirect(app, client):
    resp = client.get('/shopping-list/2026/28')
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/boodschappen')
    resp = client.get('/quick-add')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/boodschappen')


def test_combined_send_to_ah_checks_sent_items(app, client, monkeypatch):
    from weekmenu.services import shopping as shopping_svc
    r, ing = _mk_recipe('Dal-ah', 'linzen-combined', 200)
    ing.ah_product_id = 777
    iso = date.today().isocalendar()
    _plan(r, iso[0], iso[1])
    db.session.commit()

    monkeypatch.setattr(shopping_svc, 'ah_get_access_token', lambda: 'token')
    class FakeResp:
        status_code = 404
        def json(self): return {}
        def raise_for_status(self): pass
    class FakeReq:
        def get(self, *a, **kw): return FakeResp()
        def patch(self, *a, **kw): return FakeResp()
        def put(self, *a, **kw): return FakeResp()
    monkeypatch.setattr(shopping_svc, 'requests', FakeReq())

    resp = client.post('/api/boodschappen/send-to-ah', json={})
    assert resp.status_code == 200
    check = ShoppingCheck.query.filter_by(ingredient_id=ing.id).first()
    assert check is not None and check.via_ah is True


def test_week_menu_sets_cookie_and_home_follows_it(app, client):
    resp = client.get('/week/2026/30')
    assert resp.status_code == 200
    cookies = resp.headers.getlist('Set-Cookie')
    assert any('last_viewed_week=2026-30' in c for c in cookies)

    client.set_cookie('last_viewed_week', '2026-30')
    resp = client.get('/')
    assert resp.status_code == 302
    assert '/week/2026/30' in resp.headers['Location']


def test_home_ignores_invalid_cookie(app, client):
    client.set_cookie('last_viewed_week', '2026-60')
    resp = client.get('/')
    iso = date.today().isocalendar()
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']

    client.set_cookie('last_viewed_week', 'onzin')
    resp = client.get('/')
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']


def test_week_menu_invalid_week_for_year_redirects(app, client):
    resp = client.get('/week/2025/53')  # 2025 heeft geen week 53
    assert resp.status_code == 302
    iso = date.today().isocalendar()
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']


def test_home_ignores_cookie_week_invalid_for_year(app, client):
    client.set_cookie('last_viewed_week', '2025-53')
    resp = client.get('/')
    iso = date.today().isocalendar()
    assert f'/week/{iso[0]}/{iso[1]}' in resp.headers['Location']


def test_remove_endpoint_removes_custom_item(app, client):
    ing = Ingredient(name='verwijdertest', display_name='verwijdertest', category='overig')
    db.session.add(ing)
    db.session.commit()
    iso = date.today().isocalendar()
    client.post(f'/api/shopping-list/{iso[0]}/{iso[1]}/add-item',
                json={'ingredient_id': ing.id, 'amount': 1, 'unit': 'stuks'})
    assert [x for x in build_combined_shopping_list()['open'] if x['ingredient_id'] == ing.id]

    resp = client.post(f'/api/boodschappen/item/{ing.id}/remove')
    assert resp.status_code == 200
    assert not [x for x in build_combined_shopping_list()['open'] if x['ingredient_id'] == ing.id]


def test_remove_endpoint_removes_menu_item_via_exclusion(app, client):
    r, ing = _mk_recipe('Wegwezen', 'exclude-ding', 100)
    iso = date.today().isocalendar()
    _plan(r, iso[0], iso[1])
    db.session.commit()
    assert client.post(f'/api/boodschappen/item/{ing.id}/remove').status_code == 200
    assert not [x for x in build_combined_shopping_list()['open'] if x['ingredient_id'] == ing.id]
    assert client.post('/api/boodschappen/item/99999/remove').status_code == 404
