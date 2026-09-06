"""Het aanpasformulier van een concept: bijsnijden en het origineel erbij."""
from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft


def test_formulier_uit_concept_heeft_bijsnijden_en_origineel(app, client):
    db.session.add(DumpJob(id='j', status='done', mode='kaart'))
    db.session.add(RecipeDraft(id=7, job_id='j', name='Kaart', ingredients_json='[]', status='pending',
                               image_path='static/uploads/voor.jpg', original_image_path='static/uploads/voor-orig.jpg',
                               back_image_path='static/uploads/achter.jpg'))
    db.session.commit()
    html = client.get('/recipe/new?draft=7').get_data(as_text=True)
    assert 'id="cropModal"' in html                      # de modal is ingeladen
    assert 'id="importedCropBtn"' in html and 'Bijsnijden' in html
    assert 'id="importedOriginalLink"' in html and 'id="importedBackLink"' in html
    # het concept levert alles wat het formulier daarvoor nodig heeft
    data = client.get('/dump/draft/7').get_json()
    assert data['original_image_path'] == 'static/uploads/voor-orig.jpg'
    assert data['back_image_path'] == 'static/uploads/achter.jpg'
