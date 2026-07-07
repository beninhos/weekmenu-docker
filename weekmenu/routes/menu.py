import json
from datetime import date, timedelta

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, make_response

from weekmenu.extensions import db
from weekmenu.models import MenuItem, Recipe, Settings
from weekmenu.constants import DAYS, MEAL_TYPES
from weekmenu.services.menu import (
    plan_recipe, update_week_menu, clear_week,
)

bp = Blueprint('menu', __name__)


@bp.route('/week/<int:year>/<int:week>')
def week_menu(year, week):
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError:
        iso = date.today().isocalendar()
        return redirect(url_for('menu.week_menu', year=iso[0], week=iso[1]))

    menu_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    recipes = Recipe.query.order_by(Recipe.name).all()
    recipes_json = json.dumps([{'id': r.id, 'name': r.name, 'serves': r.serves} for r in recipes])
    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else None
    sunday = monday + timedelta(days=6)
    MAANDEN = ['januari', 'februari', 'maart', 'april', 'mei', 'juni', 'juli',
               'augustus', 'september', 'oktober', 'november', 'december']
    week_range = f'ma {monday.day} {MAANDEN[monday.month-1][:3]} – zo {sunday.day} {MAANDEN[sunday.month-1][:3]}'
    prev_monday = monday - timedelta(days=7)
    next_monday = monday + timedelta(days=7)
    iso_now = date.today().isocalendar()
    extra_ctx = dict(
        week_range=week_range,
        prev_year=prev_monday.isocalendar()[0], prev_week=prev_monday.isocalendar()[1],
        next_year=next_monday.isocalendar()[0], next_week=next_monday.isocalendar()[1],
        current_year=iso_now[0], current_week=iso_now[1],
        is_current_week=(year == iso_now[0] and week == iso_now[1]),
    )

    resp = make_response(render_template('week_menu.html',
                         menu_items=menu_items,
                         recipes=recipes,
                         recipes_json=recipes_json,
                         week=week,
                         year=year,
                         days=DAYS,
                         meal_types=MEAL_TYPES,
                         default_serves=default_serves,
                         **extra_ctx))
    resp.set_cookie('last_viewed_week', f'{year}-{week}', max_age=1209600, samesite='Lax')
    return resp


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
    return redirect(url_for('shopping.boodschappen'), code=302)
