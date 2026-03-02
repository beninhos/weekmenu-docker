from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from datetime import datetime, date
from werkzeug.utils import secure_filename
import os
import io
import json
import re
import zipfile
from pathlib import Path

def format_amount(amount):
    """Format numbers smart: integers without decimals, decimals when needed"""
    rounded = round(amount, 2)
    
    if rounded == int(rounded):
        return int(rounded)
    
    return f"{rounded:g}"

# Constants
DAYS = [
    (0, 'Maandag'),
    (1, 'Dinsdag'),
    (2, 'Woensdag'),
    (3, 'Donderdag'),
    (4, 'Vrijdag'),
    (5, 'Zaterdag'),
    (6, 'Zondag')
]

MEAL_TYPES = [
    ('ontbijt', 'Ontbijt'),
    ('lunch', 'Lunch'),
    ('diner', 'Diner')
]

# NIEUW: Uitgebreide categorieën die aansluiten bij supermarktindeling
PRODUCT_CATEGORIES = [
    'AGF (Groenten & Fruit)',
    'Vlees & Vis',
    'Zuivel & Eieren',
    'Kaas & Vleeswaren',
    'Brood & Banket',
    'Pasta, Rijst & Wereldkeuken',
    'Conserven & Soepen',
    'Sauzen & Kruiden',
    'Bakproducten',
    'Ontbijt & Broodbeleg',
    'Dranken',
    'Diepvries',
    'Snoep & Koek',
    'Noten & Gedroogd fruit',
    'Overig'
]

# Sorteervolgorde voor boodschappenlijst - Supermarkt looproute
CATEGORY_ORDER_SUPERMARKET = [
    'AGF (Groenten & Fruit)',           # Bij binnenkomst
    'Brood & Banket',                   # Vaak vooraan
    'Kaas & Vleeswaren',                # Versafdeling
    'Vlees & Vis',                      # Verse afdeling
    'Zuivel & Eieren',                  # Koeling zijkant
    'Pasta, Rijst & Wereldkeuken',      # Middenpad
    'Conserven & Soepen',               # Middenpaden
    'Sauzen & Kruiden',                 # Middenpaden
    'Bakproducten',                     # Middenpaden
    'Ontbijt & Broodbeleg',            # Middenpaden
    'Snoep & Koek',                    # Vaak bij kassa gebied
    'Noten & Gedroogd fruit',          # Bij snacks
    'Dranken',                          # Zwaar, vaak achteraan
    'Diepvries',                        # Helemaal achteraan
    'Overig'                            # Rest
]

# App setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:////data/weekmenu.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class Recipe(db.Model):
    __tablename__ = 'recipe'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    serves = db.Column(db.Integer, nullable=True)
    cookbook_id = db.Column(db.Integer, db.ForeignKey('cookbook.id'), nullable=True)
    page = db.Column(db.Integer)
    image_path = db.Column(db.String(200), nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)
    last_used = db.Column(db.DateTime, nullable=True)
    usage_count = db.Column(db.Integer, default=0)
    url = db.Column(db.Text, nullable=True)
    instructions = db.Column(db.Text, nullable=True)
    ingredients = db.relationship('RecipeIngredient', backref='recipe', lazy=True, cascade='all, delete-orphan')
    cookbook = db.relationship('Cookbook', back_populates='recipes')

class Ingredient(db.Model):
    __tablename__ = 'ingredient'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    category = db.Column(db.String(50), nullable=False)

class RecipeIngredient(db.Model):
    __tablename__ = 'recipe_ingredient'
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    ingredient = db.relationship('Ingredient', backref='recipe_ingredients')

class MenuItem(db.Model):
    __tablename__ = 'menu_item'
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False)
    meal_type = db.Column(db.String(20), nullable=False)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'))
    people_count = db.Column(db.Integer, nullable=True)
    week_number = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    skip_shopping_list = db.Column(db.Boolean, default=False, nullable=False)
    recipe = db.relationship('Recipe')

class Cookbook(db.Model):
    __tablename__ = 'cookbook'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    abbreviation = db.Column(db.String(10), nullable=True)
    image_path = db.Column(db.String(200), nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    recipes = db.relationship('Recipe', back_populates='cookbook', lazy=True)

class QuickAddItem(db.Model):
    __tablename__ = 'quick_add_item'
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    people_count = db.Column(db.Integer, default=4)
    week_number = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    recipe = db.relationship('Recipe')

class CustomShoppingIngredient(db.Model):
    __tablename__ = 'custom_shopping_ingredient'
    id = db.Column(db.Integer, primary_key=True)
    week_number = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    unit = db.Column(db.String(20), nullable=False, default='')
    ingredient = db.relationship('Ingredient')

class Settings(db.Model):
    __tablename__ = 'settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), nullable=False, unique=True)
    value = db.Column(db.String(200), nullable=True)

# Routes
@app.route('/')
def index():
    today = date.today()
    week_number = today.isocalendar()[1]
    year = today.year
    return redirect(url_for('week_menu', year=year, week=week_number))

@app.route('/week/<int:year>/<int:week>')
def week_menu(year, week):
    menu_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    recipes = Recipe.query.order_by(Recipe.name).all()
    recipes_json = json.dumps([{'id': r.id, 'name': r.name, 'serves': r.serves} for r in recipes])
    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else None
    return render_template('week_menu.html',
                         menu_items=menu_items,
                         recipes=recipes,
                         recipes_json=recipes_json,
                         week=week,
                         year=year,
                         days=DAYS,
                         meal_types=MEAL_TYPES,
                         default_serves=default_serves)

@app.route('/cookbook/<int:id>/recipes')
def list_cookbook_recipes(id):
    cookbook = Cookbook.query.get_or_404(id)
    recipes = sorted(cookbook.recipes, key=lambda x: (x.page is None, x.page or 0))
    return render_template('cookbook_recipes.html', cookbook=cookbook, recipes=recipes)

@app.route('/recipes')
def recipes():
    recipes = Recipe.query.all()
    return render_template('recipes.html', recipes=recipes, categories=PRODUCT_CATEGORIES)

@app.route('/receptenplanner')
def receptenplanner():
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
                    'name': ri.ingredient.name,
                    'amount': ri.amount,
                    'unit': ri.unit,
                    'category': ri.ingredient.category
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

@app.route('/api/planner/plan', methods=['POST'])
def planner_plan():
    try:
        data = request.get_json()
        recipe_id    = int(data['recipe_id'])
        day          = int(data['day'])
        meal_type    = data['meal_type']
        week         = int(data['week'])
        year         = int(data['year'])
        people_count = int(data.get('people_count') or 4)
        ingredient_ids = [int(i) for i in data.get('ingredient_ids', [])]

        recipe = Recipe.query.get_or_404(recipe_id)

        # Upsert the MenuItem with skip_shopping_list=True
        existing = MenuItem.query.filter_by(
            week_number=week, year=year, day_of_week=day, meal_type=meal_type
        ).first()
        if existing:
            existing.recipe_id = recipe_id
            existing.people_count = people_count
            existing.skip_shopping_list = True
        else:
            db.session.add(MenuItem(
                day_of_week=day, meal_type=meal_type,
                recipe_id=recipe_id, people_count=people_count,
                week_number=week, year=year,
                skip_shopping_list=True
            ))

        # Update usage stats
        recipe.usage_count = (recipe.usage_count or 0) + 1
        recipe.last_used = datetime.now()

        # Replace CustomShoppingIngredients for this recipe's ingredients in this week
        own_ingredient_ids = [ri.ingredient_id for ri in recipe.ingredients]
        if own_ingredient_ids:
            CustomShoppingIngredient.query.filter(
                CustomShoppingIngredient.week_number == week,
                CustomShoppingIngredient.year == year,
                CustomShoppingIngredient.ingredient_id.in_(own_ingredient_ids)
            ).delete(synchronize_session='fetch')

        # Add checked ingredients as CustomShoppingIngredients
        multiplier = (people_count / recipe.serves) if recipe.serves else 1.0
        for ri in recipe.ingredients:
            if ri.id in ingredient_ids:
                db.session.add(CustomShoppingIngredient(
                    week_number=week, year=year,
                    ingredient_id=ri.ingredient_id,
                    amount=round(ri.amount * multiplier, 4),
                    unit=ri.unit
                ))

        db.session.commit()
        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/recipe/new', methods=['GET', 'POST'])
def new_recipe():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    
    if request.method == 'POST':
        # Afbeelding uploaden (upload heeft voorrang boven geïmporteerd pad)
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
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
        
        ingredients = request.form.getlist('ingredient[]')
        amounts = request.form.getlist('amount[]')
        units = request.form.getlist('unit[]')
        categories = request.form.getlist('category[]')
        
        for i in range(len(ingredients)):
            if ingredients[i]:
                ingredient = Ingredient.query.filter_by(name=ingredients[i]).first()
                if not ingredient:
                    ingredient = Ingredient(name=ingredients[i], category=categories[i])
                    db.session.add(ingredient)
                    db.session.commit()
                else:
                    ingredient.category = categories[i]

                recipe_ingredient = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=float(amounts[i]) if amounts[i] else 0,
                    unit=units[i]
                )
                db.session.add(recipe_ingredient)

        db.session.commit()
        return redirect(url_for('recipes'))

    return render_template('new_recipe.html', cookbooks=cookbooks, categories=PRODUCT_CATEGORIES)

@app.route('/recipe/<int:id>', methods=['DELETE'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/cookbooks')
def list_cookbooks():
    all_cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    active = [c for c in all_cookbooks if not c.is_archived]
    archived = [c for c in all_cookbooks if c.is_archived]
    cookbooks_json = json.dumps([{'id': c.id, 'name': c.name} for c in all_cookbooks])
    return render_template('cookbooks.html', cookbooks=active, archived_cookbooks=archived, cookbooks_json=cookbooks_json)

@app.route('/cookbook/new', methods=['GET', 'POST'])
def new_cookbook():
    if request.method == 'POST':
        cookbook_name = request.form['name']
        abbreviation = request.form.get('abbreviation', '').strip()
        
        existing_cookbook = Cookbook.query.filter_by(name=cookbook_name).first()
        if existing_cookbook:
            flash('Dit kookboek bestaat al')
            return redirect(url_for('new_cookbook'))
        
        if not abbreviation:
            words = cookbook_name.split()
            abbreviation = ''.join(word[0].upper() for word in words if word)[:5]
        
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
        
        new_cookbook = Cookbook(name=cookbook_name, abbreviation=abbreviation, image_path=image_path)
        db.session.add(new_cookbook)
        db.session.commit()
        return redirect(url_for('list_cookbooks'))
    
    return render_template('new_cookbook.html')

@app.route('/cookbook/<int:id>/edit', methods=['GET', 'POST'])
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
            image.save(os.path.join(app.root_path, image_path))
            cookbook.image_path = image_path
        
        db.session.commit()
        return redirect(url_for('list_cookbooks'))

    return render_template('edit_cookbook.html', cookbook=cookbook)


@app.route('/cookbook/<int:id>/rename', methods=['POST'])
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


@app.route('/cookbook/<int:id>/migrate', methods=['POST'])
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


@app.route('/cookbook/<int:id>/archive', methods=['POST'])
def archive_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    cookbook.is_archived = not cookbook.is_archived
    db.session.commit()
    return jsonify({'status': 'success', 'is_archived': cookbook.is_archived})


@app.route('/cookbook/<int:id>/delete', methods=['POST'])
def delete_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    if cookbook.recipes:
        return jsonify({'status': 'error', 'message': 'Kookboek heeft nog recepten. Verwijder of verplaats ze eerst.'}), 400
    if cookbook.image_path:
        try:
            os.remove(os.path.join(app.root_path, cookbook.image_path))
        except OSError:
            pass
    db.session.delete(cookbook)
    db.session.commit()
    return jsonify({'status': 'success'})


@app.route('/update_menu', methods=['POST'])
def update_menu():
    try:
        data = request.get_json()
        
        old_items = MenuItem.query.filter_by(
            week_number=data['week'],
            year=data['year']
        ).all()
        
        old_positions = set()
        for old_item in old_items:
            if old_item.recipe_id:
                position = (old_item.day_of_week, old_item.meal_type, old_item.recipe_id)
                old_positions.add(position)
        
        MenuItem.query.filter_by(
            week_number=data['week'],
            year=data['year']
        ).delete()
        
        new_positions = set()
        
        for day in data['menu']:
            for meal_type, meal_data in day['meals'].items():
                if isinstance(meal_data, dict):
                    recipe_id = meal_data.get('recipe_id')
                    people_count_raw = meal_data.get('people_count')
                    try:
                        people_count = int(people_count_raw) if people_count_raw is not None else None
                    except (ValueError, TypeError):
                        people_count = None
                else:
                    recipe_id = meal_data
                    people_count = None
                
                if recipe_id:
                    recipe_id = int(recipe_id)
                    position = (day['day'], meal_type, recipe_id)
                    new_positions.add(position)
                    
                    menu_item = MenuItem(
                        day_of_week=day['day'],
                        meal_type=meal_type,
                        recipe_id=recipe_id,
                        people_count=people_count,
                        week_number=data['week'],
                        year=data['year']
                    )
                    db.session.add(menu_item)
        
        truly_new_positions = new_positions - old_positions
        
        for position in truly_new_positions:
            day, meal_type, recipe_id = position
            recipe = Recipe.query.get(recipe_id)
            if recipe:
                recipe.usage_count = (recipe.usage_count or 0) + 1
                recipe.last_used = datetime.now()
        
        used_recipe_ids = {pos[2] for pos in new_positions}
        for recipe_id in used_recipe_ids:
            recipe = Recipe.query.get(recipe_id)
            if recipe:
                recipe.last_used = datetime.now()
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/clear_week_menu', methods=['POST'])
def clear_week_menu():
    """Clear all menu items for a specific week"""
    try:
        data = request.get_json()
        week = data['week']
        year = data['year']
        
        MenuItem.query.filter_by(
            week_number=week,
            year=year
        ).delete()
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    menu_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    shopping_dict = {}
    
    def calc_multiplier(recipe_serves, people_count):
        if recipe_serves and people_count:
            try:
                return people_count / recipe_serves
            except ZeroDivisionError:
                return 1
        return 1

    # Process regular menu items (skip planner-sourced items)
    for item in menu_items:
        if item.skip_shopping_list:
            continue
        if item.recipe:
            multiplier = calc_multiplier(item.recipe.serves, item.people_count)
            for ri in item.recipe.ingredients:
                key = (ri.ingredient.name, ri.unit, ri.ingredient.category)
                adjusted_amount = ri.amount * multiplier
                if key in shopping_dict:
                    shopping_dict[key] += adjusted_amount
                else:
                    shopping_dict[key] = adjusted_amount

    # Process saved quick-add items from database
    quick_items = QuickAddItem.query.filter_by(week_number=week, year=year).all()

    for item in quick_items:
        if item.recipe:
            multiplier = calc_multiplier(item.recipe.serves, item.people_count)
            for ri in item.recipe.ingredients:
                key = (ri.ingredient.name, ri.unit, ri.ingredient.category)
                adjusted_amount = ri.amount * multiplier
                if key in shopping_dict:
                    shopping_dict[key] += adjusted_amount
                else:
                    shopping_dict[key] = adjusted_amount

    # Process temporary quick-add items from URL parameters
    recipe_ids = request.args.getlist('recipe_id')
    people_counts = request.args.getlist('people_count')

    for i, recipe_id in enumerate(recipe_ids):
        recipe = Recipe.query.get(recipe_id)
        if recipe:
            people_count = int(people_counts[i]) if i < len(people_counts) else None
            multiplier = calc_multiplier(recipe.serves, people_count)
            for ri in recipe.ingredients:
                key = (ri.ingredient.name, ri.unit, ri.ingredient.category)
                adjusted_amount = ri.amount * multiplier
                if key in shopping_dict:
                    shopping_dict[key] += adjusted_amount
                else:
                    shopping_dict[key] = adjusted_amount
    # Process custom shopping ingredients (from Receptenplanner)
    custom_items = CustomShoppingIngredient.query.filter_by(week_number=week, year=year).all()
    for ci in custom_items:
        key = (ci.ingredient.name, ci.unit, ci.ingredient.category)
        if key in shopping_dict:
            shopping_dict[key] += ci.amount
        else:
            shopping_dict[key] = ci.amount

    shopping_list = [
    {
        'name': k[0],
        'amount': v,
        'amount_display': format_amount(v),  # Dit is nieuw
        'unit': k[1],
        'category': k[2]
    }
    for k, v in shopping_dict.items()
]

    # Sorteer volgens supermarkt looproute
    category_order = {cat: i for i, cat in enumerate(CATEGORY_ORDER_SUPERMARKET)}
    shopping_list.sort(key=lambda x: (
        category_order.get(x['category'], 999),  # 999 voor onbekende categorieën
        x['name']
    ))

    # Groepeer per categorie
    grouped = []
    for item in shopping_list:
        if not grouped or grouped[-1]['category'] != item['category']:
            grouped.append({'category': item['category'], 'producten': []})
        grouped[-1]['producten'].append(item)

    return render_template('shopping_list.html',
                         grouped_shopping_list=grouped,
                         week=week,
                         year=year)

@app.route('/recipe/<int:id>/edit', methods=['GET', 'POST'])
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
            image.save(os.path.join(app.root_path, image_path))
            recipe.image_path = image_path
        
        RecipeIngredient.query.filter_by(recipe_id=recipe.id).delete()
        
        ingredients = request.form.getlist('ingredient[]')
        amounts = request.form.getlist('amount[]')
        units = request.form.getlist('unit[]')
        categories = request.form.getlist('category[]')
        
        for i in range(len(ingredients)):
            if ingredients[i]:
                ingredient = Ingredient.query.filter_by(name=ingredients[i]).first()
                if not ingredient:
                    ingredient = Ingredient(name=ingredients[i], category=categories[i])
                    db.session.add(ingredient)
                    db.session.commit()
                else:
                    ingredient.category = categories[i]

                recipe_ingredient = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=float(amounts[i]) if amounts[i] else 0,
                    unit=units[i]
                )
                db.session.add(recipe_ingredient)

        db.session.commit()
        return redirect(url_for('recipes'))

    return render_template('edit_recipe.html', recipe=recipe, cookbooks=cookbooks, categories=PRODUCT_CATEGORIES)

@app.route('/recipe/<int:id>/toggle_favorite', methods=['POST'])
def toggle_favorite(id):
    """Toggle favorite status van een recept"""
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

@app.route('/quick-add')
def quick_add():
    """Quick add page voor snel toevoegen van recepten aan boodschappenlijst"""
    today = date.today()
    week_number = request.args.get('week', today.isocalendar()[1], type=int)
    year = request.args.get('year', today.year, type=int)
    
    recipes = Recipe.query.order_by(Recipe.name).all()
    
    # Get saved quick-add items for this week
    saved_items = QuickAddItem.query.filter_by(
        week_number=week_number,
        year=year
    ).all()
    
    return render_template('quick_add.html',
                         recipes=recipes,
                         week=week_number,
                         year=year,
                         saved_items=saved_items)

@app.route('/api/quick-add/save', methods=['POST'])
def save_quick_add():
    """Save quick-add items to database for a specific week"""
    try:
        data = request.get_json()
        week = data['week']
        year = data['year']
        items = data['items']
        
        # Clear existing items for this week first
        QuickAddItem.query.filter_by(
            week_number=week,
            year=year
        ).delete()
        
        # Add new items
        for item in items:
            quick_item = QuickAddItem(
                recipe_id=item['recipe_id'],
                people_count=item['people_count'],
                week_number=week,
                year=year
            )
            db.session.add(quick_item)
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quick-add/clear', methods=['POST'])
def clear_quick_add():
    """Clear all quick-add items for a specific week"""
    try:
        data = request.get_json()
        week = data['week']
        year = data['year']
        
        QuickAddItem.query.filter_by(
            week_number=week,
            year=year
        ).delete()
        
        db.session.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/quick_access_recipes')
def get_quick_access_recipes():
    """API endpoint voor favorieten, recent en populaire recepten"""
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

@app.route('/copy_previous_week', methods=['POST'])
def copy_previous_week():
    try:
        data = request.get_json()
        week = data['week']
        year = data['year']

        if week > 1:
            prev_week = week - 1
            prev_year = year
        else:
            prev_year = year - 1
            last_day_prev_year = date(prev_year, 12, 28)
            prev_week = last_day_prev_year.isocalendar()[1]

        prev_items = MenuItem.query.filter_by(week_number=prev_week, year=prev_year).all()

        if not prev_items:
            return jsonify({'status': 'error', 'message': 'Geen menu gevonden voor de vorige week'}), 404

        MenuItem.query.filter_by(week_number=week, year=year).delete()

        for item in prev_items:
            new_item = MenuItem(
                day_of_week=item.day_of_week,
                meal_type=item.meal_type,
                recipe_id=item.recipe_id,
                people_count=item.people_count,
                week_number=week,
                year=year
            )
            db.session.add(new_item)

        db.session.commit()
        return jsonify({'status': 'success', 'count': len(prev_items)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


# Dutch unit normalization: map common Dutch abbreviations/words to canonical form
DUTCH_UNITS = {
    'el': 'el', 'eetlepel': 'el', 'eetlepels': 'el',
    'tl': 'tl', 'theelepel': 'tl', 'theelepels': 'tl',
    'kl': 'kl', 'koffielepel': 'kl', 'koffielepels': 'kl',
    'dl': 'dl', 'deciliter': 'dl',
    'ml': 'ml', 'milliliter': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l',
    'g': 'g', 'gr': 'g', 'gram': 'g', 'grams': 'g',
    'kg': 'kg', 'kilogram': 'kg',
    'stuks': 'stuks', 'stuk': 'stuks',
    'snuf': 'snufje', 'snufje': 'snufje', 'snufjes': 'snufje',
    'scheutje': 'scheutje', 'scheut': 'scheutje',
    'teen': 'teen', 'tenen': 'teen',
    'blik': 'blik', 'blikje': 'blik',
    'pakje': 'pakje', 'pak': 'pakje', 'zakje': 'zakje',
    'bosje': 'bosje', 'bos': 'bosje',
    'plak': 'plak', 'plakken': 'plak',
    'bol': 'bol', 'bollen': 'bol',
    'takje': 'takje', 'takjes': 'takje',
    'blaadje': 'blaadje', 'blaadjes': 'blaadje',
    'cup': 'cup', 'cups': 'cup',
    'tablespoon': 'el', 'tablespoons': 'el', 'tbsp': 'el', 'tbs': 'el',
    'teaspoon': 'tl', 'teaspoons': 'tl', 'tsp': 'tl',
    'pound': 'pond', 'pounds': 'pond', 'lb': 'pond', 'lbs': 'pond',
    'ounce': 'oz', 'ounces': 'oz',
    'clove': 'teen', 'cloves': 'teen',
    'bunch': 'bosje', 'handful': 'handvol', 'pinch': 'snufje', 'dash': 'scheutje',
    'can': 'blik', 'slice': 'plak', 'slices': 'plak',
    'piece': 'stuks', 'pieces': 'stuks',
}

def _parse_amount(amount_str):
    """Convert fraction strings like '1/2', '¼' to float."""
    if not amount_str:
        return None
    unicode_fractions = {'½': 0.5, '⅓': 1/3, '⅔': 2/3, '¼': 0.25, '¾': 0.75,
                         '⅕': 0.2, '⅖': 0.4, '⅗': 0.6, '⅘': 0.8, '⅙': 1/6,
                         '⅚': 5/6, '⅛': 0.125, '⅜': 0.375, '⅝': 0.625, '⅞': 0.875}
    s = str(amount_str).strip()
    for char, val in unicode_fractions.items():
        s = s.replace(char, str(val))
    # Handle "1 1/2" or "1½"
    mixed = re.match(r'^(\d+)[,. ](\d+/\d+)$', s)
    if mixed:
        whole = float(mixed.group(1))
        num, den = mixed.group(2).split('/')
        return whole + float(num) / float(den)
    if '/' in s:
        parts = s.split('/')
        try:
            return float(parts[0]) / float(parts[1])
        except (ValueError, ZeroDivisionError):
            return None
    s = s.replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return None

_UNIT_KEYS = '|'.join(re.escape(k) for k in sorted(DUTCH_UNITS.keys(), key=len, reverse=True))
_AMOUNT_RE = r'(?:[\d]+(?:[,.][\d]+)?(?:\s*[-–]\s*[\d]+(?:[,.][\d]+)?)?|[½¼¾⅓⅔⅛⅜⅝⅞]|\d+\s*/\s*\d+|\d+\s+\d+\s*/\s*\d+)'
_INGREDIENT_RE = re.compile(
    r'^(' + _AMOUNT_RE + r')\s+(' + _UNIT_KEYS + r')\b\.?\s+(.+)$',
    re.IGNORECASE
)
_AMOUNT_ONLY_RE = re.compile(
    r'^(' + _AMOUNT_RE + r')\s+(.+)$'
)

# Category guessing: ordered list checked in sequence (most specific first)
_CATEGORY_KEYWORDS = [
    ('Vlees & Vis', ['kip', 'gehakt', 'varken', 'rundvlees', 'lam', 'zalm', 'tonijn', 'vis', 'garnaal', 'mossel', 'inktvis', 'spek', 'bacon', 'worst', 'biefstuk', 'tartaar', 'ossenhaas', 'forel', 'haring', 'makreel', 'ansjovis', 'kabeljauw', 'tilapia', 'kreeft', 'krab', 'salami', 'pancetta', 'chorizo', 'kalkoen', 'eend', 'konijn']),
    ('Kaas & Vleeswaren', ['kaas', 'parmezaan', 'mozzarella', 'feta', 'ricotta', 'mascarpone', 'grana', 'pecorino', 'emmentaler', 'rookvlees']),
    ('Zuivel & Eieren', ['slagroom', 'karnemelk', 'melk', 'yoghurt', 'kwark', 'boter', 'margarine', 'crème fraîche', 'ei']),
    ('Pasta, Rijst & Wereldkeuken', ['spaghetti', 'penne', 'rigatoni', 'fusilli', 'lasagne', 'tagliatelle', 'fettuccine', 'noodle', 'couscous', 'bulgur', 'quinoa', 'polenta', 'gnocchi', 'tortellini', 'ravioli', 'macaroni', 'pasta', 'rijst', 'risotto', 'mie']),
    ('Conserven & Soepen', ['tomatenblokje', 'tomatenpuree', 'passata', 'kikkererwt', 'linzen', 'bonen', 'bouillon', 'soep']),
    ('Sauzen & Kruiden', ['olijfolie', 'zonnebloemolie', 'ketchup', 'mosterd', 'mayonaise', 'sojasaus', 'worcester', 'tabasco', 'pesto', 'sambal', 'harissa', 'paprikapoeder', 'komijn', 'kaneel', 'kurkuma', 'oregano', 'laurier', 'honing', 'stroop', 'vanille', 'azijn', 'olie', 'zout', 'suiker', 'peper']),
    ('Bakproducten', ['bloem', 'bakpoeder', 'maizena', 'gist', 'chocolade', 'cacao']),
    ('Ontbijt & Broodbeleg', ['jam', 'pindakaas', 'hagelslag', 'muesli', 'havermout', 'granola']),
    ('Dranken', ['wijn', 'bier', 'cognac', 'rum', 'wodka', 'gin', 'likeur']),
    ('Noten & Gedroogd fruit', ['amandel', 'walnoot', 'cashew', 'hazelnoot', 'pistache', 'pijnboompit', 'sesamzaad', 'rozijn', 'cranberry', 'pinda']),
    ('Brood & Banket', ['stokbrood', 'ciabatta', 'baguette', 'croissant', 'tortilla', 'cracker', 'brood']),
    ('AGF (Groenten & Fruit)', ['ui', 'sjalot', 'knoflook', 'tomat', 'appel', 'peer', 'citroen', 'limoen', 'wortel', 'aardappel', 'prei', 'courgette', 'paprika', 'champignon', 'paddenstoel', 'broccoli', 'bloemkool', 'spinazie', 'komkommer', 'avocado', 'banaan', 'aardbei', 'sinaasappel', 'kiwi', 'mango', 'ananas', 'peterselie', 'basilicum', 'rozemarijn', 'tijm', 'bieslook', 'selderij', 'venkel', 'asperge', 'sperziebonen', 'doperwt', 'mais', 'biet', 'radijs', 'spruitjes', 'kool', 'witlof', 'paksoi', 'aubergine', 'chilipeper', 'gember', 'andijvie', 'sla', 'dragon', 'koriander']),
]

def _guess_ingredient_category(name):
    """Guess supermarket category by keyword-matching ingredient name."""
    lower = name.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if re.search(r'(?<![a-z])' + re.escape(kw), lower):
                return category
    return 'Overig'

def _parse_dutch_ingredient(raw):
    """Dutch-first regex ingredient parser: amount + unit + name."""
    s = raw.strip()
    m = _INGREDIENT_RE.match(s)
    if m:
        name = m.group(3).strip()
        return {
            'amount': _parse_amount(m.group(1)),
            'unit': DUTCH_UNITS.get(m.group(2).lower(), m.group(2).lower()),
            'name': name,
            'category': _guess_ingredient_category(name),
            'raw': raw,
        }
    m2 = _AMOUNT_ONLY_RE.match(s)
    if m2:
        name = m2.group(2).strip()
        return {
            'amount': _parse_amount(m2.group(1)),
            'unit': 'stuks',
            'name': name,
            'category': _guess_ingredient_category(name),
            'raw': raw,
        }
    # Fallback: try ingredient-parser-nlp for English-format lines
    try:
        from ingredient_parser import parse_ingredient
        parsed = parse_ingredient(raw)
        amount = None
        unit = ''
        if parsed.amount:
            first = parsed.amount[0]
            amount = _parse_amount(str(first.quantity)) if first.quantity else None
            raw_unit = str(first.unit).lower().strip() if first.unit else ''
            unit = DUTCH_UNITS.get(raw_unit, raw_unit)
        name = parsed.name.text if parsed.name else s
        if name and name != s:
            name = name.strip()
            return {'amount': amount, 'unit': unit or ('stuks' if amount is not None else ''), 'name': name, 'category': _guess_ingredient_category(name), 'raw': raw}
    except Exception:
        pass
    return {'amount': None, 'unit': '', 'name': s, 'category': _guess_ingredient_category(s), 'raw': raw}

def parse_ingredients_from_list(ingredient_strings):
    return [_parse_dutch_ingredient(raw) for raw in ingredient_strings if raw and raw.strip()]


_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7',
    'DNT': '1',
}

# Known recipe websites: domain (without www.) → display name
_KNOWN_SITES = {
    'jumbo.com': 'Jumbo',
    'ah.nl': 'Albert Heijn',
    'allerhande.nl': 'Albert Heijn',
    'leukerecepten.nl': 'Leuke Recepten',
    '15gram.nl': '15GRAM',
    'culy.nl': 'Culy',
    'smulweb.nl': 'Smulweb',
    'njam.tv': 'Njam!',
    'recepten.nl': 'Recepten.nl',
    'kookmutsjes.nl': 'Kookmutsjes',
    'lekkerensimpel.nl': 'Lekker en Simpel',
    'margriet.nl': 'Margriet',
    'libelle.nl': 'Libelle',
    'jamieoliver.com': 'Jamie Oliver',
    'bbcgoodfood.com': 'BBC Good Food',
    'allrecipes.com': 'Allrecipes',
    'epicurious.com': 'Epicurious',
    'foodnetwork.com': 'Food Network',
}

def _get_or_create_site_cookbook(domain, html_text, scraper, requests_module):
    """Find or create a Cookbook entry for a website. Returns Cookbook or None."""
    import hashlib
    clean_domain = re.sub(r'^www\.', '', domain)

    # Determine display name
    name = _KNOWN_SITES.get(clean_domain)
    if not name:
        try:
            name = scraper.site_name() or clean_domain
        except Exception:
            name = clean_domain

    # Find existing cookbook with this name
    cookbook = Cookbook.query.filter_by(name=name).first()
    if cookbook:
        return cookbook

    base_fname = 'site_' + hashlib.md5(clean_domain.encode()).hexdigest()[:10]
    image_path = None

    def _save_image(content, content_type):
        ext = '.png'
        if 'jpeg' in content_type or 'jpg' in content_type: ext = '.jpg'
        elif 'svg' in content_type: ext = '.svg'
        elif 'webp' in content_type: ext = '.webp'
        elif 'ico' in content_type: ext = '.ico'
        fname = base_fname + ext
        save_path = os.path.join(app.root_path, 'static/uploads', fname)
        with open(save_path, 'wb') as f:
            f.write(content)
        return os.path.join('static/uploads', fname)

    # Attempt 1: Clearbit Logo API – returns clean brand logo (PNG, ~128×128)
    try:
        r = requests_module.get(f'https://logo.clearbit.com/{clean_domain}', timeout=5)
        if r.status_code == 200 and 'image' in r.headers.get('Content-Type', ''):
            image_path = _save_image(r.content, r.headers.get('Content-Type', 'image/png'))
    except Exception:
        pass

    # Attempt 2: apple-touch-icon from HTML (typically 180×180 PNG)
    if not image_path:
        try:
            icon_url = None
            for pattern in [
                r'<link[^>]+rel=["\'][^"\']*apple-touch-icon[^"\']*["\'][^>]+href=["\']([^"\']+)["\']',
                r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\'][^"\']*apple-touch-icon[^"\']*["\']',
            ]:
                m = re.search(pattern, html_text, re.IGNORECASE)
                if m:
                    icon_url = m.group(1)
                    break
            if icon_url:
                if icon_url.startswith('//'): icon_url = 'https:' + icon_url
                elif icon_url.startswith('/'): icon_url = f'https://{domain}' + icon_url
                elif not icon_url.startswith('http'): icon_url = f'https://{domain}/' + icon_url
                r = requests_module.get(icon_url, headers=_BROWSER_HEADERS, timeout=5)
                r.raise_for_status()
                image_path = _save_image(r.content, r.headers.get('Content-Type', ''))
        except Exception:
            pass

    # Attempt 3: /favicon.ico (last resort)
    if not image_path:
        try:
            r = requests_module.get(f'https://{domain}/favicon.ico', headers=_BROWSER_HEADERS, timeout=5)
            r.raise_for_status()
            image_path = _save_image(r.content, r.headers.get('Content-Type', 'image/x-icon'))
        except Exception:
            pass

    cookbook = Cookbook(name=name, image_path=image_path)
    db.session.add(cookbook)
    db.session.commit()
    return cookbook

@app.route('/recipe/scrape', methods=['POST'])
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
            return jsonify({'status': 'error', 'message': 'Geen receptinformatie gevonden op deze pagina. De site ondersteunt geen gestructureerde receptdata.'}), 400

    try:
        title = scraper.title() or ''
    except Exception:
        title = ''

    try:
        yields_str = scraper.yields() or ''
        # Extract first number from "4 servings", "4 persons", "4 porties" etc.
        serves_match = re.search(r'\d+', yields_str)
        serves = int(serves_match.group()) if serves_match else None
    except Exception:
        serves = None

    try:
        instructions = scraper.instructions() or ''
    except Exception:
        instructions = ''

    try:
        raw_ingredients = scraper.ingredients() or []
    except Exception:
        raw_ingredients = []

    parsed_ingredients = parse_ingredients_from_list(raw_ingredients)

    # Afbeelding downloaden en opslaan
    image_path = None
    try:
        image_url = scraper.image()
        if image_url:
            img_resp = _requests.get(image_url, headers=_BROWSER_HEADERS, timeout=10)
            img_resp.raise_for_status()
            content_type = img_resp.headers.get('Content-Type', '')
            ext = '.jpg'
            if 'png' in content_type:
                ext = '.png'
            elif 'webp' in content_type:
                ext = '.webp'
            elif 'gif' in content_type:
                ext = '.gif'
            import hashlib
            fname = hashlib.md5(image_url.encode()).hexdigest() + ext
            save_path = os.path.join(app.root_path, 'static/uploads', fname)
            with open(save_path, 'wb') as f:
                f.write(img_resp.content)
            image_path = os.path.join('static/uploads', fname)
    except Exception:
        pass

    # Kookboek automatisch aanmaken/opzoeken op basis van het domein
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


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        default_serves_raw = request.form.get('default_serves', '').strip()
        setting = Settings.query.filter_by(key='default_serves').first()
        if default_serves_raw:
            if setting:
                setting.value = default_serves_raw
            else:
                db.session.add(Settings(key='default_serves', value=default_serves_raw))
        else:
            if setting:
                db.session.delete(setting)
        db.session.commit()
        flash('Instellingen opgeslagen')
        return redirect(url_for('settings'))

    stats = {
        'recipes': Recipe.query.count(),
        'cookbooks': Cookbook.query.count(),
        'ingredients': Ingredient.query.count(),
    }
    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else None
    return render_template('settings.html', stats=stats, default_serves=default_serves)


@app.route('/export')
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
                        'name': ri.ingredient.name,
                        'category': ri.ingredient.category,
                        'amount': ri.amount,
                        'unit': ri.unit
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


@app.route('/import', methods=['POST'])
def import_data():
    try:
        file = request.files.get('file')
        if not file:
            return jsonify({'status': 'error', 'message': 'Geen bestand geselecteerd'}), 400

        data = json.loads(file.read().decode('utf-8'))
        counts = {'cookbooks': 0, 'recipes': 0, 'ingredients': 0}

        # Importeer kookboeken
        for cb_data in data.get('cookbooks', []):
            if not Cookbook.query.filter_by(name=cb_data['name']).first():
                db.session.add(Cookbook(
                    name=cb_data['name'],
                    abbreviation=cb_data.get('abbreviation')
                ))
                counts['cookbooks'] += 1
        db.session.commit()

        # Importeer recepten
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
                ingredient = Ingredient.query.filter_by(name=ing_data['name']).first()
                if not ingredient:
                    ingredient = Ingredient(
                        name=ing_data['name'],
                        category=ing_data.get('category', 'Overig')
                    )
                    db.session.add(ingredient)
                    db.session.flush()
                    counts['ingredients'] += 1

                db.session.add(RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=ing_data.get('amount', 0),
                    unit=ing_data.get('unit', '')
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


@app.route('/export/zip')
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
    uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
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


@app.route('/import/zip', methods=['POST'])
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
        uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)

        with zipfile.ZipFile(buf, 'r') as zf:
            if 'weekmenu_export.json' not in zf.namelist():
                return jsonify({'status': 'error', 'message': 'weekmenu_export.json niet gevonden in ZIP'}), 400

            data = json.loads(zf.read('weekmenu_export.json').decode('utf-8'))

            # Extract images (write directly to uploads, skip existing)
            for entry in zf.namelist():
                if entry.startswith('images/') and not entry.endswith('/'):
                    fname = os.path.basename(entry)
                    dest = os.path.join(uploads_dir, fname)
                    if not os.path.exists(dest):
                        with open(dest, 'wb') as f:
                            f.write(zf.read(entry))
                        counts['images'] += 1

            # Import cookbooks
            for cb_data in data.get('cookbooks', []):
                if not Cookbook.query.filter_by(name=cb_data['name']).first():
                    image_path = None
                    if cb_data.get('image_filename'):
                        candidate = os.path.join('static', 'uploads', cb_data['image_filename'])
                        if os.path.isfile(os.path.join(app.root_path, candidate)):
                            image_path = candidate
                    db.session.add(Cookbook(
                        name=cb_data['name'],
                        abbreviation=cb_data.get('abbreviation'),
                        image_path=image_path,
                        is_archived=cb_data.get('is_archived', False),
                    ))
                    counts['cookbooks'] += 1
            db.session.commit()

            # Import recipes
            for r_data in data.get('recipes', []):
                if Recipe.query.filter_by(name=r_data['name']).first():
                    continue

                cookbook = (Cookbook.query.filter_by(name=r_data['cookbook']).first()
                            if r_data.get('cookbook') else None)

                image_path = None
                if r_data.get('image_filename'):
                    candidate = os.path.join('static', 'uploads', r_data['image_filename'])
                    if os.path.isfile(os.path.join(app.root_path, candidate)):
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
                    db.session.add(RecipeIngredient(
                        recipe_id=recipe.id,
                        ingredient_id=ingredient.id,
                        amount=ing_data.get('amount') or 0,
                        unit=ing_data.get('unit', ''),
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


def migrate_db():
    with db.engine.connect() as conn:
        recipe_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(recipe)')).fetchall()]
        for col, col_def in [('url', 'TEXT'), ('instructions', 'TEXT'), ('serves', 'INTEGER')]:
            if col not in recipe_cols:
                try:
                    conn.execute(text(f'ALTER TABLE recipe ADD COLUMN {col} {col_def}'))
                except OperationalError:
                    pass

        menu_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(menu_item)')).fetchall()]
        if 'people_count' not in menu_cols:
            try:
                conn.execute(text('ALTER TABLE menu_item ADD COLUMN people_count INTEGER'))
            except OperationalError:
                pass
        if 'skip_shopping_list' not in menu_cols:
            try:
                conn.execute(text('ALTER TABLE menu_item ADD COLUMN skip_shopping_list BOOLEAN NOT NULL DEFAULT 0'))
            except OperationalError:
                pass

        cookbook_cols = [row[1] for row in conn.execute(text('PRAGMA table_info(cookbook)')).fetchall()]
        if 'is_archived' not in cookbook_cols:
            try:
                conn.execute(text('ALTER TABLE cookbook ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0'))
            except OperationalError:
                pass

        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                key VARCHAR(50) NOT NULL UNIQUE,
                value VARCHAR(200)
            )
        '''))

        conn.commit()


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        migrate_db()
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)
    app.run(host='0.0.0.0', port=5001, debug=True)