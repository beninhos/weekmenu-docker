"""Migratie v10: de universele schapindeling, getoetst op representatieve rijen."""
from sqlalchemy import text
from weekmenu.extensions import db
from weekmenu.migrations import _migrate_v10, _migrate_v12
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


def test_migratieketen_v10_tot_v12(client, app):
    """v10 splitste, v12 voegt vier daarvan weer samen. Samen moeten ze op
    het huidige vocabulaire uitkomen, ongeacht van welke oude naam je start."""
    _seed([
        ('appel', 'Groente, Fruit & Aardappelen'),
        ('courgette', 'Groente, Fruit & Aardappelen'),
        ('basilicum', 'Groente, Fruit & Aardappelen'),
        ('achterham', 'Kaas & Vleeswaren'),
        ('geraspte oude kaas', 'Kaas & Vleeswaren'),
        ('pindakaas', 'Kaas & Vleeswaren'),
        ('bosvruchten jam', 'Ontbijt, Bakken & Desserts'),
        ('bloem', 'Ontbijt, Bakken & Desserts'),
        ('bloemkool', 'Ontbijt, Bakken & Desserts'),
        ('verse munt', 'Kruiden & Specerijen'),
        ('rode peper', 'Kruiden & Specerijen'),
        ('zwarte peper', 'Kruiden & Specerijen'),
        ('halfvolle melk', 'Zuivel, Plantaardige Zuivel & Eieren'),
        ('fijne mosterd', 'Soepen, Sauzen & Kruiden'),
        ('zalm', 'Vis & Schaaldieren'),
        ('walnoten', 'Noten, Zaden & Gedroogd Fruit'),
        ('spaghetti', 'Pasta, Rijst & Granen'),
        ('kimchi', 'Conserven & Peulvruchten'),
    ])
    with db.engine.connect() as conn:
        _migrate_v10(conn)
        _migrate_v12(conn)
        conn.commit()
    db.session.expire_all()

    # AGF is nu een hoek: groente, fruit en verse kruiden bij elkaar
    for naam in ('appel', 'courgette', 'basilicum', 'verse munt', 'rode peper', 'bloemkool'):
        assert _cat(naam) == 'Groente, Fruit & Aardappelen', naam
    # koelwand
    assert _cat('achterham') == 'Kaas & Vleeswaren'
    assert _cat('geraspte oude kaas') == 'Kaas & Vleeswaren'
    assert _cat('zalm') == 'Vlees & Vis'
    assert _cat('halfvolle melk') == 'Zuivel & Eieren'
    # droge midden
    assert _cat('pindakaas') == 'Ontbijt & Beleg'
    assert _cat('bosvruchten jam') == 'Ontbijt & Beleg'
    assert _cat('bloem') == 'Bakken & Desserts'
    assert _cat('zwarte peper') == 'Kruiden & Specerijen'
    assert _cat('fijne mosterd') == 'Oliën, Sauzen & Smaakmakers'
    assert _cat('walnoten') == 'Noten & Snacks'
    assert _cat('spaghetti') == 'Pasta, Rijst & Wereldkeuken'
    # buiten elke splitsing: bewuste keuze blijft staan
    assert _cat('kimchi') == 'Conserven & Peulvruchten'
    # en niets valt buiten het vocabulaire
    for ing in Ingredient.query.all():
        assert ing.category in PRODUCT_CATEGORIES, ing.name


def test_looproute_is_geen_kopie_van_toevallige_volgorde(app):
    """De volgorde moet een route zijn: vers eerst, kassa-kant achteraan."""
    o = CATEGORY_ORDER_SUPERMARKET
    assert o[0] == 'Groente, Fruit & Aardappelen'
    assert o.index('Kaas & Vleeswaren') < o.index('Pasta, Rijst & Wereldkeuken')
    assert o.index('Diepvries') < o.index('Dranken')
    assert o[-1] == 'Overig'


def test_verse_kruiden_zijn_geen_kastartikel_meer(client, app):
    from weekmenu.services.pantry import annotate_pantry_status
    rows = annotate_pantry_status([
        {'name': 'verse basilicum', 'amount': 22, 'unit': 'g', 'category': 'Groente, Fruit & Aardappelen'},
        {'name': 'kaneel', 'amount': 1, 'unit': 'tl', 'category': 'Kruiden & Specerijen'},
        {'name': 'bosvruchten jam', 'amount': 1, 'unit': 'el', 'category': 'Ontbijt & Beleg'},
    ])
    assert [r['pantry_hint'] for r in rows] == [None, 'suggest', 'suggest']


def test_verouderde_categorie_lekt_niet_binnen_bij_nieuw_ingredient(client, app):
    """De dropdown toont verouderde waarden als optie; die mogen niet
    als categorie van een nieuw ingredient worden opgeslagen."""
    from weekmenu.services.recipes import _resolve_or_create_ingredient
    ing = _resolve_or_create_ingredient('venkelzaad', 'Soepen, Sauzen & Kruiden')
    db.session.commit()
    assert ing.category in PRODUCT_CATEGORIES
    assert ing.category != 'Soepen, Sauzen & Kruiden'


def test_v11_ruimt_oude_categorieen_op_in_ingredienten_en_drafts(client, app):
    import json
    from weekmenu.migrations import _migrate_v11
    from weekmenu.models import DumpJob, RecipeDraft

    _seed([('venkelzaad', 'Soepen, Sauzen & Kruiden')])
    job = DumpJob(id='job-v11')
    db.session.add(job)
    db.session.flush()
    draft = RecipeDraft(job_id=job.id, name='Oud concept', ingredients_json=json.dumps([
        {'name': 'appel', 'amount': 1, 'unit': 'stuks', 'category': 'Soepen, Sauzen & Kruiden'},
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
    assert items[0]['category'] == 'Groente, Fruit & Aardappelen'          # herzien
    assert items[1]['category'] == 'Kruiden & Specerijen'  # ongemoeid


def test_boodschappenlijst_heeft_printknop_en_printstijl(client, app):
    html = client.get('/boodschappen').get_data(as_text=True)
    assert 'window.print()' in html
    assert '@media print' in html
    assert 'shopping-list-print' in html


def test_meel_familie_landt_goed(app):
    """'maismeel' matchte 'mais' (groente), 'tarwemeel' had geen sleutelwoord."""
    from weekmenu.services.units import _guess_ingredient_category as g
    for naam in ('maismeel', 'maïsmeel', 'tarwemeel', 'roggemeel', 'boekweitmeel',
                 'speltmeel', 'bloem', 'tarwebloem', 'zelfrijzend bakmeel', 'paneermeel'):
        assert g(naam) == 'Bakken & Desserts', naam
    for naam in ('maisgriesmeel', 'instant maisgriesmeel', 'griesmeel', 'polenta',
                 'Valle del sole Maisgriesmeel voor polenta bramata'):
        assert g(naam) == 'Pasta, Rijst & Wereldkeuken', naam
    # de buren mogen niet meeverhuizen
    assert g('amandelmeel') == 'Noten & Snacks'
    assert g('bloemkool') == 'Groente, Fruit & Aardappelen'
    assert g('mais') == 'Groente, Fruit & Aardappelen'
