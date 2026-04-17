from flask import Blueprint, render_template

from weekmenu.services.seasons import (
    current_month, MONTH_NAMES_NL, resolve_seasonal_ingredients,
)
from weekmenu.services.recipe_matcher import score_recipes


bp = Blueprint('seasons', __name__)


@bp.route('/seasons')
def seasons():
    month = current_month()
    items = resolve_seasonal_ingredients(month)
    boost_ids = {id for i in items for id in i['ingredient_ids']}
    recipes = score_recipes(boost_ids, source='season')
    return render_template(
        'seasons.html',
        month_name=MONTH_NAMES_NL[month - 1],
        items=items,
        recipes=recipes,
    )
