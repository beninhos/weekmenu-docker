import json

from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, url_for)

from weekmenu.extensions import db
from weekmenu.models import Cookbook, DumpJob, Recipe, RecipeDraft, RecipeIngredient
from weekmenu.services.dump import retry_dump_job, start_dump_job
from weekmenu.services.pantry import annotate_pantry_status
from weekmenu.services.recipes import _resolve_or_create_ingredient
from weekmenu.services.units import _normalize_ri_unit

bp = Blueprint('dump', __name__)


def serialize_draft(d):
    ingredienten = annotate_pantry_status(json.loads(d.ingredients_json or '[]'))
    for i in ingredienten:
        # De kaart zegt 'zelf toevoegen': vinkje alvast aan, tenzij de
        # voorraad het al wist.
        if i.get('kaart_voorraad') and not i.get('in_pantry'):
            i['in_pantry'] = True
    return {
        'id': d.id,
        'job_id': d.job_id,
        'name': d.name,
        'serves': d.serves,
        'prep_time': d.prep_time,
        'instructions': d.instructions,
        'ingredients': ingredienten,
        'image_path': d.image_path,
        'original_image_path': d.original_image_path,
        'back_image_path': d.back_image_path,
        'source_page': d.source_page,
        'status': d.status,
        'meldingen': json.loads(d.meldingen_json or '[]'),
    }


@bp.route('/dump')
def dump_page():
    drafts = RecipeDraft.query.filter_by(status='pending').order_by(RecipeDraft.created_at).all()
    # Ook een geslaagde batch met een melding blijft zichtbaar: anders is de
    # waarschuwing dat er pagina's zijn kwijtgeraakt weg zodra je de pagina
    # herlaadt, en dat is precies het geval waarin je hem nodig hebt. Maar
    # alleen zolang er van die batch nog iets na te kijken is: anders blijft
    # de melding van een batch van dagen geleden bovenaan staan.
    nog_open = {d.job_id for d in drafts}
    jobs = DumpJob.query.filter(db.or_(DumpJob.status.in_(['processing', 'error']),
                                       db.and_(DumpJob.warning.isnot(None),
                                               DumpJob.id.in_(nog_open)))) \
                        .order_by(DumpJob.created_at.desc()).all()
    cookbooks = Cookbook.query.filter_by(is_archived=False).order_by(Cookbook.name).all()
    return render_template('dump.html',
                           drafts=[serialize_draft(d) for d in drafts],
                           jobs=[{'id': j.id, 'status': j.status,
                                  'error_message': j.error_message,
                                  'warning': j.warning} for j in jobs],
                           cookbooks=cookbooks)


@bp.route('/dump/upload', methods=['POST'])
def dump_upload():
    files = request.files.getlist('files')
    try:
        job_id = start_dump_job(files, mode=request.form.get('mode', 'boek'))
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    return jsonify({'status': 'success', 'job_id': job_id})


@bp.route('/dump/share', methods=['POST'])
def dump_share():
    """PWA share-target: bestanden delen vanaf de telefoon."""
    files = request.files.getlist('files')
    try:
        start_dump_job(files, mode=request.form.get('mode', 'boek'))
    except ValueError:
        pass  # lege share: gewoon naar de pagina
    return redirect(url_for('dump.dump_page'), code=303)


@bp.route('/dump/status/<job_id>')
def dump_status(job_id):
    job = DumpJob.query.get_or_404(job_id)
    drafts = RecipeDraft.query.filter_by(job_id=job_id, status='pending') \
                              .order_by(RecipeDraft.created_at).all()
    return jsonify({'status': job.status,
                    'error_message': job.error_message,
                    'warning': job.warning,
                    'page_count': job.page_count,
                    'drafts': [serialize_draft(d) for d in drafts]})


@bp.route('/dump/job/<job_id>/retry', methods=['POST'])
def dump_retry(job_id):
    retry_dump_job(job_id)
    return jsonify({'status': 'success'})


@bp.route('/dump/draft/<int:id>')
def dump_draft(id):
    d = RecipeDraft.query.get_or_404(id)
    payload = serialize_draft(d)
    payload.update({'status': 'success', 'draft_id': d.id, 'url': None})
    return jsonify(payload)


def _hoeveelheid_ontbreekt(ingredienten):
    """Regels met een maat maar zonder getal ('g kipfilets').

    Die mogen er niet stilzwijgend door: de kolom recipe_ingredient.amount kan
    geen leegte bevatten, dus zo'n regel zou als 0 g worden opgeslagen. Op de
    boodschappenlijst telt hij dan voor niets mee, en niets in de app laat nog
    zien dat er ooit een getal had moeten staan. Een ingrediënt zonder maat
    ('olijfolie', 'peper') is iets anders — daar hoort geen hoeveelheid bij.
    """
    return [i.get('name', '?') for i in ingredienten
            if i.get('amount') in (None, '') and (i.get('unit') or '').strip()]


def _bereiding_ontbreekt(instructions):
    """Een concept zonder bereidingstekst zou stappenloos in de database komen.

    De nakijkkaart toont de bereiding niet als hij leeg is en er is verder
    niets dat dat verraadt, dus dit is dezelfde stille val als de ontbrekende
    hoeveelheid hierboven.
    """
    return not (instructions or '').strip()


@bp.route('/dump/draft/<int:id>/accept', methods=['POST'])
def dump_draft_accept(id):
    d = RecipeDraft.query.get_or_404(id)
    if d.status != 'pending':
        # Twee tabbladen open, of tweemaal geklikt: zonder deze controle komt
        # hetzelfde recept er een tweede keer in.
        return jsonify({'status': 'error',
                        'message': 'Dit concept is al afgehandeld.'}), 409

    body = request.get_json(silent=True) or {}
    cookbook_id = body.get('cookbook_id') or None

    ingredienten = json.loads(d.ingredients_json or '[]')
    ontbreekt = _hoeveelheid_ontbreekt(ingredienten)
    if ontbreekt:
        return jsonify({
            'status': 'error',
            'message': 'Bij {} ontbreekt de hoeveelheid. Kies "Aanpassen" en vul '
                       'hem aan, anders komt het ingrediënt op 0 in de '
                       'boodschappenlijst.'.format(', '.join(ontbreekt[:4])),
        }), 409

    if _bereiding_ontbreekt(d.instructions):
        return jsonify({
            'status': 'error',
            'message': 'De bereiding ontbreekt. Kies "Aanpassen" en vul '
                       'hem aan.',
        }), 409

    recipe = Recipe(name=d.name, serves=d.serves, cookbook_id=cookbook_id,
                    page=d.source_page, image_path=d.image_path,
                    instructions=d.instructions or None,
                    prep_time=d.prep_time)
    db.session.add(recipe)
    db.session.flush()

    for ing in ingredienten:
        ingredient = _resolve_or_create_ingredient(ing.get('name', ''), ing.get('category'))
        if not ingredient:
            current_app.logger.warning(
                'Ingredient %r overgeslagen bij concept %s', ing.get('name'), d.id)
            continue
        try:
            raw_amount = float(ing['amount']) if ing.get('amount') else 0
        except (TypeError, ValueError):
            raw_amount = 0
        norm_unit, norm_amount = _normalize_ri_unit(ingredient, ing.get('unit') or '', raw_amount)
        db.session.add(RecipeIngredient(recipe_id=recipe.id, ingredient_id=ingredient.id,
                                        amount=norm_amount, unit=norm_unit))

    d.status = 'accepted'
    db.session.commit()
    return jsonify({'status': 'success', 'recipe_id': recipe.id})


@bp.route('/dump/draft/<int:id>/reject', methods=['POST'])
def dump_draft_reject(id):
    d = RecipeDraft.query.get_or_404(id)
    d.status = 'rejected'
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/dump/draft/<int:id>/crop', methods=['POST'])
def dump_draft_crop(id):
    from weekmenu.services.images import parse_crop_body, crop_image
    d = RecipeDraft.query.get_or_404(id)
    coords = parse_crop_body(request.get_json(silent=True) or {})
    if coords is None:
        return jsonify({'status': 'error', 'message': 'Ongeldige crop-coördinaten'}), 400
    src_rel = d.original_image_path or d.image_path
    if not src_rel:
        return jsonify({'status': 'error', 'message': 'Geen afbeelding om bij te snijden'}), 400
    try:
        new_path = crop_image(src_rel, *coords)
    except FileNotFoundError:
        return jsonify({'status': 'error', 'message': 'Bronafbeelding niet gevonden'}), 404
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    if not d.original_image_path:
        d.original_image_path = d.image_path
    d.image_path = new_path
    db.session.commit()
    return jsonify({'status': 'success', 'image_path': d.image_path})
