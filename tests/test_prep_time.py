"""Bereidingstijd bestaat als veld, en de kaartmodus heeft zijn kolommen."""
import json

from sqlalchemy import create_engine, text

from weekmenu.extensions import db
from weekmenu.models import DumpJob, Recipe, RecipeDraft


def test_migratie_v16_voegt_kolommen_toe_aan_oude_tabellen():
    from weekmenu.migrations import _migrate_v16
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(text('CREATE TABLE dump_job (id VARCHAR(36) PRIMARY KEY, status VARCHAR(20))'))
        conn.execute(text('CREATE TABLE recipe (id INTEGER PRIMARY KEY, name VARCHAR(100))'))
        conn.execute(text('CREATE TABLE recipe_draft (id INTEGER PRIMARY KEY, name VARCHAR(100))'))
        conn.execute(text("INSERT INTO dump_job (id, status) VALUES ('j', 'done')"))
        _migrate_v16(conn)
        _migrate_v16(conn)  # idempotent
        kolommen = {t: [r[1] for r in conn.execute(text(f'PRAGMA table_info({t})')).fetchall()]
                    for t in ('dump_job', 'recipe', 'recipe_draft')}
        assert 'mode' in kolommen['dump_job']
        assert 'prep_time' in kolommen['recipe']
        assert 'prep_time' in kolommen['recipe_draft']
        assert 'back_image_path' in kolommen['recipe_draft']
        assert conn.execute(text("SELECT mode FROM dump_job WHERE id = 'j'")).scalar() == 'boek'


def test_modelvelden_bestaan(app):
    db.session.add(DumpJob(id='k', status='done', mode='kaart'))
    r = Recipe(name='Kaart', prep_time=40)
    db.session.add(r)
    db.session.flush()
    d = RecipeDraft(job_id='k', name='Kaart', prep_time=40, back_image_path='static/uploads/x.jpg')
    db.session.add(d)
    db.session.commit()
    assert DumpJob.query.get('k').mode == 'kaart'
    db.session.add(DumpJob(id='l', status='done'))
    db.session.commit()
    assert DumpJob.query.get('l').mode == 'boek'
    assert Recipe.query.get(r.id).prep_time == 40
    assert RecipeDraft.query.get(d.id).back_image_path == 'static/uploads/x.jpg'


def test_nieuw_recept_bewaart_bereidingstijd(app, client):
    resp = client.post('/recipe/new', data={'name': 'Snel', 'serves': '2', 'page': '',
                                            'prep_time': '40'})
    assert resp.status_code == 302
    assert Recipe.query.filter_by(name='Snel').first().prep_time == 40


def test_lege_of_onzinnige_bereidingstijd_wordt_none(app, client):
    client.post('/recipe/new', data={'name': 'Leeg', 'serves': '', 'page': '', 'prep_time': ''})
    client.post('/recipe/new', data={'name': 'Tekst', 'serves': '', 'page': '', 'prep_time': 'lang'})
    assert Recipe.query.filter_by(name='Leeg').first().prep_time is None
    assert Recipe.query.filter_by(name='Tekst').first().prep_time is None


def test_bewerken_wijzigt_bereidingstijd(app, client):
    r = Recipe(name='Oud', prep_time=10)
    db.session.add(r)
    db.session.commit()
    client.post(f'/recipe/{r.id}/edit', data={'name': 'Oud', 'serves': '', 'page': '',
                                               'prep_time': '25'})
    assert Recipe.query.get(r.id).prep_time == 25


def test_accepteren_neemt_bereidingstijd_over(app, client):
    db.session.add(DumpJob(id='p', status='done'))
    d = RecipeDraft(job_id='p', name='Kaart', prep_time=35, instructions='Stap 1.',
                    ingredients_json=json.dumps([{'name': 'ui', 'amount': 1, 'unit': 'stuks'}]))
    db.session.add(d)
    db.session.commit()
    resp = client.post(f'/dump/draft/{d.id}/accept', json={})
    assert resp.status_code == 200
    assert Recipe.query.get(resp.get_json()['recipe_id']).prep_time == 35


def test_serialize_draft_en_recipe_geven_prep_time(app, client):
    from weekmenu.routes.dump import serialize_draft
    from weekmenu.routes.recipes import serialize_recipe
    db.session.add(DumpJob(id='q', status='done'))
    d = RecipeDraft(job_id='q', name='K', prep_time=15, back_image_path='static/uploads/b.jpg')
    r = Recipe(name='R', prep_time=20)
    db.session.add_all([d, r])
    db.session.commit()
    assert serialize_draft(d)['prep_time'] == 15
    assert serialize_draft(d)['back_image_path'] == 'static/uploads/b.jpg'
    assert serialize_recipe(r)['prep_time'] == 20
