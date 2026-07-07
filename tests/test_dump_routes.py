import json
import os

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


def test_serialize_draft_includes_original_image_path(app, client):
    draft = _make_draft(app)
    draft.original_image_path = 'static/uploads/orig.png'
    db.session.commit()
    data = client.get(f'/dump/draft/{draft.id}').get_json()
    assert data['original_image_path'] == 'static/uploads/orig.png'


def _make_draft_with_image(app, job_id=None):
    from PIL import Image
    import uuid
    if job_id is None:
        job_id = f'job-{uuid.uuid4().hex[:8]}'
    job = DumpJob(id=job_id, status='done')
    draft = RecipeDraft(
        job_id=job_id, name='Dal', serves=2,
        instructions='Stap 1. Kook de linzen.',
        ingredients_json=json.dumps([
            {'name': 'rode linzen', 'amount': 200, 'unit': 'g', 'category': 'overig'},
            {'name': 'ui', 'amount': 1, 'unit': 'stuks', 'category': 'groente'},
        ]),
        status='pending',
    )
    db.session.add_all([job, draft])
    db.session.commit()
    uploads = os.path.join(app.static_folder, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    img = Image.new('RGBA', (100, 80), (200, 30, 30, 255))  # PNG met alpha
    img.save(os.path.join(uploads, 'bron.png'))
    draft.image_path = 'static/uploads/bron.png'
    db.session.commit()
    return draft


def test_crop_creates_new_image_and_keeps_original(app, client):
    from PIL import Image
    draft = _make_draft_with_image(app)
    resp = client.post(f'/dump/draft/{draft.id}/crop',
                       json={'x': 0.25, 'y': 0.25, 'width': 0.5, 'height': 0.5})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'success'
    new_path = data['image_path']
    assert new_path != 'static/uploads/bron.png'
    assert new_path.endswith('.jpg')

    d = db.session.get(RecipeDraft, draft.id)
    assert d.image_path == new_path
    assert d.original_image_path == 'static/uploads/bron.png'

    out = Image.open(os.path.join(app.static_folder, new_path.replace('static/', '', 1)))
    assert out.size == (50, 40)

    # tweede crop snijdt weer uit het 100x80-origineel
    resp2 = client.post(f'/dump/draft/{draft.id}/crop',
                        json={'x': 0, 'y': 0, 'width': 1, 'height': 1})
    assert resp2.status_code == 200
    d = db.session.get(RecipeDraft, draft.id)
    assert d.original_image_path == 'static/uploads/bron.png'
    out2 = Image.open(os.path.join(app.static_folder, d.image_path.replace('static/', '', 1)))
    assert out2.size == (100, 80)


def test_crop_invalid_coords_and_missing_image(app, client):
    draft = _make_draft_with_image(app)
    for bad in [{'x': -0.1, 'y': 0, 'width': 0.5, 'height': 0.5},
                {'x': 0.8, 'y': 0, 'width': 0.5, 'height': 0.5},
                {'x': 0, 'y': 0, 'width': 0, 'height': 0.5},
                {'x': 0, 'y': 0}]:
        assert client.post(f'/dump/draft/{draft.id}/crop', json=bad).status_code == 400

    kaal = _make_draft(app)  # zonder afbeelding
    assert client.post(f'/dump/draft/{kaal.id}/crop',
                       json={'x': 0, 'y': 0, 'width': 1, 'height': 1}).status_code == 400
