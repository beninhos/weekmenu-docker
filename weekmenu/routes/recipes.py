import hashlib
import json
import os
import re

from flask import (
    Blueprint, render_template, request, jsonify,
    redirect, url_for, flash, current_app,
)
from werkzeug.utils import secure_filename

from weekmenu.extensions import db
from weekmenu.models import (
    Recipe, Ingredient, IngredientAlias, Cookbook,
    RecipeIngredient, Settings,
)
from weekmenu.constants import PRODUCT_CATEGORIES, _BROWSER_HEADERS, DUTCH_UNITS
from weekmenu.services.units import (
    _normalize_ingredient, _guess_ingredient_category,
    _normalize_ri_unit, parse_ingredients_from_list,
)
from weekmenu.services.recipes import (
    _resolve_or_create_ingredient, _get_or_create_site_cookbook,
    _get_gemini_api_key,
)

_VALID_UNITS = sorted(set(DUTCH_UNITS.values()))
_UNITS_STR = ', '.join(_VALID_UNITS)

_GEMINI_RECIPE_PROMPT = f"""Extraheer het recept. Geef ALLEEN geldige JSON terug, geen markdown.

{{
  "title": "Recept naam",
  "yields": 4,
  "prep_time": 30,
  "ingredients": [
    {{"name": "bloem", "amount": 200, "unit": "g"}},
    {{"name": "eieren", "amount": 3, "unit": "stuks"}}
  ],
  "instructions": "Stap 1. Verwarm de oven...\\nStap 2. Meng..."
}}

Regels:
- Gebruik ALLEEN deze eenheden voor "unit": {_UNITS_STR}
- "amount" is een getal (int of float), of null als onbekend
- Converteer breuken naar decimalen: ½ → 0.5, ¼ → 0.25, "anderhalve" → 1.5
- Haal hoeveelheden uit de naam en zet ze in "amount"
- "name" is de ingrediëntnaam zonder hoeveelheid of eenheid
- "instructions" als enkele string met stappen gescheiden door newlines
- "prep_time" in minuten (int of null)
- Als er geen recept gevonden kan worden: {{"error": "Geen recept gevonden"}}
"""


def _clean_html(html):
    """Strip non-content HTML tags, return plain text (max 10k chars)."""
    for tag in ('script', 'style', 'nav', 'footer', 'iframe'):
        html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:10000]


def _sanitize_json(text):
    """Strip markdown code fences and extra whitespace from LLM response."""
    text = text.strip()
    # Strip markdown fences (with optional language tag)
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
        text = text.strip()
    # Strip trailing commas before } or ]
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text


def _build_gemini_ingredients(raw_list):
    """Convert structured LLM ingredient dicts to app format with category."""
    ingredients = []
    for ing in raw_list:
        name = (ing.get('name') or '').strip()
        if not name:
            continue
        ingredients.append({
            'name': name,
            'amount': ing.get('amount'),
            'unit': ing.get('unit') or '',
            'category': _guess_ingredient_category(name),
        })
    return ingredients


bp = Blueprint('recipes', __name__)


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

    recipes_json = json.dumps([
        {
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
            ]
        }
        for r in recipes
    ], ensure_ascii=False)

    return render_template('receptenplanner.html',
                           recipes_json=recipes_json,
                           current_week=current_week,
                           current_year=current_year,
                           default_serves=default_serves)


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
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(current_app.static_folder, 'uploads', filename))

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
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(current_app.static_folder, 'uploads', filename))
            cookbook.image_path = image_path

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
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(current_app.static_folder, 'uploads', filename))
        elif request.form.get('image_path_imported'):
            image_path = request.form.get('image_path_imported')

        serves_val = request.form.get('serves', '').strip()
        recipe = Recipe(
            name=request.form['name'],
            serves=int(serves_val) if serves_val else None,
            cookbook_id=request.form.get('cookbook') if request.form.get('cookbook') else None,
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
        recipe.cookbook_id = request.form.get('cookbook') if request.form.get('cookbook') else None
        recipe.page = request.form['page'] if request.form['page'] else None
        recipe.url = request.form.get('url') or None
        recipe.instructions = request.form.get('instructions') or None

        image = request.files.get('image')
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(current_app.static_folder, 'uploads', filename))
            recipe.image_path = image_path

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
        return redirect(url_for('recipes.receptenplanner'))

    return render_template('edit_recipe.html', recipe=recipe, cookbooks=cookbooks, categories=PRODUCT_CATEGORIES)


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
    import requests as _requests
    from recipe_scrapers import scrape_html
    data = request.get_json()
    url = (data or {}).get('url', '').strip()
    if not url:
        return jsonify({'status': 'error', 'message': 'Geen URL opgegeven'}), 400

    try:
        resp = _requests.get(url, headers=_BROWSER_HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    except _requests.exceptions.Timeout:
        return jsonify({'status': 'error', 'message': 'De pagina reageerde niet op tijd. Probeer het opnieuw.'}), 400
    except _requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else '?'
        if code == 403:
            return jsonify({'status': 'error', 'message': 'Deze website blokkeert automatisch ophalen (403). Probeer een andere site.'}), 400
        if code == 404:
            return jsonify({'status': 'error', 'message': 'Pagina niet gevonden (404). Controleer de URL.'}), 400
        return jsonify({'status': 'error', 'message': f'De pagina kon niet worden opgehaald (HTTP {code}).'}), 400
    except Exception:
        return jsonify({'status': 'error', 'message': 'De URL kon niet worden bereikt. Controleer de URL.'}), 400

    try:
        scraper = scrape_html(html, org_url=url)
        scraper.title()
    except Exception:
        try:
            scraper = scrape_html(html, org_url=url, wild_mode=True)
        except Exception:
            scraper = None

    # ── LLM fallback wanneer scraper faalt ──────────────────
    if scraper is None:
        api_key = _get_gemini_api_key()
        if not api_key:
            return jsonify({'status': 'error', 'message': 'Geen receptinformatie gevonden op deze pagina. De site ondersteunt geen gestructureerde receptdata.'}), 400

        from google import genai as _genai

        text = _clean_html(html)
        prompt = _GEMINI_RECIPE_PROMPT + f"\n\nTekst van de pagina:\n{text}"

        try:
            client = _genai.Client(api_key=api_key)
            response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
            sanitized = _sanitize_json(response.text)
            result = json.loads(sanitized)

            if 'error' in result:
                return jsonify({'status': 'error', 'message': result['error']}), 400

            cookbook_id = cookbook_name = None
            try:
                from urllib.parse import urlparse as _urlparse
                domain = _urlparse(url).netloc
                cookbook = _get_or_create_site_cookbook(domain, html, None, _requests)
                if cookbook:
                    cookbook_id, cookbook_name = cookbook.id, cookbook.name
            except Exception:
                pass

            return jsonify({
                'status': 'success',
                'name': result.get('title', ''),
                'serves': result.get('yields'),
                'url': url,
                'instructions': result.get('instructions', ''),
                'ingredients': _build_gemini_ingredients(result.get('ingredients', [])),
                'image_path': None,
                'cookbook_id': cookbook_id,
                'cookbook_name': cookbook_name,
            })
        except json.JSONDecodeError as e:
            return jsonify({'status': 'error', 'message': f'Fout in receptgegevens: {str(e)[:100]}'}), 400
        except Exception as e:
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower() or 'RESOURCE_EXHAUSTED' in msg:
                msg = 'Gemini is even niet beschikbaar (rate limit). Probeer het over een minuut opnieuw.'
            else:
                msg = f'Fout bij verwerken: {msg[:100]}'
            return jsonify({'status': 'error', 'message': msg}), 400

    try:
        title = scraper.title() or ''
    except Exception:
        title = ''

    try:
        yields_str = scraper.yields() or ''
        serves_match = re.search(r'\d+', yields_str)
        serves = int(serves_match.group()) if serves_match else None
    except Exception:
        serves = None

    try:
        instructions = scraper.instructions() or ''
    except Exception:
        instructions = ''

    raw_ingredients = []
    section_names = []
    try:
        groups = scraper.ingredient_groups()
        if groups and len(groups) > 1:
            for g in groups:
                if g.ingredients:
                    raw_ingredients.extend(g.ingredients)
                if g.purpose:
                    section_names.append(g.purpose)
        else:
            raise ValueError('single group, use .ingredients()')
    except Exception:
        try:
            raw_ingredients = scraper.ingredients() or []
        except Exception:
            raw_ingredients = []

    if section_names:
        prefix = 'Secties: ' + ' + '.join(section_names) + '\n\n'
        instructions = prefix + instructions

    parsed_ingredients = parse_ingredients_from_list(raw_ingredients)

    image_path = None
    try:
        image_url = scraper.image()
        if image_url:
            from curl_cffi import requests as _cffi_requests
            img_resp = _cffi_requests.get(image_url, impersonate='chrome', timeout=10)
            img_resp.raise_for_status()
            content_type = img_resp.headers.get('Content-Type', '')
            ext = '.jpg'
            if 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            elif 'avif' in content_type:
                ext = '.avif'
            elif 'gif' in content_type:
                ext = '.gif'
            fname = hashlib.md5(image_url.encode()).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(img_resp.content)
            image_path = os.path.join('static/uploads', fname)
    except Exception:
        pass

    cookbook_id = None
    cookbook_name = None
    try:
        from urllib.parse import urlparse as _urlparse
        domain = _urlparse(url).netloc
        cookbook = _get_or_create_site_cookbook(domain, html, scraper, _requests)
        if cookbook:
            cookbook_id = cookbook.id
            cookbook_name = cookbook.name
    except Exception:
        pass

    return jsonify({
        'status': 'success',
        'name': title,
        'serves': serves,
        'url': url,
        'instructions': instructions,
        'ingredients': parsed_ingredients,
        'image_path': image_path,
        'cookbook_id': cookbook_id,
        'cookbook_name': cookbook_name,
    })


@bp.route('/recipe/from-photo', methods=['POST'])
def recipe_from_photo():
    from google import genai as _genai
    from google.genai import types as _gtypes
    import json as _json

    api_key = _get_gemini_api_key()
    if not api_key:
        return jsonify({'status': 'error', 'message': 'Gemini API key niet geconfigureerd'}), 400

    if 'photos' not in request.files:
        return jsonify({'status': 'error', 'message': "Geen foto's ontvangen"}), 400

    photos = request.files.getlist('photos')
    if not photos or len(photos) == 0 or photos[0].filename == '':
        return jsonify({'status': 'error', 'message': "Geen foto's geselecteerd"}), 400

    if len(photos) > 3:
        return jsonify({'status': 'error', 'message': "Maximaal 3 foto's toegestaan"}), 400

    image_parts = []
    first_image_path = None

    for i, photo in enumerate(photos):
        if photo.filename == '':
            continue

        image_bytes = photo.read()

        if i == 0:
            ext = '.jpg'
            if photo.content_type == 'image/png':
                ext = '.png'
            elif photo.content_type == 'image/webp':
                ext = '.webp'
            fname = hashlib.md5(image_bytes).hexdigest() + ext
            save_path = os.path.join(current_app.static_folder, 'uploads', fname)
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, 'wb') as f:
                f.write(image_bytes)
            first_image_path = os.path.join('static/uploads', fname)

        image_parts.append(
            _gtypes.Part.from_bytes(data=image_bytes, mime_type=photo.content_type or 'image/jpeg')
        )

    prompt = _GEMINI_RECIPE_PROMPT + "\n\nBij meerdere foto's: combineer ingrediënten en bereiding van alle pagina's."

    try:
        client = _genai.Client(api_key=api_key)
        content = [prompt] + image_parts
        response = client.models.generate_content(model='gemini-2.5-flash', contents=content)
        sanitized = _sanitize_json(response.text)
        result = _json.loads(sanitized)

        if 'error' in result:
            return jsonify({'status': 'error', 'message': result['error']}), 400

        return jsonify({
            'status': 'success',
            'name': result.get('title', ''),
            'serves': result.get('yields'),
            'url': None,
            'instructions': result.get('instructions', ''),
            'ingredients': _build_gemini_ingredients(result.get('ingredients', [])),
            'image_path': first_image_path,
            'cookbook_id': None,
            'cookbook_name': None,
        })

    except _json.JSONDecodeError as e:
        return jsonify({'status': 'error', 'message': f'Fout in receptgegevens: {str(e)[:100]}'}), 400
    except Exception as e:
        msg = str(e)
        if '429' in msg or 'quota' in msg.lower() or 'RESOURCE_EXHAUSTED' in msg:
            msg = 'Gemini is even niet beschikbaar (rate limit). Probeer het over een minuut opnieuw.'
        else:
            msg = f'Fout bij verwerken: {msg[:100]}'
        return jsonify({'status': 'error', 'message': msg}), 400
