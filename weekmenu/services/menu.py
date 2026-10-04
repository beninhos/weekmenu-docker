from datetime import datetime

from weekmenu.extensions import db
from weekmenu.models import (
    Recipe, MenuItem, CustomShoppingIngredient, QuickAddItem,
    ShoppingListExclusion, ShoppingListOverride,
)
from weekmenu.services import afgehandeld
from weekmenu.services.shopping import bijdrage_van_regel, omrekening


def stem_af_op_de_week(year, week, ingredient_id, lopende_weken):
    """Uit de voorraad halen: in een lopende week weer helemaal open, in een
    week die geweest is dicht.

    'Ik heb het toch niet in huis' zegt iets over nu en spreekt een vinkje van
    voor de voorraad tegen; het is het enige gebaar dat afgevinkt en
    weggehaald wist. `lopende_weken` komt van services.shopping.lopende_weken()
    en wordt door de aanroeper een keer opgehaald.
    """
    if (year, week) in lopende_weken:
        afgehandeld.zet_terug(year, week, ingredient_id)
    else:
        afgehandeld.sluit_af(year, week, ingredient_id)


def _neem_over(neem_over, week, year, recept_ids):
    """'Zelfde maaltijd': het losse recept gaat op in het weekmenu.

    Alleen een los recept uit dezelfde week, van een recept dat nu echt in het
    menu staat. Anders verdwijnt een extra set stil: van een andere week, of
    omdat het vak na 'Ja' weer leeg of anders werd voor het opslaan.
    """
    ids = [int(i) for i in neem_over or ()]
    if ids and recept_ids:
        QuickAddItem.query.filter(QuickAddItem.id.in_(ids),
                                  QuickAddItem.year == year,
                                  QuickAddItem.week_number == week,
                                  QuickAddItem.recipe_id.in_(recept_ids)).delete(
                                      synchronize_session=False)


def plan_recipe(recipe_id, day, meal_type, week, year, people_count, ingredient_ids,
                neem_over=()):
    """Plan een recept op een dag/maaltijd; uitgevinkte ingrediënten heb je al.

    Plannen zet alleen de nieuwe hoeveelheid op de lijst: wat al afgevinkt of
    weggehaald is blijft dat (Rutger, 4 okt 2026). Een uitgevinkt ingredient
    ('heb ik al') haalt alleen het deel van dít recept weg, niet de hele week.
    """
    recipe = db.get_or_404(Recipe, recipe_id)

    existing = MenuItem.query.filter_by(
        week_number=week, year=year, day_of_week=day, meal_type=meal_type
    ).first()
    if existing:
        existing.recipe_id = recipe_id
        existing.people_count = people_count
        existing.skip_shopping_list = False
    else:
        db.session.add(MenuItem(
            day_of_week=day, meal_type=meal_type,
            recipe_id=recipe_id, people_count=people_count,
            week_number=week, year=year,
            skip_shopping_list=False
        ))

    recipe.usage_count = (recipe.usage_count or 0) + 1
    recipe.last_used = datetime.now()

    omr = omrekening()
    for ri in recipe.ingredients:
        if ri.id not in ingredient_ids:
            ing, eenheid, hoeveel = bijdrage_van_regel(ri, recipe.serves, people_count, omr)
            afgehandeld.haal_weg(year, week, ing, {eenheid: hoeveel})

    _neem_over(neem_over, week, year, {recipe_id})
    db.session.commit()


def update_week_menu(week, year, menu_data, neem_over=()):
    """Sla het hele weekmenu op.

    Opslaan zet nooit iets terug: wat er bij komt staat vanzelf open, wat al
    afgevinkt of weggehaald is blijft dat. Een recept dat er nieuw bij komt
    telt mee in usage_count.
    """
    oude_recepten = {mi.recipe_id for mi in
                     MenuItem.query.filter_by(week_number=week, year=year).all()}
    MenuItem.query.filter_by(week_number=week, year=year).delete()

    gebruikt = set()
    for day in menu_data:
        for meal_type, meal_data in day['meals'].items():
            if isinstance(meal_data, dict):
                recipe_id = meal_data.get('recipe_id')
                people_count_raw = meal_data.get('people_count')
                try:
                    people_count = int(people_count_raw) if people_count_raw is not None else None
                except (ValueError, TypeError):
                    people_count = None
            else:
                recipe_id = meal_data
                people_count = None

            if recipe_id:
                recipe_id = int(recipe_id)
                gebruikt.add(recipe_id)
                db.session.add(MenuItem(
                    day_of_week=day['day'],
                    meal_type=meal_type,
                    recipe_id=recipe_id,
                    people_count=people_count,
                    week_number=week,
                    year=year
                ))

    for recipe_id in gebruikt:
        recipe = db.session.get(Recipe, recipe_id)
        if not recipe:
            continue
        if recipe_id not in oude_recepten:
            recipe.usage_count = (recipe.usage_count or 0) + 1
        recipe.last_used = datetime.now()

    _neem_over(neem_over, week, year, gebruikt)
    db.session.commit()


def clear_week(week, year):
    """Wis alle menu items en gerelateerde data voor een week."""
    MenuItem.query.filter_by(week_number=week, year=year).delete()
    CustomShoppingIngredient.query.filter_by(week_number=week, year=year).delete()
    ShoppingListExclusion.query.filter_by(week_number=week, year=year).delete()
    ShoppingListOverride.query.filter_by(week_number=week, year=year).delete()
    db.session.commit()
