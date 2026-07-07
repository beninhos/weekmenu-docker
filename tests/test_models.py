import json

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft


def test_dumpjob_and_draft_roundtrip(app):
    job = DumpJob(id='abc-123', status='processing')
    db.session.add(job)
    db.session.flush()

    draft = RecipeDraft(
        job_id='abc-123', name='Shakshuka', serves=4,
        instructions='Stap 1. Doe dingen.',
        ingredients_json=json.dumps([{'name': 'ei', 'amount': 3, 'unit': 'stuks', 'category': 'zuivel'}]),
        image_path=None, source_page=2, status='pending',
    )
    db.session.add(draft)
    db.session.flush()

    assert draft.id is not None
    assert draft.job.status == 'processing'
    assert job.drafts[0].name == 'Shakshuka'
