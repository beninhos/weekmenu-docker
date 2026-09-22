from datetime import datetime

from weekmenu.extensions import db
from weekmenu.models import (
    Recipe, MenuItem, CustomShoppingIngredient,
    ShoppingListExclusion, ShoppingListOverride, ShoppingCheck,
)


def zet_terug_op_de_lijst(year, week, ingredient_id):
    """Rutgers regel: 'wat ik afvink gaat van de lijst — tot ik het opnieuw
    erop zet.' Elk gebaar waarmee hij iets op de lijst zet — plannen, een los
    recept toevoegen, een los item toevoegen — is dat 'opnieuw erop zetten':
    de afvink- én uitsluitstatus van dat ingredient in die week gaat weg, ook
    als de week al naar de AH is gestuurd. Zonder dit bleef een nieuw gepland
    recept onzichtbaar zodra de week eerder besteld was (nasi, 13 sep 2026).

    Alleen de week die je aanraakt, nooit alle weken: gemeten op 20 sep 2026
    haalde de weekloze variant de ui van de al gekochte vorige week terug op
    de lijst en telde hij 200 g bij de 100 g van deze week op.
    """
    ShoppingListExclusion.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).delete()
    ShoppingCheck.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).delete()


def houd_de_week_afgerond(year, week, ingredient_id):
    """De tegenhanger: zorg dat dit ingredient die week afgevinkt staat.

    Een recept bewerken voegt zijn regels toe aan elke week waarin het gepland
    staat, ook aan weken waarvoor je allang boodschappen hebt gedaan. Een nieuw
    ingredient heeft daar nooit een vinkje gehad en komt dus open te staan --
    een regel uit augustus, met de recepthint van toen. Voor een week die
    geweest is geldt hetzelfde als voor de rest: er wordt niets meer gekocht.
    """
    bestaat = ShoppingCheck.query.filter_by(
        year=year, week_number=week, ingredient_id=ingredient_id
    ).first()
    if not bestaat:
        db.session.add(ShoppingCheck(year=year, week_number=week,
                                     ingredient_id=ingredient_id))


def stem_af_op_de_week(year, week, ingredient_id, lopende_weken):
    """Een zijdelingse wijziging laat een week niet van status wisselen.

    Leeft de week nog, dan hoort de wijziging zichtbaar te worden. Is hij
    afgerond, dan blijft hij dicht. `lopende_weken` komt van
    services.shopping.lopende_weken() en wordt door de aanroeper een keer
    opgehaald -- per ingredient opnieuw bouwen kost de hele lijst.
    """
    if (year, week) in lopende_weken:
        zet_terug_op_de_lijst(year, week, ingredient_id)
    else:
        houd_de_week_afgerond(year, week, ingredient_id)


def plan_recipe(recipe_id, day, meal_type, week, year, people_count, ingredient_ids):
    """Plan een recept op een specifieke dag/maaltijd met ingredient-selectie."""
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

    # Exclude unchecked ingredients via ShoppingListExclusion
    for ri in recipe.ingredients:
        if ri.id not in ingredient_ids:
            excl_exists = ShoppingListExclusion.query.filter_by(
                year=year, week_number=week, ingredient_id=ri.ingredient_id
            ).first()
            if not excl_exists:
                db.session.add(ShoppingListExclusion(
                    year=year, week_number=week, ingredient_id=ri.ingredient_id
                ))
        else:
            zet_terug_op_de_lijst(year, week, ri.ingredient_id)

    db.session.commit()


def update_week_menu(week, year, menu_data):
    """Bulk update alle menu items voor een week.

    Een positie is (dag, maaltijd, recept, personen). Elke positie die er
    vóór het opslaan niet was — nieuw recept, hetzelfde recept op een extra
    dag, of een ander aantal personen — telt als 'opnieuw op de lijst zetten'
    en wist afvink- en uitsluitstatus van dat recept in die week. Een recept
    alleen naar een andere dag schuiven verandert de boodschappen niet en laat
    de status dus staan.
    """
    old_items = MenuItem.query.filter_by(week_number=week, year=year).all()
    old_positions = set()
    for old_item in old_items:
        if old_item.recipe_id:
            old_positions.add((old_item.meal_type, old_item.recipe_id, old_item.people_count))

    MenuItem.query.filter_by(week_number=week, year=year).delete()

    new_positions = set()
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
                new_positions.add((meal_type, recipe_id, people_count))
                db.session.add(MenuItem(
                    day_of_week=day['day'],
                    meal_type=meal_type,
                    recipe_id=recipe_id,
                    people_count=people_count,
                    week_number=week,
                    year=year
                ))

    truly_new_recipe_ids = {pos[1] for pos in new_positions} - {pos[1] for pos in old_positions}
    for rid in {pos[1] for pos in new_positions - old_positions}:
        recipe = db.session.get(Recipe, rid)
        if not recipe:
            continue
        if rid in truly_new_recipe_ids:
            recipe.usage_count = (recipe.usage_count or 0) + 1
            recipe.last_used = datetime.now()
        for ri in recipe.ingredients:
            zet_terug_op_de_lijst(year, week, ri.ingredient_id)

    used_recipe_ids = {pos[1] for pos in new_positions}
    for recipe_id in used_recipe_ids:
        recipe = db.session.get(Recipe, recipe_id)
        if recipe:
            recipe.last_used = datetime.now()

    db.session.commit()


def clear_week(week, year):
    """Wis alle menu items en gerelateerde data voor een week."""
    MenuItem.query.filter_by(week_number=week, year=year).delete()
    CustomShoppingIngredient.query.filter_by(week_number=week, year=year).delete()
    ShoppingListExclusion.query.filter_by(week_number=week, year=year).delete()
    ShoppingListOverride.query.filter_by(week_number=week, year=year).delete()
    db.session.commit()


def clear_shopping_list(week, year):
    """Wis de boodschappenlijst: verberg items zonder recepten te verwijderen."""
    MenuItem.query.filter_by(
        week_number=week, year=year, skip_shopping_list=False
    ).update({'skip_shopping_list': True})
    CustomShoppingIngredient.query.filter_by(week_number=week, year=year).delete()
    ShoppingListExclusion.query.filter_by(week_number=week, year=year).delete()
    ShoppingListOverride.query.filter_by(week_number=week, year=year).delete()
    db.session.commit()
