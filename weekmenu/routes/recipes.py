import hashlib
import json
import os

from flask import (
    Blueprint, render_template, request, jsonify,
    redirect, url_for, flash, current_app,
)

from weekmenu.extensions import db
from weekmenu.models import (
    Recipe, Ingredient, IngredientAlias, Cookbook,
    RecipeIngredient, Settings, PantryIngredient,
)
from weekmenu.constants import PRODUCT_CATEGORIES
from weekmenu.services.units import (
    _normalize_ingredient, _guess_ingredient_category, _normalize_ri_unit,
)
from weekmenu.services.recipes import (
    _resolve_or_create_ingredient, _download_site_logo,
)
from weekmenu.services.gemini import scrape_recipe_from_url, recipe_from_photos
from weekmenu.services.recipe_matcher import score_recipes
from weekmenu.services.pantry import list_pantry, add_to_pantry, remove_from_pantry


bp = Blueprint('recipes', __name__)


def serialize_recipe(r, default_serves=4):
    """Volledige recept-payload voor detail-modal en receptenplanner-cache."""
    return {
        'id': r.id,
        'name': r.name,
        'serves': r.serves or default_serves,
        'image_path': r.image_path or '',
        'cookbook': r.cookbook.name if r.cookbook else None,
        'cookbook_abbr': r.cookbook.abbreviation if r.cookbook else None,
        'page': r.page,
        'url': r.url or '',
        'instructions': r.instructions or '',
        'is_favorite': r.is_favorite,
        'ingredients': [
            {
                'id': ri.id,
                'name': ri.ingredient.display,
                'amount': ri.amount,
                'unit': ri.unit,
                'category': ri.ingredient.category,
                'preparation': ri.preparation or '',
            }
            for ri in r.ingredients
        ],
    }


@bp.route('/recipes')
def recipes():
    return redirect(url_for('recipes.receptenplanner'))


@bp.route('/receptenplanner')
def receptenplanner():
    from datetime import date
    recipes = Recipe.query.order_by(Recipe.name).all()
    today = date.today()
    current_week = today.isocalendar()[1]
    current_year = today.year

    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else 4

    recipes_json = json.dumps(
        [serialize_recipe(r, default_serves) for r in recipes],
        ensure_ascii=False,
    )

    return render_template('receptenplanner.html',
                           recipes_json=recipes_json,
                           current_week=current_week,
                           current_year=current_year,
                           default_serves=default_serves)


@bp.route('/api/recipe/<int:id>')
def api_recipe_detail(id):
    recipe = Recipe.query.get_or_404(id)
    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else 4
    return jsonify(serialize_recipe(recipe, default_serves))


@bp.route('/cookbook/<int:id>/recipes')
def list_cookbook_recipes(id):
    cookbook = Cookbook.query.get_or_404(id)
    recipes = sorted(cookbook.recipes, key=lambda x: (x.page is None, x.page or 0))
    return render_template('cookbook_recipes.html', cookbook=cookbook, recipes=recipes)


@bp.route('/cookbooks')
def list_cookbooks():
    all_cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    active = [c for c in all_cookbooks if not c.is_archived]
    archived = [c for c in all_cookbooks if c.is_archived]
    cookbooks_json = json.dumps([{'id': c.id, 'name': c.name} for c in all_cookbooks])
    return render_template('cookbooks.html', cookbooks=active, archived_cookbooks=archived, cookbooks_json=cookbooks_json)


@bp.route('/cookbook/new', methods=['GET', 'POST'])
def new_cookbook():
    if request.method == 'POST':
        cookbook_name = request.form['name']
        abbreviation = request.form.get('abbreviation', '').strip()

        existing_cookbook = Cookbook.query.filter_by(name=cookbook_name).first()
        if existing_cookbook:
            flash('Dit kookboek bestaat al')
            return redirect(url_for('recipes.new_cookbook'))

        if not abbreviation:
            words = cookbook_name.split()
            abbreviation = ''.join(word[0].upper() for word in words if word)[:5]

        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            image_data = image.read()
            ext = os.path.splitext(image.filename)[1].lower() or '.jpg'
            fname = hashlib.md5(image_data).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            image_path = os.path.join('static/uploads', fname)

        new_cb = Cookbook(name=cookbook_name, abbreviation=abbreviation, image_path=image_path)
        db.session.add(new_cb)
        db.session.commit()
        return redirect(url_for('recipes.list_cookbooks'))

    return render_template('new_cookbook.html')


@bp.route('/cookbook/<int:id>/edit', methods=['GET', 'POST'])
def edit_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)

    if request.method == 'POST':
        cookbook.name = request.form['name']
        abbreviation = request.form.get('abbreviation', '').strip()

        if abbreviation:
            cookbook.abbreviation = abbreviation
        else:
            words = cookbook.name.split()
            cookbook.abbreviation = ''.join(word[0].upper() for word in words if word)[:5]

        image = request.files.get('image')
        if image and image.filename:
            image_data = image.read()
            ext = os.path.splitext(image.filename)[1].lower() or '.jpg'
            fname = hashlib.md5(image_data).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            cookbook.image_path = os.path.join('static/uploads', fname)

        db.session.commit()
        return redirect(url_for('recipes.list_cookbooks'))

    return render_template('edit_cookbook.html', cookbook=cookbook)


@bp.route('/cookbook/<int:id>/rename', methods=['POST'])
def rename_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    new_name = request.form.get('name', '').strip()
    if not new_name:
        return jsonify({'status': 'error', 'message': 'Naam mag niet leeg zijn'}), 400
    if Cookbook.query.filter(Cookbook.name == new_name, Cookbook.id != id).first():
        return jsonify({'status': 'error', 'message': 'Een kookboek met deze naam bestaat al'}), 400
    cookbook.name = new_name
    db.session.commit()
    return jsonify({'status': 'success', 'name': cookbook.name})


@bp.route('/cookbook/<int:id>/migrate', methods=['POST'])
def migrate_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    data = request.get_json()
    target_id = data.get('target_cookbook_id')
    if not target_id:
        return jsonify({'status': 'error', 'message': 'Geen doelkookboek opgegeven'}), 400
    target = Cookbook.query.get_or_404(int(target_id))
    Recipe.query.filter_by(cookbook_id=id).update({'cookbook_id': target.id})
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'Recepten verplaatst naar {target.name}'})


@bp.route('/cookbook/<int:id>/archive', methods=['POST'])
def archive_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    cookbook.is_archived = not cookbook.is_archived
    db.session.commit()
    return jsonify({'status': 'success', 'is_archived': cookbook.is_archived})


@bp.route('/cookbook/<int:id>/delete', methods=['POST'])
def delete_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    if cookbook.recipes:
        return jsonify({'status': 'error', 'message': 'Kookboek heeft nog recepten. Verwijder of verplaats ze eerst.'}), 400
    if cookbook.image_path:
        try:
            os.remove(os.path.join(current_app.static_folder, 'uploads', os.path.basename(cookbook.image_path)))
        except OSError:
            pass
    db.session.delete(cookbook)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/recipe/new', methods=['GET', 'POST'])
def new_recipe():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()

    if request.method == 'POST':
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            image_data = image.read()
            ext = os.path.splitext(image.filename)[1].lower() or '.jpg'
            fname = hashlib.md5(image_data).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            image_path = os.path.join('static/uploads', fname)
        elif request.form.get('image_path_imported'):
            image_path = request.form.get('image_path_imported')

        cookbook_id = request.form.get('cookbook') or None
        if cookbook_id == '__new__':
            new_name = request.form.get('new_cookbook_name', '').strip()
            if new_name:
                existing = Cookbook.query.filter_by(name=new_name).first()
                if existing:
                    cookbook_id = existing.id
                else:
                    words = new_name.split()
                    abbr = ''.join(w[0].upper() for w in words if w)[:5]
                    cb_image = None
                    recipe_url = request.form.get('url', '').strip()
                    if recipe_url:
                        try:
                            from urllib.parse import urlparse as _up
                            domain = _up(recipe_url).netloc
                            import requests as _req
                            cb_image = _download_site_logo(domain, '', _req)
                        except Exception:
                            pass
                    new_cb = Cookbook(name=new_name, abbreviation=abbr, image_path=cb_image)
                    db.session.add(new_cb)
                    db.session.flush()
                    cookbook_id = new_cb.id
            else:
                cookbook_id = None

        serves_val = request.form.get('serves', '').strip()
        recipe = Recipe(
            name=request.form['name'],
            serves=int(serves_val) if serves_val else None,
            cookbook_id=cookbook_id,
            page=request.form['page'] if request.form['page'] else None,
            image_path=image_path,
            url=request.form.get('url') or None,
            instructions=request.form.get('instructions') or None
        )
        db.session.add(recipe)
        db.session.commit()

        ingredient_ids = request.form.getlist('ingredient_id[]')
        ingredient_names = request.form.getlist('ingredient[]')
        amounts = request.form.getlist('amount[]')
        units = request.form.getlist('unit[]')
        categories = request.form.getlist('category[]')
        preparations = request.form.getlist('preparation[]')

        for i in range(len(ingredient_names)):
            if not ingredient_names[i]:
                continue

            if i < len(ingredient_ids) and ingredient_ids[i]:
                ingredient = Ingredient.query.get(int(ingredient_ids[i]))
            else:
                ingredient = _resolve_or_create_ingredient(ingredient_names[i], categories[i] if i < len(categories) else None)

            if not ingredient:
                continue

            prep = preparations[i].strip() if i < len(preparations) and preparations[i] else None

            raw_amount = float(amounts[i]) if amounts[i] else 0
            norm_unit, norm_amount = _normalize_ri_unit(ingredient, units[i], raw_amount)
            recipe_ingredient = RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                amount=norm_amount,
                unit=norm_unit,
                preparation=prep,
            )
            db.session.add(recipe_ingredient)

        db.session.commit()
        return redirect(url_for('recipes.receptenplanner'))

    return render_template('new_recipe.html', cookbooks=cookbooks, categories=PRODUCT_CATEGORIES)


@bp.route('/recipe/<int:id>/edit', methods=['GET', 'POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()

    if request.method == 'POST':
        recipe.name = request.form['name']
        serves_val = request.form.get('serves', '').strip()
        recipe.serves = int(serves_val) if serves_val else None

        cookbook_id = request.form.get('cookbook') or None
        if cookbook_id == '__new__':
            new_name = request.form.get('new_cookbook_name', '').strip()
            if new_name:
                existing = Cookbook.query.filter_by(name=new_name).first()
                if existing:
                    cookbook_id = existing.id
                else:
                    words = new_name.split()
                    abbr = ''.join(w[0].upper() for w in words if w)[:5]
                    cb_image = None
                    recipe_url = request.form.get('url', '').strip()
                    if recipe_url:
                        try:
                            from urllib.parse import urlparse as _up
                            domain = _up(recipe_url).netloc
                            import requests as _req
                            cb_image = _download_site_logo(domain, '', _req)
                        except Exception:
                            pass
                    new_cb = Cookbook(name=new_name, abbreviation=abbr, image_path=cb_image)
                    db.session.add(new_cb)
                    db.session.flush()
                    cookbook_id = new_cb.id
            else:
                cookbook_id = None
        recipe.cookbook_id = cookbook_id
        recipe.page = request.form['page'] if request.form['page'] else None
        recipe.url = request.form.get('url') or None
        recipe.instructions = request.form.get('instructions') or None

        image = request.files.get('image')
        if image and image.filename:
            image_data = image.read()
            ext = os.path.splitext(image.filename)[1].lower() or '.jpg'
            fname = hashlib.md5(image_data).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_data)
            recipe.image_path = os.path.join('static/uploads', fname)

        RecipeIngredient.query.filter_by(recipe_id=recipe.id).delete()

        ingredient_ids = request.form.getlist('ingredient_id[]')
        ingredient_names = request.form.getlist('ingredient[]')
        amounts = request.form.getlist('amount[]')
        units = request.form.getlist('unit[]')
        categories = request.form.getlist('category[]')
        preparations = request.form.getlist('preparation[]')

        for i in range(len(ingredient_names)):
            if not ingredient_names[i]:
                continue

            if i < len(ingredient_ids) and ingredient_ids[i]:
                ingredient = Ingredient.query.get(int(ingredient_ids[i]))
            else:
                ingredient = _resolve_or_create_ingredient(ingredient_names[i], categories[i] if i < len(categories) else None)

            if not ingredient:
                continue

            prep = preparations[i].strip() if i < len(preparations) and preparations[i] else None

            raw_amount = float(amounts[i]) if amounts[i] else 0
            norm_unit, norm_amount = _normalize_ri_unit(ingredient, units[i], raw_amount)
            recipe_ingredient = RecipeIngredient(
                recipe_id=recipe.id,
                ingredient_id=ingredient.id,
                amount=norm_amount,
                unit=norm_unit,
                preparation=prep,
            )
            db.session.add(recipe_ingredient)

        db.session.commit()

        # Scope-gebonden pantry-sync: alleen ingrediënten van dit recept aanraken
        scope_ids         = set(int(x) for x in request.form.getlist('ingredient_id[]') if x)
        checked_pantry_ids = set(int(x) for x in request.form.getlist('pantry[]'))
        for ing_id in scope_ids:
            exists = PantryIngredient.query.filter_by(ingredient_id=ing_id).first()
            if ing_id in checked_pantry_ids:
                if not exists:
                    db.session.add(PantryIngredient(ingredient_id=ing_id))
            else:
                if exists:
                    db.session.delete(exists)
        db.session.commit()

        return redirect(url_for('recipes.receptenplanner'))

    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    return render_template('edit_recipe.html', recipe=recipe, cookbooks=cookbooks,
                           categories=PRODUCT_CATEGORIES, pantry_ids=pantry_ids)


@bp.route('/recipe/<int:id>', methods=['DELETE'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return jsonify({'status': 'success'})


@bp.route('/recipe/<int:id>/toggle_favorite', methods=['POST'])
def toggle_favorite(id):
    try:
        recipe = Recipe.query.get_or_404(id)
        recipe.is_favorite = not recipe.is_favorite
        db.session.commit()
        return jsonify({
            'status': 'success',
            'is_favorite': recipe.is_favorite
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/api/ingredients/search')
def ingredient_search():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify([])

    q_norm = _normalize_ingredient(q)

    results = db.session.query(Ingredient).join(
        IngredientAlias, Ingredient.id == IngredientAlias.ingredient_id
    ).filter(
        IngredientAlias.alias.like(f'{q_norm}%')
    ).distinct().limit(15).all()

    if len(results) < 10:
        seen = {r.id for r in results}
        more = Ingredient.query.filter(
            Ingredient.display_name.ilike(f'%{q}%')
        ).limit(15 - len(results)).all()
        results.extend(r for r in more if r.id not in seen)

    return jsonify([{
        'id': ing.id,
        'name': ing.display,
        'category': ing.category,
        'has_ah': bool(ing.ah_product_id),
        'preferred_unit': ing.preferred_unit,
    } for ing in results[:15]])


@bp.route('/api/ingredients', methods=['POST'])
def create_ingredient():
    data = request.get_json()
    raw_name = (data.get('name') or '').strip()
    category = data.get('category', 'Overig')

    if not raw_name:
        return jsonify({'status': 'error', 'message': 'Naam is verplicht'}), 400

    canonical = _normalize_ingredient(raw_name.lower().strip())

    existing = Ingredient.query.filter_by(name=canonical).first()
    if existing:
        return jsonify({
            'status': 'exists',
            'ingredient_id': existing.id,
            'display_name': existing.display,
            'category': existing.category,
        })

    alias = IngredientAlias.query.filter_by(alias=canonical).first()
    if alias:
        return jsonify({
            'status': 'exists',
            'ingredient_id': alias.ingredient_id,
            'display_name': alias.ingredient.display,
            'category': alias.ingredient.category,
        })

    if not category or category == 'Overig':
        category = _guess_ingredient_category(canonical)

    ing = Ingredient(name=canonical, display_name=raw_name.strip(), category=category)
    db.session.add(ing)
    db.session.flush()
    db.session.add(IngredientAlias(alias=canonical, ingredient_id=ing.id))
    db.session.commit()

    return jsonify({
        'status': 'success',
        'ingredient_id': ing.id,
        'display_name': ing.display,
        'category': ing.category,
    })


@bp.route('/api/quick_access_recipes')
def get_quick_access_recipes():
    try:
        favorites = Recipe.query.filter_by(is_favorite=True).order_by(Recipe.name).limit(10).all()
        recent = Recipe.query.filter(Recipe.last_used.isnot(None)).order_by(Recipe.last_used.desc()).limit(10).all()
        popular = Recipe.query.filter(Recipe.usage_count > 0).order_by(Recipe.usage_count.desc()).limit(10).all()

        def format_recipe(recipe):
            return {
                'id': recipe.id,
                'name': recipe.name,
                'serves': recipe.serves or 4,
                'cookbook_abbr': recipe.cookbook.abbreviation if recipe.cookbook else None,
                'page': recipe.page,
                'is_favorite': recipe.is_favorite,
                'usage_count': recipe.usage_count or 0,
                'image_path': recipe.image_path
            }

        return jsonify({
            'favorites': [format_recipe(r) for r in favorites],
            'recent': [format_recipe(r) for r in recent],
            'popular': [format_recipe(r) for r in popular]
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/recipe/scrape', methods=['POST'])
def scrape_recipe():
    data = request.get_json() or {}
    url = data.get('url', '')
    payload, status = scrape_recipe_from_url(url)
    if status != 200:
        current_app.logger.warning('Recept-import mislukt voor %r: %s',
                                   url, payload.get('message'))
    return jsonify(payload), status


@bp.route('/recipe/from-photo', methods=['POST'])
def recipe_from_photo():
    if 'photos' not in request.files:
        return jsonify({'status': 'error', 'message': "Geen foto's ontvangen"}), 400
    payload, status = recipe_from_photos(request.files.getlist('photos'))
    return jsonify(payload), status


# ── Ecobooster ───────────────────────────────────────────────────────────────

@bp.route('/ecobooster')
def ecobooster():
    return redirect(url_for('inspiratie.inspiratie', tab='ecobooster'), code=301)


@bp.route('/api/ecobooster/match', methods=['POST'])
def ecobooster_match():
    fresh_ids = request.json.get('ingredient_ids', []) if request.json else []
    return jsonify(score_recipes(fresh_ids, source='ecobooster'))


# ── Pantry API ───────────────────────────────────────────────────────────────

@bp.route('/api/pantry', methods=['GET'])
def get_pantry():
    return jsonify(list_pantry())


@bp.route('/api/pantry', methods=['POST'])
def add_pantry():
    data = request.json or {}
    payload, status = add_to_pantry(data.get('ingredient_id'))
    return jsonify(payload), status


@bp.route('/api/pantry/<int:ingredient_id>', methods=['DELETE'])
def remove_pantry(ingredient_id):
    return jsonify(remove_from_pantry(ingredient_id))
