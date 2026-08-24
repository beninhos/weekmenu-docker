"""Maaltijdtype-tags: invoer, achteraf taggen en filter-data."""
from weekmenu.extensions import db
from weekmenu.models import Recipe, RecipeMealType


def _recipe(name='Soep'):
    r = Recipe(name=name, serves=2)
    db.session.add(r)
    db.session.commit()
    return r


def _codes(recipe_id):
    return sorted(m.meal_type for m in RecipeMealType.query.filter_by(recipe_id=recipe_id))


def test_nieuw_recept_slaat_maaltijdtypen_op(client, app):
    resp = client.post('/recipe/new', data={
        'name': 'Tomatensoep', 'page': '', 'serves': '2', 'cookbook': '',
        'url': '', 'instructions': '',
        'ingredient[]': ['tomaat'], 'ingredient_id[]': [''],
        'amount[]': ['3'], 'unit[]': ['stuks'],
        'category[]': ['Groente, Fruit & Aardappelen'],
        'preparation[]': [''], 'pantry_flag[]': ['0'],
        'meal_type[]': ['lunch', 'diner'],
    })
    assert resp.status_code == 302
    r = Recipe.query.filter_by(name='Tomatensoep').one()
    assert _codes(r.id) == ['diner', 'lunch']


def test_bewerken_synct_toevoegen_en_weghalen(client, app):
    r = _recipe()
    db.session.add(RecipeMealType(recipe_id=r.id, meal_type='diner'))
    db.session.commit()
    client.post(f'/recipe/{r.id}/edit', data={
        'name': 'Soep', 'page': '', 'serves': '2', 'cookbook': '',
        'url': '', 'instructions': '',
        'ingredient[]': [], 'ingredient_id[]': [], 'amount[]': [], 'unit[]': [],
        'category[]': [], 'preparation[]': [], 'pantry_flag[]': [],
        'meal_type[]': ['lunch'],
    })
    assert _codes(r.id) == ['lunch']


def test_achteraf_taggen_via_de_api(client, app):
    r = _recipe()
    resp = client.post(f'/api/recipe/{r.id}/meal-types',
                       json={'meal_types': ['ontbijt', 'tussendoor']})
    assert resp.get_json() == {'status': 'ok', 'meal_types': ['ontbijt', 'tussendoor']}
    resp = client.post(f'/api/recipe/{r.id}/meal-types', json={'meal_types': []})
    assert resp.get_json()['meal_types'] == []


def test_onbekende_codes_worden_genegeerd(client, app):
    r = _recipe()
    resp = client.post(f'/api/recipe/{r.id}/meal-types',
                       json={'meal_types': ['diner', 'brunch', '<script>']})
    assert resp.get_json()['meal_types'] == ['diner']


def test_api_zonder_lijst_geeft_400(client, app):
    r = _recipe()
    assert client.post(f'/api/recipe/{r.id}/meal-types', json={}).status_code == 400


def test_recept_detail_bevat_maaltijdtypen(client, app):
    r = _recipe()
    db.session.add(RecipeMealType(recipe_id=r.id, meal_type='tussendoor'))
    db.session.commit()
    data = client.get(f'/api/recipe/{r.id}').get_json()
    assert data['meal_types'] == ['tussendoor']


def test_planner_levert_filterchips_en_opties(client, app):
    html = client.get('/receptenplanner').get_data(as_text=True)
    assert 'id="mealtype-filter"' in html
    assert 'id="meal-type-opts"' in html
    assert 'Tussendoor' in html


def test_verwijderen_recept_ruimt_tags_op(client, app):
    r = _recipe()
    db.session.add(RecipeMealType(recipe_id=r.id, meal_type='diner'))
    db.session.commit()
    db.session.delete(r)
    db.session.commit()
    assert RecipeMealType.query.count() == 0
