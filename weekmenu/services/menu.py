from datetime import datetime

from weekmenu.extensions import db
from weekmenu.models import (
    Recipe, MenuItem, CustomShoppingIngredient,
    ShoppingListExclusion, ShoppingListOverride,
)


def plan_recipe(recipe_id, day, meal_type, week, year, people_count, ingredient_ids):
    """Plan een recept op een specifieke dag/maaltijd met ingredient-selectie."""
    recipe = Recipe.query.get_or_404(recipe_id)

    existing = MenuItem.query.filter_by(
        week_number=week, year=year, day_of_week=day, meal_type=meal_type
    ).first()
    if existing:
        existing.recipe_id = recipe_id
        existing.people_count = people_count
        existing.skip_shopping_list = False
    else:
        db.session.add(MenuItem(
            day_of_week=day, meal_type=meal_type,
            recipe_id=recipe_id, people_count=people_count,
            week_number=week, year=year,
            skip_shopping_list=False
        ))

    recipe.usage_count = (recipe.usage_count or 0) + 1
    recipe.last_used = datetime.now()

    # Exclude unchecked ingredients via ShoppingListExclusion
    for ri in recipe.ingredients:
        if ri.id not in ingredient_ids:
            excl_exists = ShoppingListExclusion.query.filter_by(
                year=year, week_number=week, ingredient_id=ri.ingredient_id
            ).first()
            if not excl_exists:
                db.session.add(ShoppingListExclusion(
                    year=year, week_number=week, ingredient_id=ri.ingredient_id
                ))
        else:
            ShoppingListExclusion.query.filter_by(
                year=year, week_number=week, ingredient_id=ri.ingredient_id
            ).delete()

    db.session.commit()


def update_week_menu(week, year, menu_data):
    """Bulk update alle menu items voor een week.

    BUG 1 FIX: Bij nieuw toegevoegde recepten worden stale
    ShoppingListExclusion records opgeruimd, zodat ingrediënten
    die via favorieten worden toegevoegd correct op de boodschappenlijst komen.
    """
    old_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    old_positions = set()
    for old_item in old_items:
        if old_item.recipe_id:
            old_positions.add((old_item.day_of_week, old_item.meal_type, old_item.recipe_id))

    MenuItem.query.filter_by(week_number=week, year=year).delete()

    new_positions = set()
    for day in menu_data:
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
                new_positions.add((day['day'], meal_type, recipe_id))
                db.session.add(MenuItem(
                    day_of_week=day['day'],
                    meal_type=meal_type,
                    recipe_id=recipe_id,
                    people_count=people_count,
                    week_number=week,
                    year=year
                ))

    # BUG 1 FIX: ruim stale exclusions op voor nieuw toegevoegde recepten
    truly_new_recipe_ids = {pos[2] for pos in new_positions} - {pos[2] for pos in old_positions}
    for rid in truly_new_recipe_ids:
        recipe = Recipe.query.get(rid)
        if recipe:
            recipe.usage_count = (recipe.usage_count or 0) + 1
            recipe.last_used = datetime.now()
            # Verwijder exclusions voor ingrediënten van dit recept
            for ri in recipe.ingredients:
                ShoppingListExclusion.query.filter_by(
                    year=year, week_number=week, ingredient_id=ri.ingredient_id
                ).delete()

    used_recipe_ids = {pos[2] for pos in new_positions}
    for recipe_id in used_recipe_ids:
        recipe = Recipe.query.get(recipe_id)
        if recipe:
            recipe.last_used = datetime.now()

    db.session.commit()


def clear_week(week, year):
    """Wis alle menu items en gerelateerde data voor een week."""
    MenuItem.query.filter_by(week_number=week, year=year).delete()
    CustomShoppingIngredient.query.filter_by(week_number=week, year=year).delete()
    ShoppingListExclusion.query.filter_by(week_number=week, year=year).delete()
    ShoppingListOverride.query.filter_by(week_number=week, year=year).delete()
    db.session.commit()


def clear_shopping_list(week, year):
    """Wis de boodschappenlijst: verberg items zonder recepten te verwijderen."""
    MenuItem.query.filter_by(
        week_number=week, year=year, skip_shopping_list=False
    ).update({'skip_shopping_list': True})
    CustomShoppingIngredient.query.filter_by(week_number=week, year=year).delete()
    ShoppingListExclusion.query.filter_by(week_number=week, year=year).delete()
    ShoppingListOverride.query.filter_by(week_number=week, year=year).delete()
    db.session.commit()
