from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from werkzeug.utils import secure_filename
import os
from pathlib import Path

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
    cookbook_id = db.Column(db.Integer, db.ForeignKey('cookbook.id'), nullable=True)
    page = db.Column(db.Integer)
    image_path = db.Column(db.String(200), nullable=True)
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
    week_number = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    recipe = db.relationship('Recipe')

class Cookbook(db.Model):
    __tablename__ = 'cookbook'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
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
        
        # Controleer of cookbook al bestaat
        existing_cookbook = Cookbook.query.filter_by(name=cookbook_name).first()
        if existing_cookbook:
            flash('Dit kookboek bestaat al')
            return redirect(url_for('new_cookbook'))
        
        # Afbeelding uploaden
        image = request.files.get('image')
        image_path = None
        if image and image.filename:
            filename = secure_filename(image.filename)
            image_path = os.path.join('static/uploads', filename)
            image.save(os.path.join(app.root_path, image_path))
        
        new_cookbook = Cookbook(name=cookbook_name, image_path=image_path)
        db.session.add(new_cookbook)
        db.session.commit()
        return redirect(url_for('list_cookbooks'))
    
    return render_template('new_cookbook.html')

@app.route('/cookbook/<int:id>/edit', methods=['GET', 'POST'])
def edit_cookbook(id):
    cookbook = Cookbook.query.get_or_404(id)
    
    if request.method == 'POST':
        cookbook.name = request.form['name']
        
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
        
        MenuItem.query.filter_by(
            week_number=data['week'],
            year=data['year']
        ).delete()
        
        for day in data['menu']:
            for meal_type, recipe_id in day['meals'].items():
                if recipe_id:
                    menu_item = MenuItem(
                        day_of_week=day['day'],
                        meal_type=meal_type,
                        recipe_id=recipe_id,
                        week_number=data['week'],
                        year=data['year']
                    )
                    db.session.add(menu_item)
        
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
            for ri in item.recipe.ingredients:
                key = (ri.ingredient.name, ri.unit, ri.ingredient.category)
                if key in shopping_dict:
                    shopping_dict[key] += ri.amount
                else:
                    shopping_dict[key] = ri.amount
    
    shopping_list = [
        {'name': k[0], 'amount': v, 'unit': k[1], 'category': k[2]}
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)    
    app.run(host='0.0.0.0', port=5001, debug=True)