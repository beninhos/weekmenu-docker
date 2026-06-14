from flask import Blueprint, render_template, request

from weekmenu.constants import MONTH_NAMES_NL
from weekmenu.services.seasons import current_month, resolve_seasonal_ingredients
from weekmenu.services.recipe_matcher import score_recipes


bp = Blueprint('inspiratie', __name__)


@bp.route('/inspiratie')
def inspiratie():
    tab = request.args.get('tab', 'ecobooster')
    if tab not in ('ecobooster', 'seizoen'):
        tab = 'ecobooster'

    ctx = {'active_tab': tab}

    if tab == 'seizoen':
        month = current_month()
        items = resolve_seasonal_ingredients(month)
        boost_ids = {id for i in items for id in i['ingredient_ids']}
        ctx.update(
            month_name=MONTH_NAMES_NL[month - 1],
            items=items,
            recipes=score_recipes(boost_ids, source='season'),
        )

    return render_template('inspiratie.html', **ctx)
