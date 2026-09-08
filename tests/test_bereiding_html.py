"""De bereiding moet zijn regelindeling houden op weg naar het recept.

Het concept bewaart de bereiding als platte tekst met regeleinden; de kopjes
uit de OCR staan op eigen regels. Een \\n is in HTML gewone witruimte, dus
zodra die tekst ergens in een innerHTML belandt loopt de hele bereiding aan
elkaar -- en schrijft Quill bij de eerste keer opslaan diezelfde ene lap terug
naar de database. Deze tests leggen vast waar platte tekst HTML wordt (één
plek: services/bereiding.py) en dat de kopjes de hele keten overleven.
"""
import re

from sqlalchemy import create_engine, text

from weekmenu.extensions import db
from weekmenu.models import DumpJob, Recipe, RecipeDraft

KOPJESTEKST = (
    '1. Snijden\n'
    'Snijd de ui in halve ringen.\n'
    'Snijd de paprika in reepjes.\n'
    '2. Koken\n'
    'Kook de rijst in 12 minuten gaar.\n'
    'Giet af en houd warm.\n'
    '3. Bakken\n'
    'Verhit de olie in een wok.\n'
    'Bak de ui 3 minuten.\n'
    '4. Serveren\n'
    'Schep alles door elkaar.\n'
    'Serveer met een partje limoen.'
)


def _regels_zoals_de_browser(html):
    """De regels die de gebruiker ziet als deze HTML in een div staat.

    Een regeleinde in de bron is voor de browser witruimte; alleen <br> en het
    einde van een blok-element beginnen een nieuwe regel. Precies dat verschil
    is waar de kopjes op stukliepen, dus de test doet het net zo.
    """
    tekst = html.replace('\n', ' ')
    tekst = re.sub(r'(?i)<br\s*/?>', '\n', tekst)
    tekst = re.sub(r'(?i)</(p|div|li|h[1-6]|ol|ul|blockquote|pre)>', '\n', tekst)
    tekst = re.sub(r'<[^>]+>', '', tekst)
    tekst = tekst.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    return [r.strip() for r in tekst.split('\n') if r.strip()]


def _concept(**velden):
    job_id = 'job-bereiding-' + str(len(db.session.query(DumpJob).all()) + 1)
    db.session.add(DumpJob(id=job_id, status='done'))
    draft = RecipeDraft(job_id=job_id, status='pending', **velden)
    db.session.add(draft)
    db.session.commit()
    return draft


# --- de omzetting zelf ----------------------------------------------------


def test_elke_regel_wordt_een_eigen_blok():
    from weekmenu.services.bereiding import bereiding_naar_html

    html = bereiding_naar_html('Stap 1\nStap 2\nStap 3')
    assert _regels_zoals_de_browser(html) == ['Stap 1', 'Stap 2', 'Stap 3']


def test_lege_regel_blijft_een_lege_regel():
    """Quill schrijft een witregel als <p><br></p>; anders valt hij weg bij

    de eerste keer opslaan en schuift de indeling alsnog dicht.
    """
    from weekmenu.services.bereiding import bereiding_naar_html

    assert bereiding_naar_html('Boven\n\nOnder') == '<p>Boven</p><p><br></p><p>Onder</p>'


def test_html_uit_het_formulier_blijft_ongemoeid():
    """De 49 recepten die al uit Quill komen mogen geen extra witruimte krijgen."""
    from weekmenu.services.bereiding import bereiding_naar_html

    quill = '<p>Stap 1</p><p>Stap 2</p>'
    assert bereiding_naar_html(quill) == quill
    lijst = '<ol><li>Snijden</li>\n<li>Koken</li></ol>'
    assert bereiding_naar_html(lijst) == lijst


def test_leeg_blijft_leeg():
    from weekmenu.services.bereiding import bereiding_naar_html

    assert bereiding_naar_html(None) is None
    assert bereiding_naar_html('') == ''
    assert bereiding_naar_html('   ') == '   '


def test_platte_tekst_met_tekens_die_op_html_lijken_wordt_ontsmet():
    """Wat plat binnenkomt gaat als tekst de database in, niet als opmaak.

    De detailkaart zet de bereiding met innerHTML in de pagina; zonder deze
    ontsmetting zou OCR-tekst met een < erin daar als opmaak landen.
    """
    from weekmenu.services.bereiding import bereiding_naar_html

    html = bereiding_naar_html('Verwarm tot <200 graden\n<script>alert(1)</script>')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    assert _regels_zoals_de_browser(html) == ['Verwarm tot <200 graden', '<script>alert(1)</script>']


def test_een_kleiner_dan_teken_maakt_er_nog_geen_html_van():
    """'a < b' bevat de letter b achter een <; dat is geen opmaak.

    Zou het daarop als HTML worden gezien, dan bleef de tekst plat staan --
    precies de fout die we hier dichttimmeren -- én zou hij ongeschonden in
    een innerHTML belanden.
    """
    from weekmenu.services.bereiding import bereiding_naar_html

    html = bereiding_naar_html('Laat inkoken tot a < b\nRoer door')
    assert _regels_zoals_de_browser(html) == ['Laat inkoken tot a < b', 'Roer door']


def test_een_los_stuk_tekst_zonder_regeleinden_wordt_ook_html():
    """Anders is de bereiding in de database soms wel en soms geen HTML."""
    from weekmenu.services.bereiding import bereiding_naar_html

    assert bereiding_naar_html('Alles in één pan.') == '<p>Alles in één pan.</p>'


# --- de hele keten: concept -> overnemen -> bewerken ----------------------


def test_kopjes_overleven_overnemen_en_een_ronde_door_bewerken(app, client):
    draft = _concept(name='Wokschotel', serves=4, instructions=KOPJESTEKST,
                     ingredients_json='[{"name": "ui", "amount": 1, "unit": "st"}]')

    resp = client.post(f'/dump/draft/{draft.id}/accept', json={})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    recipe_id = resp.get_json()['recipe_id']

    # 1. zoals de gebruiker het krijgt: de receptdetailkaart haalt dit op en
    #    zet het met innerHTML in de pagina.
    payload = client.get(f'/api/recipe/{recipe_id}').get_json()
    regels = _regels_zoals_de_browser(payload['instructions'])
    assert regels == KOPJESTEKST.split('\n')
    for kopje in ('1. Snijden', '2. Koken', '3. Bakken', '4. Serveren'):
        assert kopje in regels

    # 2. één keer openen in Bewerken en opslaan: Quill krijgt dezelfde HTML
    #    binnen en stuurt hem onveranderd terug.
    resp = client.post(f'/recipe/{recipe_id}/edit', data={
        'name': 'Wokschotel', 'serves': '4', 'page': '',
        'instructions': payload['instructions'],
    })
    assert resp.status_code == 302
    opnieuw = client.get(f'/api/recipe/{recipe_id}').get_json()
    assert _regels_zoals_de_browser(opnieuw['instructions']) == KOPJESTEKST.split('\n')


def test_bereiding_uit_het_formulier_gaat_ongewijzigd_de_database_in(app, client):
    """Het aanpasformulier stuurt al HTML; die mag niet nog eens verpakt worden."""
    quill = '<p>1. Snijden</p><p>Snijd de ui.</p>'
    client.post('/recipe/new', data={
        'name': 'Uit het formulier', 'serves': '2', 'page': '',
        'instructions': quill,
    })
    assert Recipe.query.filter_by(name='Uit het formulier').first().instructions == quill


def test_het_concept_zelf_blijft_platte_tekst(app, client):
    """De nakijkkaart toont de bereiding met white-space:pre-wrap en esc().

    Die heeft de platte tekst nodig; het formulier krijgt er een tweede veld
    bij zodat beide dezelfde omzetting gebruiken.
    """
    draft = _concept(name='Concept', instructions=KOPJESTEKST)
    payload = client.get(f'/dump/draft/{draft.id}').get_json()
    assert payload['instructions'] == KOPJESTEKST
    assert _regels_zoals_de_browser(payload['instructions_html']) == KOPJESTEKST.split('\n')


# --- de recepten die er al zijn -------------------------------------------


def test_migratie_v20_zet_de_platte_recepten_om():
    from weekmenu.migrations import _migrate_v20
    engine = create_engine('sqlite://')
    with engine.connect() as conn:
        conn.execute(text('CREATE TABLE recipe (id INTEGER PRIMARY KEY, '
                          'name VARCHAR(100), instructions TEXT)'))
        conn.execute(text("INSERT INTO recipe (id, name, instructions) "
                          "VALUES (1, 'Plat', '1. Snijden\nSnijd de ui.')"))
        conn.execute(text("INSERT INTO recipe (id, name, instructions) "
                          "VALUES (2, 'Uit Quill', '<p>Stap 1</p><p>Stap 2</p>')"))
        conn.execute(text("INSERT INTO recipe (id, name, instructions) "
                          "VALUES (3, 'Leeg', NULL)"))
        _migrate_v20(conn)
        _migrate_v20(conn)  # idempotent

        rijen = dict(conn.execute(text('SELECT id, instructions FROM recipe')).fetchall())
        assert _regels_zoals_de_browser(rijen[1]) == ['1. Snijden', 'Snijd de ui.']
        assert rijen[2] == '<p>Stap 1</p><p>Stap 2</p>'
        assert rijen[3] is None
