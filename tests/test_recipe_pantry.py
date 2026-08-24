"""Voorraadmarkering en categoriecorrectie bij het invoeren van recepten."""
from weekmenu.extensions import db
from weekmenu.models import Ingredient, PantryIngredient, Recipe, RecipeIngredient


def _post_new(client, **over):
    form = {
        'name': 'Testrecept', 'page': '', 'serves': '2', 'cookbook': '',
        'url': '', 'instructions': '',
        'ingredient[]': ['olijfolie'], 'ingredient_id[]': [''],
        'amount[]': ['2'], 'unit[]': ['el'],
        'category[]': ['Oliën, Sauzen & Smaakmakers'],
        'preparation[]': [''], 'pantry_flag[]': ['0'],
    }
    form.update(over)
    return client.post('/recipe/new', data=form, follow_redirects=False)


def test_nieuw_recept_kan_ingredient_op_voorraad_zetten(client, app):
    resp = _post_new(client, **{'pantry_flag[]': ['1']})
    assert resp.status_code == 302
    ing = Ingredient.query.filter_by(name='olijfolie').one()
    assert PantryIngredient.query.filter_by(ingredient_id=ing.id).first() is not None


def test_nieuw_recept_zonder_vlag_laat_voorraad_leeg(client, app):
    _post_new(client)
    assert PantryIngredient.query.count() == 0


def test_leeg_pantry_veld_laat_opslaan_niet_crashen(client, app):
    resp = _post_new(client, **{'pantry_flag[]': ['']})
    assert resp.status_code == 302
    assert PantryIngredient.query.count() == 0


def _make_recipe(prep='grof', category='Overig'):
    ing = Ingredient(name='mosterd', display_name='mosterd', category=category)
    db.session.add(ing)
    db.session.flush()
    r = Recipe(name='Bestaand', serves=2)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=1, unit='el', preparation=prep))
    db.session.commit()
    return r, ing


def _edit_form(ing, category, prep, flag='0'):
    return {
        'name': 'Bestaand', 'page': '', 'serves': '2', 'cookbook': '',
        'url': '', 'instructions': '',
        'ingredient[]': ['mosterd'], 'ingredient_id[]': [str(ing.id)],
        'amount[]': ['1'], 'unit[]': ['el'], 'category[]': [category],
        'preparation[]': [prep], 'pantry_flag[]': [flag],
    }


def test_bewerken_bewaart_de_bereiding(client, app):
    r, ing = _make_recipe(prep='grof')
    client.post(f'/recipe/{r.id}/edit',
                data=_edit_form(ing, 'Overig', 'grof'))
    assert RecipeIngredient.query.filter_by(recipe_id=r.id).one().preparation == 'grof'


def test_categorie_van_bestaand_ingredient_is_te_corrigeren(client, app):
    r, ing = _make_recipe(category='Overig')
    client.post(f'/recipe/{r.id}/edit',
                data=_edit_form(ing, 'Oliën, Sauzen & Smaakmakers', ''))
    assert Ingredient.query.get(ing.id).category == 'Oliën, Sauzen & Smaakmakers'


def test_onbekende_categorie_wordt_niet_overgenomen(client, app):
    r, ing = _make_recipe(category='Overig')
    client.post(f'/recipe/{r.id}/edit',
                data=_edit_form(ing, 'Zuivel & Eieren', ''))
    assert Ingredient.query.get(ing.id).category == 'Overig'


def test_uitvinken_haalt_alleen_ingredienten_van_dit_recept_uit_de_voorraad(client, app):
    r, ing = _make_recipe()
    ander = Ingredient(name='zout', display_name='zout', category='Kruiden & Specerijen')
    db.session.add(ander)
    db.session.flush()
    db.session.add_all([PantryIngredient(ingredient_id=ing.id),
                        PantryIngredient(ingredient_id=ander.id)])
    db.session.commit()

    client.post(f'/recipe/{r.id}/edit', data=_edit_form(ing, 'Overig', '', flag='0'))

    assert PantryIngredient.query.filter_by(ingredient_id=ing.id).first() is None
    assert PantryIngredient.query.filter_by(ingredient_id=ander.id).first() is not None


def test_autocomplete_geeft_voorraadstatus_terug(client, app):
    ing = Ingredient(name='olijfolie', display_name='olijfolie',
                     category='Oliën, Sauzen & Smaakmakers')
    db.session.add(ing)
    db.session.flush()
    db.session.add(PantryIngredient(ingredient_id=ing.id))
    db.session.commit()

    data = client.get('/api/ingredients/search?q=olijfolie').get_json()
    assert data and data[0]['in_pantry'] is True


def test_bewerkformulier_stuurt_de_bereiding_mee(client, app):
    """De bereiding stond nergens in het formulier, dus elke edit wiste hem."""
    r, ing = _make_recipe(prep='grof')
    html = client.get(f'/recipe/{r.id}/edit').get_data(as_text=True)
    assert 'name="preparation[]" value="grof"' in html


def test_nieuw_receptformulier_heeft_een_voorraadmarkering(client, app):
    html = client.get('/recipe/new').get_data(as_text=True)
    assert 'name="pantry_flag[]"' in html
    assert 'altijd in huis' in html


def test_verouderde_categorie_blijft_selecteerbaar_in_de_dropdown(client, app):
    """Zonder deze optie stuurt de select niets mee en schuiven de rijen op."""
    r, ing = _make_recipe(category='Zuivel & Eieren')
    html = client.get(f'/recipe/{r.id}/edit').get_data(as_text=True)
    assert 'Zuivel &amp; Eieren (verouderd)' in html


def test_server_rijen_hebben_het_label_dat_de_js_bijwerkt(client, app):
    """Zonder class="pantry-text" bleef het label op 'altijd in huis' staan."""
    r, ing = _make_recipe()
    for url in ('/recipe/new', f'/recipe/{r.id}/edit'):
        html = client.get(url).get_data(as_text=True)
        assert 'class="pantry-text"' in html, url
