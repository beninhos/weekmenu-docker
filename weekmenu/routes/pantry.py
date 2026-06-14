from flask import Blueprint, render_template

from weekmenu.models import Ingredient, PantryIngredient


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
