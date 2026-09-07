"""Bijsnijden moet uitgaan van het beeld ZOALS DE GEBRUIKER HET ZAG.

De browser past de EXIF-oriëntatie toe, PIL negeerde die tot nu toe. Een foto
met oriëntatie 6 (kwartslag) landde daardoor op een heel ander stuk van de
pagina dan aangewezen. Deze tests leggen het weergave-assenstelsel vast: de
fracties horen bij het rechtgezette beeld, plus de kwartslagen die de gebruiker
zelf draaide.
"""
import io
import os

import pytest
from PIL import Image

from weekmenu.extensions import db
from weekmenu.models import DumpJob, Recipe, RecipeDraft
from weekmenu.services.images import (crop_image, normaliseer_orientatie,
                                      parse_crop_body)

ROOD = (220, 20, 20)
GROEN = (20, 200, 20)
BLAUW = (20, 20, 220)
GEEL = (230, 230, 20)


def _vlakkenfoto(orientatie=None):
    """Een liggende 80x40-foto met vier herkenbare kwadranten.

    Linksboven rood, rechtsboven groen, linksonder blauw, rechtsonder geel.
    Met `orientatie` krijgt het bestand die EXIF-tag mee zonder dat de pixels
    veranderen -- precies zoals een telefoon het opslaat.
    """
    im = Image.new('RGB', (80, 40))
    im.paste(ROOD, (0, 0, 40, 20))
    im.paste(GROEN, (40, 0, 80, 20))
    im.paste(BLAUW, (0, 20, 40, 40))
    im.paste(GEEL, (40, 20, 80, 40))
    buf = io.BytesIO()
    if orientatie:
        exif = im.getexif()
        exif[274] = orientatie
        im.save(buf, 'JPEG', quality=95, subsampling=0, exif=exif)
    else:
        im.save(buf, 'JPEG', quality=95, subsampling=0)
    return buf.getvalue()


def _schrijf_vlakkenfoto(app, naam, orientatie=None):
    pad = os.path.join(app.static_folder, 'uploads', naam)
    os.makedirs(os.path.dirname(pad), exist_ok=True)
    with open(pad, 'wb') as fh:
        fh.write(_vlakkenfoto(orientatie))
    return 'static/uploads/' + naam


def _concept(**velden):
    """Een concept met de klus eromheen; job_id is verplicht in het model."""
    job_id = 'job-crop-' + str(len(db.session.query(DumpJob).all()) + 1)
    db.session.add(DumpJob(id=job_id, status='done'))
    draft = RecipeDraft(job_id=job_id, status='pending', **velden)
    db.session.add(draft)
    db.session.commit()
    return draft


def _open(app, rel_pad):
    return Image.open(os.path.join(app.static_folder, rel_pad.replace('static/', '', 1)))


def _lijkt_op(pixel, kleur, marge=45):
    return all(abs(a - b) <= marge for a, b in zip(pixel[:3], kleur))


def _midden(im):
    return im.convert('RGB').getpixel((im.width // 2, im.height // 2))


# --- het weergave-assenstelsel -------------------------------------------


def test_crop_volgt_de_kwartslag_van_orientatie_6(app):
    """Oriëntatie 6 = de kijker draait het beeld een kwartslag met de klok mee.

    De liggende 80x40 wordt dan een staande 40x80 waarin het rode kwadrant
    rechtsboven zit. Wie rechtsboven aanwijst hoort rood te krijgen; op de
    ruwe pixels zou daar groen zitten.
    """
    src = _schrijf_vlakkenfoto(app, 'staand6.jpg', orientatie=6)
    uit = _open(app, crop_image(src, 0.5, 0.0, 0.5, 0.5))
    assert uit.size == (20, 40)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_crop_volgt_de_halve_slag_van_orientatie_3(app):
    """Oriëntatie 3 = een halve slag; linksboven toont dan het gele kwadrant."""
    src = _schrijf_vlakkenfoto(app, 'omgekeerd3.jpg', orientatie=3)
    uit = _open(app, crop_image(src, 0.0, 0.0, 0.5, 0.5))
    assert uit.size == (40, 20)
    assert _lijkt_op(_midden(uit), GEEL), _midden(uit)


def test_crop_zonder_orientatietag_blijft_zoals_het_was(app):
    """Zonder tag verandert er niets; de 144 ongetagde bestanden mogen niet schuiven."""
    src = _schrijf_vlakkenfoto(app, 'kaal.jpg')
    uit = _open(app, crop_image(src, 0.0, 0.0, 0.5, 0.5))
    assert uit.size == (40, 20)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_crop_van_onleesbaar_bestand_geeft_nette_melding(app):
    """De kapotte jpg's in static/uploads mogen geen 500 opleveren."""
    pad = os.path.join(app.static_folder, 'uploads', 'stuk.jpg')
    with open(pad, 'wb') as fh:
        fh.write(b'\xff\xd8\xff\xe0 dit is geen jpeg')
    with pytest.raises(ValueError):
        crop_image('static/uploads/stuk.jpg', 0.0, 0.0, 1.0, 1.0)


# --- de draaiknop ---------------------------------------------------------


def test_rotatie_90_draait_met_de_klok_mee(app):
    """rotate=90 betekent hetzelfde als in de browser: met de klok mee."""
    src = _schrijf_vlakkenfoto(app, 'draai90.jpg')
    uit = _open(app, crop_image(src, 0.5, 0.0, 0.5, 0.5, 90))
    assert uit.size == (20, 40)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_rotatie_180_zet_rood_rechtsonder(app):
    src = _schrijf_vlakkenfoto(app, 'draai180.jpg')
    uit = _open(app, crop_image(src, 0.5, 0.5, 0.5, 0.5, 180))
    assert uit.size == (40, 20)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_rotatie_270_draait_de_andere_kant_op(app):
    src = _schrijf_vlakkenfoto(app, 'draai270.jpg')
    uit = _open(app, crop_image(src, 0.0, 0.5, 0.5, 0.5, 270))
    assert uit.size == (20, 40)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_rotatie_komt_bovenop_de_exif_stand(app):
    """De draai van de gebruiker telt op bij de stand die EXIF al gaf.

    Oriëntatie 6 zet rood rechtsboven; nog een kwartslag met de klok mee zet
    rood rechtsonder in een weer liggend beeld.
    """
    src = _schrijf_vlakkenfoto(app, 'zes_plus_negentig.jpg', orientatie=6)
    uit = _open(app, crop_image(src, 0.5, 0.5, 0.5, 0.5, 90))
    assert uit.size == (40, 20)
    assert _lijkt_op(_midden(uit), ROOD), _midden(uit)


def test_parse_crop_body_leest_de_rotatie(app):
    basis = {'x': 0, 'y': 0, 'width': 1, 'height': 1}
    assert parse_crop_body(basis) == (0.0, 0.0, 1.0, 1.0, 0)
    assert parse_crop_body(dict(basis, rotate=90))[4] == 90
    assert parse_crop_body(dict(basis, rotate=180))[4] == 180
    assert parse_crop_body(dict(basis, rotate=-90))[4] == 270
    assert parse_crop_body(dict(basis, rotate=450))[4] == 90
    assert parse_crop_body(dict(basis, rotate=0))[4] == 0


def test_parse_crop_body_weigert_een_halve_kwartslag(app):
    """45 graden kunnen we niet uitvoeren; stilzwijgend negeren zou het

    verkeerde stuk uitsnijden, dus liever een nette 400.
    """
    basis = {'x': 0, 'y': 0, 'width': 1, 'height': 1}
    for onzin in (45, 1, 'schuin', float('nan'), 89.9):
        assert parse_crop_body(dict(basis, rotate=onzin)) is None, onzin


def test_eindpunten_geven_400_bij_een_ongeldige_rotatie(app, client):
    src = _schrijf_vlakkenfoto(app, 'endpoint45.jpg')
    recipe = Recipe(name='Schuin', image_path=src)
    db.session.add(recipe)
    db.session.commit()
    draft = _concept(name='Schuin', image_path=src)
    body = {'x': 0, 'y': 0, 'width': 1, 'height': 1, 'rotate': 45}
    assert client.post(f'/recipe/{recipe.id}/crop', json=body).status_code == 400
    assert client.post(f'/dump/draft/{draft.id}/crop', json=body).status_code == 400


def test_eindpunten_voeren_een_kwartslag_uit(app, client):
    src = _schrijf_vlakkenfoto(app, 'endpoint90.jpg')
    recipe = Recipe(name='Gedraaid', image_path=src)
    db.session.add(recipe)
    db.session.commit()
    draft = _concept(name='Gedraaid', image_path=src)
    body = {'x': 0.5, 'y': 0, 'width': 0.5, 'height': 0.5, 'rotate': 90}

    resp = client.post(f'/recipe/{recipe.id}/crop', json=body)
    assert resp.status_code == 200
    uit = _open(app, resp.get_json()['image_path'])
    assert uit.size == (20, 40) and _lijkt_op(_midden(uit), ROOD)

    resp = client.post(f'/dump/draft/{draft.id}/crop', json=body)
    assert resp.status_code == 200
    uit = _open(app, resp.get_json()['image_path'])
    assert uit.size == (20, 40) and _lijkt_op(_midden(uit), ROOD)


# --- normaliseren bij binnenkomst ----------------------------------------


def test_normaliseer_orientatie_bakt_de_draai_in_de_pixels():
    data, ext = normaliseer_orientatie(_vlakkenfoto(orientatie=6), '.jpg')
    assert ext == '.jpg'
    im = Image.open(io.BytesIO(data))
    assert im.size == (40, 80)  # staand, dus de draai zit nu in de pixels
    assert im.getexif().get(274, 1) == 1
    assert _lijkt_op(im.convert('RGB').getpixel((30, 10)), ROOD)


def test_normaliseer_orientatie_spiegelt_ook(app):
    """Oriëntatie 2 is een spiegeling; met geen enkele serverdraai te herstellen."""
    data, _ = normaliseer_orientatie(_vlakkenfoto(orientatie=2), '.jpg')
    im = Image.open(io.BytesIO(data)).convert('RGB')
    assert im.size == (80, 40)
    assert _lijkt_op(im.getpixel((60, 10)), ROOD)  # rood staat nu rechtsboven


def test_normaliseer_orientatie_laat_ongetagde_bytes_met_rust():
    ruw = _vlakkenfoto()
    data, ext = normaliseer_orientatie(ruw, '.png')
    assert data is ruw and ext == '.png'


def test_normaliseer_orientatie_laat_onleesbare_bytes_met_rust():
    data, ext = normaliseer_orientatie(b'geen afbeelding', '.jpg')
    assert data == b'geen afbeelding' and ext == '.jpg'


def test_upload_in_nieuw_recept_wordt_rechtgezet(app, client):
    resp = client.post('/recipe/new', data={
        'name': 'Rechtop', 'serves': '2', 'page': '',
        'image': (io.BytesIO(_vlakkenfoto(orientatie=6)), 'foto.jpg'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    recipe = Recipe.query.filter_by(name='Rechtop').first()
    im = _open(app, recipe.image_path)
    assert im.size == (40, 80)
    assert im.getexif().get(274, 1) == 1


def test_upload_in_aanpasformulier_wordt_rechtgezet(app, client):
    recipe = Recipe(name='Aanpassen')
    db.session.add(recipe)
    db.session.commit()
    resp = client.post(f'/recipe/{recipe.id}/edit', data={
        'name': 'Aanpassen', 'serves': '2', 'page': '',
        'image': (io.BytesIO(_vlakkenfoto(orientatie=6)), 'foto.jpg'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    im = _open(app, db.session.get(Recipe, recipe.id).image_path)
    assert im.size == (40, 80)
    assert im.getexif().get(274, 1) == 1


def test_dump_foto_wordt_rechtgezet_en_op_de_nieuwe_bytes_gehasht(app):
    """De md5 gaat over de genormaliseerde bytes, niet over het bronbestand."""
    import hashlib

    from weekmenu.services.dump import _resolve_image

    bron = os.path.join(app.static_folder, 'bron_foto.jpg')
    ruw = _vlakkenfoto(orientatie=6)
    with open(bron, 'wb') as fh:
        fh.write(ruw)

    rel = _resolve_image('job1', 'p1', {'p1': (bron, None)})
    assert rel is not None
    im = _open(app, rel)
    assert im.size == (40, 80)
    assert im.getexif().get(274, 1) == 1
    assert os.path.basename(rel) != hashlib.md5(ruw).hexdigest() + '.jpg'
    with open(os.path.join(app.static_folder, rel.replace('static/', '', 1)), 'rb') as fh:
        assert os.path.basename(rel) == hashlib.md5(fh.read()).hexdigest() + '.jpg'


# --- het origineel moet mee naar het recept -------------------------------


def test_origineel_gaat_mee_bij_accepteren_van_een_concept(app, client):
    draft = _concept(name='Met origineel', instructions='Roeren.',
                     ingredients_json='[{"name": "ui", "amount": 1, "unit": "st"}]',
                     image_path='static/uploads/klein.jpg',
                     original_image_path='static/uploads/heel.jpg')
    resp = client.post(f'/dump/draft/{draft.id}/accept', json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    recipe = db.session.get(Recipe, resp.get_json()['recipe_id'])
    assert recipe.original_image_path == 'static/uploads/heel.jpg'


def test_origineel_gaat_mee_bij_opslaan_vanuit_het_formulier(app, client):
    draft = _concept(name='Uit formulier',
                     image_path='static/uploads/klein.jpg',
                     original_image_path='static/uploads/heel.jpg')
    resp = client.post('/recipe/new', data={
        'name': 'Uit formulier', 'serves': '2', 'page': '',
        'draft_id': str(draft.id),
        'image_path_imported': 'static/uploads/klein.jpg',
    })
    assert resp.status_code == 302
    recipe = Recipe.query.filter_by(name='Uit formulier').first()
    assert recipe.image_path == 'static/uploads/klein.jpg'
    assert recipe.original_image_path == 'static/uploads/heel.jpg'
    assert db.session.get(RecipeDraft, draft.id).status == 'accepted'


def test_verse_upload_erft_het_origineel_van_het_concept_niet(app, client):
    """Wie zelf een nieuw bestand kiest, wil niet de oude pagina als origineel."""
    draft = _concept(name='Eigen foto',
                     image_path='static/uploads/klein.jpg',
                     original_image_path='static/uploads/heel.jpg')
    client.post('/recipe/new', data={
        'name': 'Eigen foto', 'serves': '2', 'page': '',
        'draft_id': str(draft.id),
        'image_path_imported': 'static/uploads/klein.jpg',
        'image': (io.BytesIO(_vlakkenfoto()), 'eigen.jpg'),
    }, content_type='multipart/form-data')
    recipe = Recipe.query.filter_by(name='Eigen foto').first()
    assert recipe.original_image_path is None


def test_nieuw_bestand_in_het_aanpasformulier_wist_het_oude_origineel(app, client):
    """Anders wijst de bijsnijdknop na het vervangen nog naar de vorige pagina.

    Het formulier opent de crop op `original_image_path or image_path`; bleef
    het oude origineel staan, dan snijd je uit een beeld dat niets meer met dit
    recept te maken heeft.
    """
    recipe = Recipe(name='Vervangen', image_path='static/uploads/klein.jpg',
                    original_image_path='static/uploads/heel.jpg')
    db.session.add(recipe)
    db.session.commit()
    client.post(f'/recipe/{recipe.id}/edit', data={
        'name': 'Vervangen', 'serves': '2', 'page': '',
        'image': (io.BytesIO(_vlakkenfoto()), 'nieuw.jpg'),
    }, content_type='multipart/form-data')
    r = db.session.get(Recipe, recipe.id)
    assert r.image_path != 'static/uploads/klein.jpg'
    assert r.original_image_path is None
