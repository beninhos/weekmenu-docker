from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from werkzeug.utils import secure_filename
import os
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
    serves = db.Column(db.Integer, default=4)  # NIEUW: aantal personen
    cookbook_id = db.Column(db.Integer, db.ForeignKey('cookbook.id'), nullable=True)
    page = db.Column(db.Integer)
    image_path = db.Column(db.String(200), nullable=True)
    is_favorite = db.Column(db.Boolean, default=False)  # NIEUW: favorieten
    last_used = db.Column(db.DateTime, nullable=True)  # NIEUW: recent gebruikt
    usage_count = db.Column(db.Integer, default=0)  # NIEUW: gebruiksfrequentie
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
    people_count = db.Column(db.Integer, default=4)  # NIEUW: aantal personen voor dit menu item
    week_number = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    recipe = db.relationship('Recipe')

class Cookbook(db.Model):
    __tablename__ = 'cookbook'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    abbreviation = db.Column(db.String(10), nullable=True)  # NIEUW: afkorting veld
    image_path = db.Column(db.String(200), nullable=True)  # NIEUW: afbeelding veld
    
    # Relatie met recepten
    recipes = db.relationship('Recipe', back_populates='cookbook', lazy=True)

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
    return render_template('week_menu.html',
                         menu_items=menu_items,
                         recipes=recipes,
                         week=week,
                         year=year,
                         days=DAYS,
                         meal_types=MEAL_TYPES)

@app.route('/cookbook/<int:id>/recipes')
def list_cookbook_recipes(id):
    cookbook = Cookbook.query.get_or_404(id)
    # Sorteer recepten op paginanummer, recepten zonder pagina komen laatst
    recipes = sorted(cookbook.recipes, key=lambda x: (x.page is None, x.page or 0))
    return render_template('cookbook_recipes.html', cookbook=cookbook, recipes=recipes)

@app.route('/recipes')
def recipes():
    recipes = Recipe.query.all()
    return render_template('recipes.html', recipes=recipes)

@app.route('/recipe/new', methods=['GET', 'POST'])
def new_recipe():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    
    if request.method == 'POST':
        # Afbeelding uploaden
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
        
        recipe = Recipe(
            name=request.form['name'],
            serves=int(request.form.get('serves', 4)),
            cookbook_id=request.form.get('cookbook') if request.form.get('cookbook') else None,
            page=request.form['page'] if request.form['page'] else None,
            image_path=image_path
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
                
                recipe_ingredient = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=float(amounts[i]) if amounts[i] else 0,
                    unit=units[i]
                )
                db.session.add(recipe_ingredient)
        
        db.session.commit()
        return redirect(url_for('recipes'))
    
    return render_template('new_recipe.html', cookbooks=cookbooks)

@app.route('/recipe/<int:id>', methods=['DELETE'])
def delete_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    db.session.delete(recipe)
    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/cookbooks')
def list_cookbooks():
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    return render_template('cookbooks.html', cookbooks=cookbooks)

@app.route('/cookbook/new', methods=['GET', 'POST'])
def new_cookbook():
    if request.method == 'POST':
        cookbook_name = request.form['name']
        abbreviation = request.form.get('abbreviation', '').strip()
        
        # Controleer of cookbook al bestaat
        existing_cookbook = Cookbook.query.filter_by(name=cookbook_name).first()
        if existing_cookbook:
            flash('Dit kookboek bestaat al')
            return redirect(url_for('new_cookbook'))
        
        # Maak automatisch afkorting als geen opgegeven
        if not abbreviation:
            words = cookbook_name.split()
            abbreviation = ''.join(word[0].upper() for word in words if word)[:5]
        
        # Afbeelding uploaden
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
        
        # Update afkorting of maak automatisch aan
        if abbreviation:
            cookbook.abbreviation = abbreviation
        else:
            words = cookbook.name.split()
            cookbook.abbreviation = ''.join(word[0].upper() for word in words if word)[:5]
        
        # Afbeelding uploaden
        image = request.files.get('image')
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
            cookbook.image_path = image_path
        
        db.session.commit()
        return redirect(url_for('list_cookbooks'))
    
    return render_template('edit_cookbook.html', cookbook=cookbook)

@app.route('/update_menu', methods=['POST'])
def update_menu():
    try:
        data = request.get_json()
        
        # Haal oude menu items op om te zien welke posities er al waren
        old_items = MenuItem.query.filter_by(
            week_number=data['week'],
            year=data['year']
        ).all()
        
        # Verzamel oude menu posities (dag+maaltijd+recept)
        old_positions = set()
        for old_item in old_items:
            if old_item.recipe_id:
                position = (old_item.day_of_week, old_item.meal_type, old_item.recipe_id)
                old_positions.add(position)
        
        # Verwijder oude menu items
        MenuItem.query.filter_by(
            week_number=data['week'],
            year=data['year']
        ).delete()
        
        # Track welke menu posities worden toegevoegd
        new_positions = set()
        
        for day in data['menu']:
            for meal_type, meal_data in day['meals'].items():
                # Handle both old format (string) and new format (dict)
                if isinstance(meal_data, dict):
                    recipe_id = meal_data.get('recipe_id')
                    people_count = meal_data.get('people_count', 4)
                else:
                    # Backward compatibility
                    recipe_id = meal_data
                    people_count = 4
                
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
        
        # Verhoog usage_count voor elke nieuwe positie 
        truly_new_positions = new_positions - old_positions
        
        # Update usage statistics voor elke nieuwe positie
        for position in truly_new_positions:
            day, meal_type, recipe_id = position
            recipe = Recipe.query.get(recipe_id)
            if recipe:
                recipe.usage_count = (recipe.usage_count or 0) + 1
                recipe.last_used = datetime.now()
        
        # Update last_used voor alle gebruikte recepten
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

@app.route('/shopping-list/<int:year>/<int:week>')
def shopping_list(year, week):
    menu_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    shopping_dict = {}
    
    for item in menu_items:
        if item.recipe:
            # Calculate portion multiplier
            recipe_serves = item.recipe.serves or 4
            people_count = item.people_count or 4
            multiplier = people_count / recipe_serves
            
            for ri in item.recipe.ingredients:
                key = (ri.ingredient.name, ri.unit, ri.ingredient.category)
                adjusted_amount = ri.amount * multiplier
                
                if key in shopping_dict:
                    shopping_dict[key] += adjusted_amount
                else:
                    shopping_dict[key] = adjusted_amount
    
    shopping_list = [
        {
            'name': k[0], 
            'amount': format_amount(v),  # GEWIJZIGD: Slimme formatting
            'unit': k[1], 
            'category': k[2]
        }
        for k, v in shopping_dict.items()
    ]
    shopping_list.sort(key=lambda x: (x['category'], x['name']))
    
    return render_template('shopping_list.html',
                         shopping_list=shopping_list,
                         week=week,
                         year=year)

@app.route('/recipe/<int:id>/edit', methods=['GET', 'POST'])
def edit_recipe(id):
    recipe = Recipe.query.get_or_404(id)
    cookbooks = Cookbook.query.order_by(Cookbook.name).all()
    
    if request.method == 'POST':
        recipe.name = request.form['name']
        recipe.serves = int(request.form.get('serves', 4))
        recipe.cookbook_id = request.form.get('cookbook') if request.form.get('cookbook') else None
        recipe.page = request.form['page'] if request.form['page'] else None
        
        # Afbeelding uploaden
        image = request.files.get('image')
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
            recipe.image_path = image_path
        
        # Verwijder bestaande ingrediënten
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
                
                recipe_ingredient = RecipeIngredient(
                    recipe_id=recipe.id,
                    ingredient_id=ingredient.id,
                    amount=float(amounts[i]) if amounts[i] else 0,
                    unit=units[i]
                )
                db.session.add(recipe_ingredient)
        
        db.session.commit()
        return redirect(url_for('recipes'))
    
    return render_template('edit_recipe.html', recipe=recipe, cookbooks=cookbooks)

# NIEUWE ROUTES VOOR FAVORIETEN EN QUICK ACCESS

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

@app.route('/api/quick_access_recipes')
def get_quick_access_recipes():
    """API endpoint voor favorieten, recent en populaire recepten"""
    try:
        # Favorieten (max 10)
        favorites = Recipe.query.filter_by(is_favorite=True).order_by(Recipe.name).limit(10).all()
        
        # Recent gebruikt (max 10, laatste eerst)
        recent = Recipe.query.filter(Recipe.last_used.isnot(None)).order_by(Recipe.last_used.desc()).limit(10).all()
        
        # Populair (max 10, hoogste usage_count eerst)
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)    
    app.run(host='0.0.0.0', port=5001, debug=True)