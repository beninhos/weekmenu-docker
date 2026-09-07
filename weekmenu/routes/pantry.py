from flask import Blueprint, render_template, request, jsonify

from weekmenu.models import Ingredient, PantryIngredient
from weekmenu.constants import PRODUCT_CATEGORIES
from weekmenu.services.pantry import review_lists, set_category, set_bron
from weekmenu.services.ingredienten import (
    koppel_alias, markeer_apart, markeer_paar_apart, samenvoeg_kandidaten, voeg_samen,
)


bp = Blueprint('pantry', __name__)


@bp.route('/voorraad')
def pantry():
    items = (
        PantryIngredient.query
        .join(PantryIngredient.ingredient)
        .order_by(Ingredient.display_name)
        .all()
    )
    return render_template('pantry.html', pantry=items)


@bp.route('/twijfelgevallen')
def review():
    """Waar de app zichzelf niet zeker weet: dubbele ingredienten,
    voorraadkandidaten, onbekende categorieen, en ingredienten waarvan de
    categorie afwijkt van de gok."""
    return render_template('twijfelgevallen.html',
                           lists=review_lists(),
                           dubbel=samenvoeg_kandidaten(),
                           categories=PRODUCT_CATEGORIES)


@bp.route('/api/ingredienten/samenvoegen', methods=['POST'])
def samenvoegen():
    """Twee varianten tot één ingredient. Alleen op een klik, nooit vanzelf."""
    data = request.get_json() or {}
    payload, status = voeg_samen(data.get('verliezer_id'), data.get('winnaar_id'))
    return jsonify(payload), status


@bp.route('/api/ingredienten/apart', methods=['POST'])
def apart():
    """'Toch apart': dit paar of deze spelling niet meer voorstellen.

    Met `ander_id` gaat het om twee bestaande ingredienten (het overslaan van
    een voorstel), met `naam` om een spelling die nog geen eigen rij heeft
    (de vraag tijdens het importeren).
    """
    data = request.get_json() or {}
    if data.get('ander_id'):
        payload, status = markeer_paar_apart(data.get('ingredient_id'), data.get('ander_id'))
    else:
        payload, status = markeer_apart(data.get('naam'), data.get('ingredient_id'))
    return jsonify(payload), status


@bp.route('/api/ingredienten/alias', methods=['POST'])
def alias():
    """'Zelfde product': onthoud deze spelling bij dit ingredient."""
    data = request.get_json() or {}
    payload, status = koppel_alias(data.get('naam'), data.get('ingredient_id'))
    return jsonify(payload), status


@bp.route('/api/ingredient/<int:ingredient_id>/category', methods=['POST'])
def update_category(ingredient_id):
    data = request.get_json() or {}
    payload, status = set_category(ingredient_id, data.get('category'))
    return jsonify(payload), status


@bp.route('/api/ingredient/<int:ingredient_id>/bron', methods=['POST'])
def update_bron(ingredient_id):
    data = request.get_json() or {}
    payload, status = set_bron(ingredient_id, data.get('bron'))
    return jsonify(payload), status
