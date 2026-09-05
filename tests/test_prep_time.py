"""Bereidingstijd bestaat als veld, en de kaartmodus heeft zijn kolommen."""
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
