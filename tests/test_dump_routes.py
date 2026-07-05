import json

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft, Recipe


def _make_draft(app):
    job = DumpJob(id='job-1', status='done')
    draft = RecipeDraft(
        job_id='job-1', name='Dal', serves=2,
        instructions='Stap 1. Kook de linzen.',
        ingredients_json=json.dumps([
            {'name': 'rode linzen', 'amount': 200, 'unit': 'g', 'category': 'overig'},
            {'name': 'ui', 'amount': 1, 'unit': 'stuks', 'category': 'groente'},
        ]),
        status='pending',
    )
    db.session.add_all([job, draft])
    db.session.commit()
    return draft


def test_status_endpoint_lists_drafts(app, client):
    _make_draft(app)
    resp = client.get('/dump/status/job-1')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'done'
    assert data['drafts'][0]['name'] == 'Dal'
    assert len(data['drafts'][0]['ingredients']) == 2


def test_accept_creates_recipe_and_marks_draft(app, client):
    draft = _make_draft(app)
    resp = client.post(f'/dump/draft/{draft.id}/accept', json={'cookbook_id': None})
    assert resp.status_code == 200
    recipe_id = resp.get_json()['recipe_id']

    recipe = db.session.get(Recipe, recipe_id)
    assert recipe.name == 'Dal'
    assert recipe.serves == 2
    assert len(recipe.ingredients) == 2
    assert db.session.get(RecipeDraft, draft.id).status == 'accepted'


def test_reject_marks_draft(app, client):
    draft = _make_draft(app)
    resp = client.post(f'/dump/draft/{draft.id}/reject')
    assert resp.status_code == 200
    assert db.session.get(RecipeDraft, draft.id).status == 'rejected'


def test_upload_without_files_is_400(app, client):
    resp = client.post('/dump/upload', data={})
    assert resp.status_code == 400


def test_draft_prefill_payload(app, client):
    draft = _make_draft(app)
    data = client.get(f'/dump/draft/{draft.id}').get_json()
    assert data['status'] == 'success'
    assert data['draft_id'] == draft.id
    assert data['name'] == 'Dal'
    assert data['ingredients'][1]['name'] == 'ui'


def test_new_recipe_post_with_draft_id_accepts_draft(app, client):
    draft = _make_draft(app)
    resp = client.post('/recipe/new', data={
        'name': 'Dal (aangepast)', 'serves': '2', 'page': '',
        'draft_id': str(draft.id),
    })
    assert resp.status_code == 302
    assert db.session.get(RecipeDraft, draft.id).status == 'accepted'
