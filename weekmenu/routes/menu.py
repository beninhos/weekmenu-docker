import json
from datetime import date

from flask import Blueprint, render_template, request, jsonify

from weekmenu.extensions import db
from weekmenu.models import MenuItem, Recipe, Settings, QuickAddItem
from weekmenu.constants import DAYS, MEAL_TYPES
from weekmenu.services.menu import (
    plan_recipe, update_week_menu, clear_week, clear_shopping_list,
)

bp = Blueprint('menu', __name__)


@bp.route('/week/<int:year>/<int:week>')
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


@bp.route('/update_menu', methods=['POST'])
def update_menu():
    try:
        data = request.get_json()
        update_week_menu(data['week'], data['year'], data['menu'])
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/api/planner/plan', methods=['POST'])
def planner_plan():
    try:
        data = request.get_json()
        recipe_id = int(data['recipe_id'])
        day = int(data['day'])
        meal_type = data['meal_type']
        week = int(data['week'])
        year = int(data['year'])
        people_count = int(data.get('people_count') or 4)
        ingredient_ids = [int(i) for i in data.get('ingredient_ids', [])]

        plan_recipe(recipe_id, day, meal_type, week, year, people_count, ingredient_ids)
        return jsonify({'status': 'success'})

    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/clear_week_menu', methods=['POST'])
def clear_week_menu():
    try:
        data = request.get_json()
        clear_week(data['week'], data['year'])
        return jsonify({'status': 'success'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 400


@bp.route('/quick-add')
def quick_add():
    today = date.today()
    week_number = request.args.get('week', today.isocalendar()[1], type=int)
    year = request.args.get('year', today.year, type=int)

    recipes = Recipe.query.order_by(Recipe.name).all()

    saved_items = QuickAddItem.query.filter_by(
        week_number=week_number,
        year=year
    ).all()

    return render_template('quick_add.html',
                         recipes=recipes,
                         week=week_number,
                         year=year,
                         saved_items=saved_items)


@bp.route('/api/quick-add/save', methods=['POST'])
def save_quick_add():
    try:
        data = request.get_json()
        week = data['week']
        year = data['year']
        items = data['items']

        QuickAddItem.query.filter_by(
            week_number=week,
            year=year
        ).delete()

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


@bp.route('/api/quick-add/clear', methods=['POST'])
def clear_quick_add():
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
