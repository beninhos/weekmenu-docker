from datetime import date

from flask import Blueprint, redirect, request, url_for

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    today = date.today()
    iso = today.isocalendar()
    year, week_number = iso[0], iso[1]
    cookie = request.cookies.get('last_viewed_week', '')
    try:
        c_year, c_week = (int(p) for p in cookie.split('-'))
        if 1 <= c_week <= 53 and abs(c_year - year) <= 1:
            # Validate that the week actually exists for that year
            date.fromisocalendar(c_year, c_week, 1)
            year, week_number = c_year, c_week
    except (ValueError, AttributeError):
        pass
    return redirect(url_for('menu.week_menu', year=year, week=week_number))


@bp.route('/boodschappenlijst')
def boodschappenlijst_redirect():
    return redirect(url_for('shopping.boodschappen'))
