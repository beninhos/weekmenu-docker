from datetime import datetime
from weekmenu.extensions import db


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
    display_name = db.Column(db.String(100), nullable=False, default='')
    category = db.Column(db.String(50), nullable=False)
    ah_product_id      = db.Column(db.Integer, nullable=True)
    ah_product_name    = db.Column(db.String(200), nullable=True)
    ah_product_size    = db.Column(db.String(50), nullable=True)
    ah_product_price   = db.Column(db.String(20), nullable=True)
    ah_product_image   = db.Column(db.String(500), nullable=True)
    ah_product_bonus   = db.Column(db.Boolean, default=False)
    ah_product_updated = db.Column(db.Integer, nullable=True)
    ah_product_color   = db.Column(db.String(20), nullable=True)
    ah_product_was_price       = db.Column(db.String(20), nullable=True)
    ah_product_bonus_mechanism = db.Column(db.String(100), nullable=True)
    ah_product_brand           = db.Column(db.String(100), nullable=True)
    ah_product_category        = db.Column(db.String(100), nullable=True)
    ah_pkg_qty         = db.Column(db.Float, nullable=True)
    ah_pkg_unit        = db.Column(db.String(20), nullable=True)
    ah_conv_factor     = db.Column(db.Float, nullable=True)
    ah_conv_unit       = db.Column(db.String(20), nullable=True)
    preferred_unit     = db.Column(db.String(20), nullable=True)

    @property
    def display(self):
        return self.display_name or self.name


class IngredientUnitConversion(db.Model):
    __tablename__ = 'ingredient_unit_conversion'
    id            = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    from_unit     = db.Column(db.String(20), nullable=False)
    to_unit       = db.Column(db.String(20), nullable=False)
    factor        = db.Column(db.Float, nullable=False)
    confidence    = db.Column(db.Float, nullable=True)
    reasoning     = db.Column(db.Text, nullable=True)
    ingredient    = db.relationship('Ingredient', backref='unit_conversions')


class IngredientAlias(db.Model):
    __tablename__ = 'ingredient_alias'
    id = db.Column(db.Integer, primary_key=True)
    alias = db.Column(db.String(100), nullable=False, unique=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    ingredient = db.relationship('Ingredient', backref='aliases')


class RecipeIngredient(db.Model):
    __tablename__ = 'recipe_ingredient'
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipe.id'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    preparation = db.Column(db.String(100), nullable=True)
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


class ShoppingListOverride(db.Model):
    __tablename__ = 'shopping_list_override'
    __table_args__ = (
        db.UniqueConstraint('year', 'week_number', 'ingredient_id',
                            name='uq_override_week_ingredient'),
    )
    id            = db.Column(db.Integer, primary_key=True)
    year          = db.Column(db.Integer, nullable=False)
    week_number   = db.Column(db.Integer, nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
    qty           = db.Column(db.Integer, nullable=False)


class PantryIngredient(db.Model):
    __tablename__ = 'pantry_ingredient'
    id            = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False, unique=True)
    ingredient    = db.relationship('Ingredient')


class ShoppingListExclusion(db.Model):
    __tablename__ = 'shopping_list_exclusion'
    __table_args__ = (
        db.UniqueConstraint('year', 'week_number', 'ingredient_id',
                            name='uq_exclusion_week_ingredient'),
    )
    id            = db.Column(db.Integer, primary_key=True)
    year          = db.Column(db.Integer, nullable=False)
    week_number   = db.Column(db.Integer, nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredient.id'), nullable=False)
