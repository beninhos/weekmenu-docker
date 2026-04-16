"""Generic recipe scoring by boost-ingredients.

Used by Ecobooster ("bijna-op"-items), and prepared for future Flyer
(aanbiedingen) and Seasonal (seizoens-groente) features. All three share the
same shape: a set of ingredient ids gets boosted, each recipe gets an
eco-style match-score, results are sorted by missing-count ascending.
"""
from weekmenu.models import Recipe, PantryIngredient


def score_recipes(boost_ids, source='ecobooster'):
    """Score recipes by overlap with `boost_ids`.

    Args:
        boost_ids: iterable of ingredient ids to treat as "already available"
            or "preferred" (e.g. bijna-op-ingrediënten, items uit folder,
            seizoens-groente).
        source: label passed through on each result so the frontend can
            distinguish why a recipe is recommended ('ecobooster' | 'flyer' |
            'season').

    Returns:
        list[dict] sorted by (missing_count asc, score desc).
    """
    boost_ids = set(boost_ids or [])
    if not boost_ids:
        return []

    pantry_ids = {p.ingredient_id for p in PantryIngredient.query.all()}
    all_available = boost_ids | pantry_ids

    results = []
    for recipe in Recipe.query.all():
        ri_list = recipe.ingredients
        ri_ids = {ri.ingredient_id for ri in ri_list}
        total = len(ri_ids)
        if total == 0:
            continue

        matched_boost = boost_ids & ri_ids
        if not matched_boost:
            continue

        matched_pantry = pantry_ids & ri_ids
        score = round((len(matched_boost) + len(matched_pantry)) / total * 100)
        missing = [ri.ingredient.display for ri in ri_list
                   if ri.ingredient_id not in all_available]

        results.append({
            'id': recipe.id,
            'name': recipe.name,
            'is_favorite': recipe.is_favorite,
            'cookbook': recipe.cookbook.abbreviation if recipe.cookbook else None,
            'page': recipe.page,
            'serves': recipe.serves,
            'eco_score': score,
            'missing': missing,
            'missing_count': len(missing),
            'source': source,
        })

    results.sort(key=lambda x: (x['missing_count'], -x['eco_score']))
    return results
