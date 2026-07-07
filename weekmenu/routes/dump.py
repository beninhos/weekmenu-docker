import json

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from weekmenu.extensions import db
from weekmenu.models import Cookbook, DumpJob, Recipe, RecipeDraft, RecipeIngredient
from weekmenu.services.dump import retry_dump_job, start_dump_job
from weekmenu.services.recipes import _resolve_or_create_ingredient
from weekmenu.services.units import _normalize_ri_unit

bp = Blueprint('dump', __name__)


def serialize_draft(d):
    return {
        'id': d.id,
        'job_id': d.job_id,
        'name': d.name,
        'serves': d.serves,
        'instructions': d.instructions,
        'ingredients': json.loads(d.ingredients_json or '[]'),
        'image_path': d.image_path,
        'original_image_path': d.original_image_path,
        'status': d.status,
    }


@bp.route('/dump')
def dump_page():
    drafts = RecipeDraft.query.filter_by(status='pending').order_by(RecipeDraft.created_at).all()
    jobs = DumpJob.query.filter(DumpJob.status.in_(['processing', 'error'])) \
                        .order_by(DumpJob.created_at.desc()).all()
    cookbooks = Cookbook.query.filter_by(is_archived=False).order_by(Cookbook.name).all()
    return render_template('dump.html',
                           drafts=[serialize_draft(d) for d in drafts],
                           jobs=[{'id': j.id, 'status': j.status, 'error_message': j.error_message} for j in jobs],
                           cookbooks=cookbooks)


@bp.route('/dump/upload', methods=['POST'])
def dump_upload():
    files = request.files.getlist('files')
    try:
        job_id = start_dump_job(files)
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
    return jsonify({'status': 'success', 'job_id': job_id})


@bp.route('/dump/share', methods=['POST'])
def dump_share():
    """PWA share-target: bestanden delen vanaf de telefoon."""
    files = request.files.getlist('files')
    try:
        start_dump_job(files)
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


@bp.route('/dump/draft/<int:id>/accept', methods=['POST'])
def dump_draft_accept(id):
    d = RecipeDraft.query.get_or_404(id)
    body = request.get_json(silent=True) or {}
    cookbook_id = body.get('cookbook_id') or None

    recipe = Recipe(name=d.name, serves=d.serves, cookbook_id=cookbook_id,
                    page=d.source_page, image_path=d.image_path,
                    instructions=d.instructions or None)
    db.session.add(recipe)
    db.session.flush()

    for ing in json.loads(d.ingredients_json or '[]'):
        ingredient = _resolve_or_create_ingredient(ing.get('name', ''), ing.get('category'))
        if not ingredient:
            continue
        raw_amount = float(ing['amount']) if ing.get('amount') else 0
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
