import time

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash

from weekmenu.changelog import WIJZIGINGEN
from weekmenu.extensions import db
from weekmenu.models import Recipe, Cookbook, Ingredient, Settings
from weekmenu.services.gemini import _get_gemini_api_key
from weekmenu.services.shopping import UITGANG_KEUZES, huidige_uitgang

bp = Blueprint('settings', __name__)


@bp.route('/wat-is-er-nieuw')
def wat_is_er_nieuw():
    return render_template('changelog.html', wijzigingen=WIJZIGINGEN)


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
        uitgang = request.form.get('uitgang')
        if uitgang in UITGANG_KEUZES:
            setting = Settings.query.filter_by(key='uitgang').first()
            if setting:
                setting.value = uitgang
            else:
                db.session.add(Settings(key='uitgang', value=uitgang))
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
    return render_template('settings.html', stats=stats, default_serves=default_serves,
                           uitgang=huidige_uitgang())


@bp.route('/api/gemini/key', methods=['POST', 'DELETE'])
def gemini_key():
    if request.method == 'DELETE':
        setting = Settings.query.filter_by(key='gemini_api_key').first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
        return jsonify({'status': 'success'})

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
    return jsonify({'status': 'success'})


@bp.route('/api/gemini/status')
def gemini_status():
    configured = bool(_get_gemini_api_key())
    return jsonify({'configured': configured})


@bp.route('/api/vision/key', methods=['POST', 'DELETE'])
def vision_key():
    if request.method == 'DELETE':
        setting = Settings.query.filter_by(key='vision_api_key').first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
        return jsonify({'status': 'success'})

    data = request.get_json() or {}
    api_key = data.get('key', '').strip()
    if not api_key:
        return jsonify({'status': 'error', 'message': 'Geen API key opgegeven'}), 400

    # Meteen uitproberen: een verse sleutel werkt meestal nog niet omdat de
    # Vision-API in het project nog uitstaat. Dat hoor je hier te merken en niet
    # pas halverwege een import, want die draait in een achtergrondthread.
    from weekmenu.services.ocr import verify_vision_key
    werkt, reden = verify_vision_key(api_key)
    if werkt is False:
        return jsonify({'status': 'error', 'message': reden}), 400

    setting = Settings.query.filter_by(key='vision_api_key').first()
    if setting:
        setting.value = api_key
    else:
        setting = Settings(key='vision_api_key', value=api_key)
        db.session.add(setting)
    db.session.commit()
    if werkt is None:
        return jsonify({'status': 'success', 'warning':
                        f'Sleutel opgeslagen, maar niet kunnen controleren: {reden}'})
    return jsonify({'status': 'success'})


@bp.route('/api/vision/status')
def vision_status():
    from weekmenu.services.ocr import vision_configured
    return jsonify({'configured': vision_configured()})
