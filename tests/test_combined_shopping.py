import json
from datetime import date, datetime, timedelta

from weekmenu.extensions import db
from weekmenu.models import (
    Cookbook, Ingredient, MenuItem, QuickAddItem, Recipe, RecipeIngredient,
    ShoppingCheck,
)
from weekmenu.services.shopping import build_combined_shopping_list, window_weeks

TODAY = date(2026, 7, 11)  # zaterdag, ISO-week 28


def _mk_recipe(name, ing_name, amount, unit='g', serves=4):
    ing = Ingredient.query.filter_by(name=ing_name).first()
    if not ing:
        ing = Ingredient(name=ing_name, display_name=ing_name, category='overig')
        db.session.add(ing)
        db.session.flush()
    r = Recipe(name=name, serves=serves)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=amount, unit=unit))
    db.session.flush()
    return r, ing


def _plan(recipe, year, week, day=0):
    db.session.add(MenuItem(day_of_week=day, meal_type='avond',
                            recipe_id=recipe.id, week_number=week, year=year))
    db.session.flush()


def test_window_weeks_covers_prev_to_plus_two(app):
    weeks = window_weeks(today=TODAY)
    assert (2026, 27) in weeks and (2026, 28) in weeks
    assert (2026, 29) in weeks and (2026, 30) in weeks


def test_same_ingredient_two_weeks_merges_and_checks_partially(app):
    r1, ing = _mk_recipe('Dal wk28', 'rode linzen', 200)
    r2, _ = _mk_recipe('Dal wk29', 'rode linzen', 300)
    _plan(r1, 2026, 28)
    _plan(r2, 2026, 29)

    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['name'].lower().startswith('rode linzen')]
    assert len(rows) == 1
    assert rows[0]['amount'] == 500  # 200 + 300 samengevoegd

    # week 28 afvinken → alleen 300 nog open
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    rows = [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert rows[0]['amount'] == 300

    # beide weken afgevinkt → rij naar checked
    db.session.add(ShoppingCheck(year=2026, week_number=29, ingredient_id=ing.id,
                                 via_ah=True))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]
    checked = [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert checked and checked[0]['via_ah'] is True


def test_checked_older_than_14_days_hidden(app):
    r, ing = _mk_recipe('Soep', 'prei', 2, unit='stuks')
    _plan(r, 2026, 28)
    db.session.add(ShoppingCheck(year=2026, week_number=28, ingredient_id=ing.id,
                                 checked_at=datetime(2026, 6, 1)))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert not [x for x in result['checked'] if x['ingredient_id'] == ing.id]
    assert not [x for x in result['open'] if x['ingredient_id'] == ing.id]


def test_quick_add_recipe_counts_and_old_manual_week_included(app):
    r, ing = _mk_recipe('Feestje', 'chips', 3, unit='zak')
    # QuickAddItem in een week buiten het venster (3 weken terug, week 25)
    db.session.add(QuickAddItem(recipe_id=r.id, people_count=4,
                                week_number=25, year=2026))
    db.session.commit()
    result = build_combined_shopping_list(today=TODAY)
    assert [x for x in result['open'] if x['ingredient_id'] == ing.id]
    assert any(q['recipe_id'] == r.id for q in result['quick_add'])
