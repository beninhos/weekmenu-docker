"""Geïmporteerde receptregels (Gemini/scrape) krijgen voorraadstatus mee."""
from weekmenu.extensions import db
from weekmenu.models import Ingredient, PantryIngredient
from weekmenu.services.pantry import annotate_pantry_status


def _ing(name, category, pantry=False):
    i = Ingredient(name=name, display_name=name, category=category)
    db.session.add(i)
    db.session.flush()
    if pantry:
        db.session.add(PantryIngredient(ingredient_id=i.id))
    db.session.commit()
    return i


def test_bekend_voorraaditem_wordt_bevestigd_zonder_klik(client, app):
    i = _ing('olijfolie', 'Oliën, Sauzen & Smaakmakers', pantry=True)
    rows = annotate_pantry_status([
        {'name': 'olijfolie', 'amount': 2, 'unit': 'el',
         'category': 'Oliën, Sauzen & Smaakmakers'}])
    assert rows[0]['id'] == i.id
    assert rows[0]['in_pantry'] is True
    assert rows[0]['pantry_hint'] == 'in_pantry'


def test_spellingsvariant_van_voorraaditem_vraagt_om_bevestiging(client, app):
    twin = _ing('rodewijnazijn', 'Oliën, Sauzen & Smaakmakers', pantry=True)
    rows = annotate_pantry_status([
        {'name': 'rode wijnazijn', 'amount': 1, 'unit': 'el',
         'category': 'Oliën, Sauzen & Smaakmakers'}])
    assert rows[0]['in_pantry'] is False
    assert rows[0]['pantry_hint'] == 'variant'
    assert rows[0]['variant_of'] == {'id': twin.id, 'name': 'rodewijnazijn'}


def test_dosis_uit_een_kastcategorie_wordt_voorgesteld(client, app):
    rows = annotate_pantry_status([
        {'name': 'kurkuma', 'amount': 1, 'unit': 'tl',
         'category': 'Kruiden & Specerijen'}])
    assert rows[0]['pantry_hint'] == 'suggest'
    assert rows[0]['id'] is None


def test_hele_verpakking_wordt_niet_voorgesteld(client, app):
    rows = annotate_pantry_status([
        {'name': 'tomatenpuree', 'amount': 140, 'unit': 'g',
         'category': 'Oliën, Sauzen & Smaakmakers'}])
    assert rows[0]['pantry_hint'] is None


def test_verse_producten_worden_niet_voorgesteld(client, app):
    rows = annotate_pantry_status([
        {'name': 'courgette', 'amount': 1, 'unit': 'stuks',
         'category': 'Groente, Fruit & Aardappelen'},
        {'name': 'rode peper', 'amount': 1, 'unit': 'stuks',
         'category': 'Kruiden & Specerijen'}])
    assert [r['pantry_hint'] for r in rows] == [None, None]


def test_jouw_vier_oordelen(client, app):
    rows = annotate_pantry_status([
        {'name': 'tomatenpuree', 'amount': 140, 'unit': 'g', 'category': 'Oliën, Sauzen & Smaakmakers'},
        {'name': 'honing', 'amount': 1, 'unit': 'tl', 'category': 'Oliën, Sauzen & Smaakmakers'},
        {'name': 'bloem', 'amount': 2, 'unit': 'el', 'category': 'Ontbijt, Bakken & Desserts'},
        {'name': 'mayonaise', 'amount': 2, 'unit': 'el', 'category': 'Oliën, Sauzen & Smaakmakers'}])
    assert [r['pantry_hint'] for r in rows] == [None, 'suggest', 'suggest', 'suggest']


def test_lege_lijst_blijft_leeg(client, app):
    assert annotate_pantry_status([]) == []


def test_dump_draft_endpoint_geeft_voorraadstatus_mee(client, app):
    import json
    from weekmenu.models import DumpJob, RecipeDraft

    _ing('olijfolie', 'Oliën, Sauzen & Smaakmakers', pantry=True)
    job = DumpJob(id='job-1')
    db.session.add(job)
    db.session.flush()
    draft = RecipeDraft(job_id=job.id, name='Concept', ingredients_json=json.dumps([
        {'name': 'olijfolie', 'amount': 2, 'unit': 'el',
         'category': 'Oliën, Sauzen & Smaakmakers'},
        {'name': 'kurkuma', 'amount': 1, 'unit': 'tl',
         'category': 'Kruiden & Specerijen'},
    ]))
    db.session.add(draft)
    db.session.commit()

    rows = client.get(f'/dump/draft/{draft.id}').get_json()['ingredients']
    assert rows[0]['in_pantry'] is True
    assert rows[1]['pantry_hint'] == 'suggest'


def test_verse_kruiden_worden_nog_niet_als_kastartikel_voorgesteld(client, app):
    """Verse kruiden zitten nog in 'Kruiden & Specerijen' en gaan per paar gram."""
    rows = annotate_pantry_status([
        {'name': 'verse basilicum', 'amount': 22, 'unit': 'g', 'category': 'Kruiden & Specerijen'},
        {'name': 'verse munt', 'amount': 4, 'unit': 'takje', 'category': 'Kruiden & Specerijen'},
        {'name': 'bladpeterselie', 'amount': 1, 'unit': 'bosje', 'category': 'Kruiden & Specerijen'},
        {'name': 'kaneel', 'amount': 1, 'unit': 'tl', 'category': 'Kruiden & Specerijen'}])
    assert [r['pantry_hint'] for r in rows] == [None, None, None, 'suggest']


def test_zoek_api_stelt_kastartikel_voor_bij_typen(client, app):
    """Bij typen bestaat de receptregel nog niet, dus telt het gebruik tot nu toe."""
    from weekmenu.models import Recipe, RecipeIngredient

    kurkuma = _ing('kurkuma', 'Kruiden & Specerijen')
    puree = _ing('tomatenpuree', 'Oliën, Sauzen & Smaakmakers')
    r = Recipe(name='R', serves=2)
    db.session.add(r)
    db.session.flush()
    db.session.add_all([
        RecipeIngredient(recipe_id=r.id, ingredient_id=kurkuma.id, amount=1, unit='tl'),
        RecipeIngredient(recipe_id=r.id, ingredient_id=puree.id, amount=140, unit='g'),
    ])
    db.session.commit()

    by_name = {r['name']: r for r in client.get('/api/ingredients/search?q=kurkuma').get_json()}
    assert by_name['kurkuma']['pantry_hint'] == 'suggest'
    by_name = {r['name']: r for r in client.get('/api/ingredients/search?q=tomatenpuree').get_json()}
    assert by_name['tomatenpuree']['pantry_hint'] is None


def test_zoek_api_meldt_wat_al_op_voorraad_staat(client, app):
    _ing('olijfolie', 'Oliën, Sauzen & Smaakmakers', pantry=True)
    row = client.get('/api/ingredients/search?q=olijfolie').get_json()[0]
    assert row['in_pantry'] is True and row['pantry_hint'] == 'in_pantry'
