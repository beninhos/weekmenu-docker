"""Migratie v10: de universele schapindeling, getoetst op representatieve rijen."""
from sqlalchemy import text
from weekmenu.extensions import db
from weekmenu.migrations import _migrate_v10
from weekmenu.models import Ingredient
from weekmenu.constants import PRODUCT_CATEGORIES, CATEGORY_ORDER_SUPERMARKET, CATEGORY_BG


def _seed(rows):
    for name, cat in rows:
        db.session.add(Ingredient(name=name, display_name=name, category=cat))
    db.session.commit()


def _cat(name):
    return Ingredient.query.filter_by(name=name).one().category


def test_constantenlijsten_zijn_consistent(app):
    assert set(PRODUCT_CATEGORIES) == set(CATEGORY_ORDER_SUPERMARKET)
    assert set(PRODUCT_CATEGORIES) == set(CATEGORY_BG)


def test_splitsingen_en_hernoemingen(client, app):
    _seed([
        # Groente/Fruit-splitsing
        ('appel', 'Groente, Fruit & Aardappelen'),
        ('courgette', 'Groente, Fruit & Aardappelen'),
        ('basilicum', 'Groente, Fruit & Aardappelen'),
        # Kaas/Vleeswaren-splitsing incl. het beroemde geval
        ('achterham', 'Kaas & Vleeswaren'),
        ('geraspte oude kaas', 'Kaas & Vleeswaren'),
        ('pindakaas', 'Kaas & Vleeswaren'),
        # Ontbijt&Beleg/Bakken-splitsing incl. bloemkool-weeffout
        ('bosvruchten jam', 'Ontbijt, Bakken & Desserts'),
        ('bloem', 'Ontbijt, Bakken & Desserts'),
        ('bloemkool', 'Ontbijt, Bakken & Desserts'),
        # Verse kruiden uit droge specerijen
        ('verse munt', 'Kruiden & Specerijen'),
        ('rode peper', 'Kruiden & Specerijen'),
        ('zwarte peper', 'Kruiden & Specerijen'),
        # Hernoemingen en wezen
        ('halfvolle melk', 'Zuivel, Plantaardige Zuivel & Eieren'),
        ('fijne mosterd', 'Soepen, Sauzen & Kruiden'),
        ('verse dragon', 'Groente & Aardappelen'),
        # Buiten de splitsing: bewuste keuze blijft staan
        ('mangochutney', 'Groente, Fruit & Aardappelen'),
        ('tuinkers', 'Groente, Fruit & Aardappelen'),
        ('parmaham', 'Kaas & Vleeswaren'),
        ('manchego twee', 'Zuivel, Plantaardige Zuivel & Eieren'),
        ('kimchi', 'Conserven & Peulvruchten'),
        ('manchego', 'Overig'),
    ])
    with db.engine.connect() as conn:
        _migrate_v10(conn)
        conn.commit()
    db.session.expire_all()

    assert _cat('appel') == 'Fruit'
    assert _cat('courgette') == 'Groente & Aardappelen'
    assert _cat('basilicum') == 'Verse Kruiden'
    assert _cat('achterham') == 'Vleeswaren'
    assert _cat('geraspte oude kaas') == 'Kaas'
    assert _cat('pindakaas') == 'Ontbijt & Beleg'
    assert _cat('bosvruchten jam') == 'Ontbijt & Beleg'
    assert _cat('bloem') == 'Bakken & Desserts'
    assert _cat('bloemkool') == 'Groente & Aardappelen'
    assert _cat('verse munt') == 'Verse Kruiden'
    assert _cat('rode peper') == 'Groente & Aardappelen'
    assert _cat('zwarte peper') == 'Kruiden & Specerijen'
    assert _cat('halfvolle melk') == 'Zuivel & Eieren'
    assert _cat('fijne mosterd') == 'Oliën, Sauzen & Smaakmakers'
    assert _cat('verse dragon') == 'Verse Kruiden'
    assert _cat('mangochutney') == 'Oliën, Sauzen & Smaakmakers'
    assert _cat('tuinkers') == 'Groente & Aardappelen'
    assert _cat('parmaham') == 'Vleeswaren'
    assert _cat('manchego twee') == 'Kaas'
    assert _cat('kimchi') == 'Conserven & Peulvruchten'   # niet aangeraakt
    assert _cat('manchego') == 'Overig'                    # niet aangeraakt


def test_verse_kruiden_zijn_geen_kastartikel_meer(client, app):
    from weekmenu.services.pantry import annotate_pantry_status
    rows = annotate_pantry_status([
        {'name': 'verse basilicum', 'amount': 22, 'unit': 'g', 'category': 'Verse Kruiden'},
        {'name': 'kaneel', 'amount': 1, 'unit': 'tl', 'category': 'Kruiden & Specerijen'},
        {'name': 'bosvruchten jam', 'amount': 1, 'unit': 'el', 'category': 'Ontbijt & Beleg'},
    ])
    assert [r['pantry_hint'] for r in rows] == [None, 'suggest', 'suggest']


def test_verouderde_categorie_lekt_niet_binnen_bij_nieuw_ingredient(client, app):
    """De dropdown toont verouderde waarden als optie; die mogen niet
    als categorie van een nieuw ingredient worden opgeslagen."""
    from weekmenu.services.recipes import _resolve_or_create_ingredient
    ing = _resolve_or_create_ingredient('venkelzaad', 'Groente, Fruit & Aardappelen')
    db.session.commit()
    assert ing.category in PRODUCT_CATEGORIES
    assert ing.category != 'Groente, Fruit & Aardappelen'


def test_v11_ruimt_oude_categorieen_op_in_ingredienten_en_drafts(client, app):
    import json
    from weekmenu.migrations import _migrate_v11
    from weekmenu.models import DumpJob, RecipeDraft

    _seed([('venkelzaad', 'Groente, Fruit & Aardappelen')])
    job = DumpJob(id='job-v11')
    db.session.add(job)
    db.session.flush()
    draft = RecipeDraft(job_id=job.id, name='Oud concept', ingredients_json=json.dumps([
        {'name': 'appel', 'amount': 1, 'unit': 'stuks', 'category': 'Groente, Fruit & Aardappelen'},
        {'name': 'kaneel', 'amount': 1, 'unit': 'tl', 'category': 'Kruiden & Specerijen'},
    ]))
    db.session.add(draft)
    db.session.commit()

    with db.engine.connect() as conn:
        _migrate_v11(conn)
        conn.commit()
    db.session.expire_all()

    assert _cat('venkelzaad') in PRODUCT_CATEGORIES
    items = json.loads(RecipeDraft.query.get(draft.id).ingredients_json)
    assert items[0]['category'] == 'Fruit'          # herzien
    assert items[1]['category'] == 'Kruiden & Specerijen'  # ongemoeid


def test_boodschappenlijst_heeft_printknop_en_printstijl(client, app):
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'window.print()' in html
    assert '@media print' in html
    assert 'shopping-list-print' in html
