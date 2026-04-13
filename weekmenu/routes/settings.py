import time

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash

from weekmenu.extensions import db
from weekmenu.models import Recipe, Cookbook, Ingredient, Settings, PantryIngredient
from weekmenu.services.ah import _ah_setting
from weekmenu.services.recipes import _get_gemini_api_key

bp = Blueprint('settings', __name__)


@bp.route('/settings', methods=['GET', 'POST'])
def settings_page():
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
        return redirect(url_for('settings.settings_page'))

    stats = {
        'recipes': Recipe.query.count(),
        'cookbooks': Cookbook.query.count(),
        'ingredients': Ingredient.query.count(),
    }
    default_serves_setting = Settings.query.filter_by(key='default_serves').first()
    default_serves = int(default_serves_setting.value) if default_serves_setting and default_serves_setting.value else None
    ah_refresh = _ah_setting('ah_refresh_token')
    ah_expires = _ah_setting('ah_token_expires')
    ah_connected = bool(ah_refresh)
    ah_expires_dt = None
    if ah_expires:
        import datetime as _dt
        ah_expires_dt = _dt.datetime.fromtimestamp(int(ah_expires)).strftime('%d %b %Y')
    pantry = PantryIngredient.query.join(PantryIngredient.ingredient).order_by(Ingredient.display_name).all()
    return render_template('settings.html', stats=stats, default_serves=default_serves,
                           ah_connected=ah_connected, ah_expires_dt=ah_expires_dt,
                           pantry=pantry)


@bp.route('/api/gemini/key', methods=['POST', 'DELETE'])
def gemini_key():
    if request.method == 'DELETE':
        setting = Settings.query.filter_by(key='gemini_api_key').first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
        return jsonify({'status': 'ok'})

    data = request.get_json() or {}
    api_key = data.get('key', '').strip()
    if not api_key:
        return jsonify({'status': 'error', 'message': 'Geen API key opgegeven'}), 400

    setting = Settings.query.filter_by(key='gemini_api_key').first()
    if setting:
        setting.value = api_key
    else:
        setting = Settings(key='gemini_api_key', value=api_key)
        db.session.add(setting)
    db.session.commit()
    return jsonify({'status': 'ok'})


@bp.route('/api/gemini/status')
def gemini_status():
    configured = bool(_get_gemini_api_key())
    return jsonify({'configured': configured})
