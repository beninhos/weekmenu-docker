"""Pantry CRUD — items marked as "altijd op voorraad", used by shopping-list filter and Ecobooster."""
from weekmenu.extensions import db
from weekmenu.models import PantryIngredient


def list_pantry():
    """Return all pantry items as a list of dicts for the API."""
    items = PantryIngredient.query.order_by(PantryIngredient.id).all()
    return [{
        'id': p.id,
        'ingredient_id': p.ingredient_id,
        'name': p.ingredient.display,
    } for p in items]


def add_to_pantry(ingredient_id):
    """Add an ingredient to the pantry. Returns (result_dict, status_code)."""
    if not ingredient_id:
        return {'status': 'error', 'message': 'ingredient_id verplicht'}, 400

    existing = PantryIngredient.query.filter_by(ingredient_id=ingredient_id).first()
    if existing:
        return {'status': 'exists'}, 200

    p = PantryIngredient(ingredient_id=ingredient_id)
    db.session.add(p)
    db.session.commit()
    return {
        'status': 'ok',
        'id': p.id,
        'ingredient_id': p.ingredient_id,
        'name': p.ingredient.display,
    }, 200


def remove_from_pantry(ingredient_id):
    """Remove an ingredient from the pantry (idempotent)."""
    p = PantryIngredient.query.filter_by(ingredient_id=ingredient_id).first()
    if p:
        db.session.delete(p)
        db.session.commit()
    return {'status': 'ok'}
