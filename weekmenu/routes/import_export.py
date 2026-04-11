import io
import json
import os
import zipfile
from datetime import datetime, date

from flask import Blueprint, request, jsonify, send_file, current_app

from weekmenu.extensions import db
from weekmenu.models import Cookbook, Recipe, RecipeIngredient, Ingredient
from weekmenu.services.recipes import _resolve_or_create_ingredient
from weekmenu.services.units import _normalize_ri_unit

bp = Blueprint('import_export', __name__)


@bp.route('/export')
def export_data():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    recipes = Recipe.query.order_by(Recipe.name).all()

    data = {
        'version': 1,
        'exported_at': datetime.now().isoformat(),
        'cookbooks': [
            {'name': c.name, 'abbreviation': c.abbreviation}
            for c in cookbooks
        ],
        'recipes': [
            {
                'name': r.name,
                'serves': r.serves,
                'cookbook': r.cookbook.name if r.cookbook else None,
                'page': r.page,
                'is_favorite': r.is_favorite,
                'url': r.url,
                'instructions': r.instructions,
                'ingredients': [
                    {
                        'name': ri.ingredient.display,
                        'category': ri.ingredient.category,
                        'amount': ri.amount,
                        'unit': ri.unit,
                        'preparation': ri.preparation or '',
                    }
                    for ri in r.ingredients
                ]
            }
            for r in recipes
        ]
    }

    buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    buf.seek(0)
    filename = f"weekmenu_export_{date.today().strftime('%Y%m%d')}.json"
    return send_file(buf, mimetype='application/json', as_attachment=True, download_name=filename)


@bp.route('/import', methods=['POST'])
def import_data():
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({'status': 'error', 'message': 'Geen bestand geselecteerd'}), 400

        data = json.loads(file.read().decode('utf-8'))
        counts = {'cookbooks': 0, 'recipes': 0, 'ingredients': 0}

        for cb_data in data.get('cookbooks', []):
            if not Cookbook.query.filter_by(name=cb_data['name']).first():
                db.session.add(Cookbook(
                    name=cb_data['name'],
                    abbreviation=cb_data.get('abbreviation')
                ))
                counts['cookbooks'] += 1
        db.session.commit()

        for r_data in data.get('recipes', []):
            if Recipe.query.filter_by(name=r_data['name']).first():
                continue

            cookbook = Cookbook.query.filter_by(name=r_data['cookbook']).first() if r_data.get('cookbook') else None
            recipe = Recipe(
                name=r_data['name'],
                serves=r_data.get('serves', 4),
                cookbook_id=cookbook.id if cookbook else None,
                page=r_data.get('page'),
                is_favorite=r_data.get('is_favorite', False),
                url=r_data.get('url'),
                instructions=r_data.get('instructions')
            )
            db.session.add(recipe)
            db.session.flush()

            for ing_data in r_data.get('ingredients', []):
                ingredient = _resolve_or_create_ingredient(
                    ing_data['name'],
                    ing_data.get('category', 'Overig')
                )
                if not ingredient:
                    continue
                counts['ingredients'] += 1

                raw_amount = ing_data.get('amount', 0)
                norm_unit, norm_amount = _normalize_ri_unit(ingredient, ing_data.get('unit', ''), raw_amount)
                db.session.add(RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=norm_amount,
                    unit=norm_unit,
                    preparation=ing_data.get('preparation'),
                ))

            counts['recipes'] += 1

        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': f"{counts['cookbooks']} kookboeken, {counts['recipes']} recepten en {counts['ingredients']} ingrediënten geïmporteerd."
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/export/zip')
def export_zip():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    recipes = Recipe.query.order_by(Recipe.name).all()

    data = {
        'version': 2,
        'exported_at': datetime.now().isoformat(),
        'cookbooks': [
            {
                'name': c.name,
                'abbreviation': c.abbreviation,
                'image_filename': os.path.basename(c.image_path) if c.image_path else None,
                'is_archived': c.is_archived,
            }
            for c in cookbooks
        ],
        'recipes': [
            {
                'name': r.name,
                'serves': r.serves,
                'cookbook': r.cookbook.name if r.cookbook else None,
                'page': r.page,
                'is_favorite': r.is_favorite,
                'url': r.url,
                'instructions': r.instructions,
                'image_filename': os.path.basename(r.image_path) if r.image_path else None,
                'ingredients': [
                    {
                        'name': ri.ingredient.name,
                        'category': ri.ingredient.category,
                        'amount': ri.amount,
                        'unit': ri.unit,
                    }
                    for ri in r.ingredients
                ],
            }
            for r in recipes
        ],
    }

    buf = io.BytesIO()
    uploads_dir = os.path.join(current_app.root_path, 'static', 'uploads')
    image_filenames = set()
    for c in cookbooks:
        if c.image_path:
            image_filenames.add(os.path.basename(c.image_path))
    for r in recipes:
        if r.image_path:
            image_filenames.add(os.path.basename(r.image_path))

    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('weekmenu_export.json', json.dumps(data, ensure_ascii=False, indent=2))
        for fname in image_filenames:
            full_path = os.path.join(uploads_dir, fname)
            if os.path.isfile(full_path):
                zf.write(full_path, arcname=os.path.join('images', fname))

    buf.seek(0)
    filename = f"weekmenu_export_{date.today().strftime('%Y%m%d')}.zip"
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=filename)


@bp.route('/import/zip', methods=['POST'])
def import_zip():
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({'status': 'error', 'message': 'Geen bestand geselecteerd'}), 400

        buf = io.BytesIO(file.read())
        if not zipfile.is_zipfile(buf):
            return jsonify({'status': 'error', 'message': 'Ongeldig ZIP-bestand'}), 400

        buf.seek(0)
        counts = {'cookbooks': 0, 'recipes': 0, 'ingredients': 0, 'images': 0}
        uploads_dir = os.path.join(current_app.root_path, 'static', 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)

        with zipfile.ZipFile(buf, 'r') as zf:
            if 'weekmenu_export.json' not in zf.namelist():
                return jsonify({'status': 'error', 'message': 'weekmenu_export.json niet gevonden in ZIP'}), 400

            data = json.loads(zf.read('weekmenu_export.json').decode('utf-8'))

            for entry in zf.namelist():
                if entry.startswith('images/') and not entry.endswith('/'):
                    fname = os.path.basename(entry)
                    dest = os.path.join(uploads_dir, fname)
                    if not os.path.exists(dest):
                        with open(dest, 'wb') as f:
                            f.write(zf.read(entry))
                        counts['images'] += 1

            for cb_data in data.get('cookbooks', []):
                if not Cookbook.query.filter_by(name=cb_data['name']).first():
                    image_path = None
                    if cb_data.get('image_filename'):
                        candidate = os.path.join('static', 'uploads', cb_data['image_filename'])
                        if os.path.isfile(os.path.join(current_app.root_path, candidate)):
                            image_path = candidate
                    db.session.add(Cookbook(
                        name=cb_data['name'],
                        abbreviation=cb_data.get('abbreviation'),
                        image_path=image_path,
                        is_archived=cb_data.get('is_archived', False),
                    ))
                    counts['cookbooks'] += 1
            db.session.commit()

            for r_data in data.get('recipes', []):
                if Recipe.query.filter_by(name=r_data['name']).first():
                    continue

                cookbook = (Cookbook.query.filter_by(name=r_data['cookbook']).first()
                            if r_data.get('cookbook') else None)

                image_path = None
                if r_data.get('image_filename'):
                    candidate = os.path.join('static', 'uploads', r_data['image_filename'])
                    if os.path.isfile(os.path.join(current_app.root_path, candidate)):
                        image_path = candidate

                recipe = Recipe(
                    name=r_data['name'],
                    serves=r_data.get('serves'),
                    cookbook_id=cookbook.id if cookbook else None,
                    page=r_data.get('page'),
                    is_favorite=r_data.get('is_favorite', False),
                    url=r_data.get('url'),
                    instructions=r_data.get('instructions'),
                    image_path=image_path,
                )
                db.session.add(recipe)
                db.session.flush()

                for ing_data in r_data.get('ingredients', []):
                    ingredient = Ingredient.query.filter_by(name=ing_data['name']).first()
                    if not ingredient:
                        ingredient = Ingredient(
                            name=ing_data['name'],
                            category=ing_data.get('category', 'Overig'),
                        )
                        db.session.add(ingredient)
                        db.session.flush()
                        counts['ingredients'] += 1
                    raw_amount = ing_data.get('amount') or 0
                    norm_unit, norm_amount = _normalize_ri_unit(ingredient, ing_data.get('unit', ''), raw_amount)
                    db.session.add(RecipeIngredient(
                        recipe_id=recipe.id,
                        ingredient_id=ingredient.id,
                        amount=norm_amount,
                        unit=norm_unit,
                    ))
                counts['recipes'] += 1

        db.session.commit()
        return jsonify({
            'status': 'success',
            'message': (f"{counts['cookbooks']} kookboeken, {counts['recipes']} recepten, "
                        f"{counts['ingredients']} ingrediënten en {counts['images']} afbeeldingen geïmporteerd.")
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400
