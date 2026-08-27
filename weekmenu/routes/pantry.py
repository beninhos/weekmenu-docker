from flask import Blueprint, render_template, request, jsonify

from weekmenu.models import Ingredient, PantryIngredient
from weekmenu.constants import PRODUCT_CATEGORIES
from weekmenu.services.pantry import review_lists, set_category, set_bron


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
    """Waar de app zichzelf niet zeker weet: voorraadkandidaten, onbekende
    categorieen, en ingredienten waarvan de categorie afwijkt van de gok."""
    return render_template('twijfelgevallen.html',
                           lists=review_lists(),
                           categories=PRODUCT_CATEGORIES)


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
