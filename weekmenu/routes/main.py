from datetime import date

from flask import Blueprint, redirect, url_for

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    today = date.today()
    week_number = today.isocalendar()[1]
    year = today.year
    return redirect(url_for('menu.week_menu', year=year, week=week_number))


@bp.route('/boodschappenlijst')
def boodschappenlijst_redirect():
    today = date.today()
    iso = today.isocalendar()
    return redirect(url_for('shopping.shopping_list', year=iso[0], week=iso[1]))
