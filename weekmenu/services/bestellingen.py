"""Wat er per week echt gehaald is — los van de boodschappenlijst.

De lijst gaat sinds v21 alleen nog over lopende weken en vergeet de rest. Dat
is precies wat Rutger wil ('afgevinkt is afgevinkt, ik heb geen actieve
historie nodig'), maar het laat geen spoor na voor de vraag achteraf: wat kocht
ik, wat kostte het, wat was bonus. Dat spoor staat hier.

Eén pot per week. De AH-regels komen uit de order zelf en worden bij elke
snapshot ververst, want wat je uiteindelijk krijgt wijkt af zodra het magazijn
iets niet heeft. Wat je met de hand afvinkt -- de markt, de slager, of iets dat
nooit aan een AH-product is gekoppeld -- gaat in dezelfde pot en blijft staan.
"""
from datetime import datetime

from weekmenu.extensions import db
from weekmenu.models import Bestelling, BestellingRegel, Ingredient


def pot_voor(jaar, week):
    """De bestelling van die week; maak hem aan als hij er nog niet is."""
    pot = Bestelling.query.filter_by(year=jaar, week_number=week).first()
    if not pot:
        pot = Bestelling(year=jaar, week_number=week)
        db.session.add(pot)
        db.session.flush()
    return pot


def leg_ah_order_vast(jaar, week, order, bron='ah'):
    """Vervang de regels van deze bron voor die week door wat er nu in de order staat.

    Vervangen, niet aanvullen: een tweede blik op dezelfde order moet hetzelfde
    resultaat geven, ook als je er in de AH-app intussen iets bij hebt gedaan of
    het magazijn iets heeft laten vallen. De handmatige regels blijven staan --
    die kent de order niet.
    """
    if not order:
        return None

    pot = pot_voor(jaar, week)
    pot.ah_order_id = order.get('orderId') or pot.ah_order_id
    pot.orderstatus = order.get('orderState') or pot.orderstatus
    pot.bezorgdatum = order.get('deliveryDate') or pot.bezorgdatum
    pot.totaal = order.get('total')
    pot.besparing = order.get('savings')
    pot.bijgewerkt_op = datetime.now()

    for regel in [r for r in pot.regels if r.bron == bron]:
        db.session.delete(regel)

    per_product = {
        ing.ah_product_id: ing.id
        for ing in Ingredient.query.filter(Ingredient.ah_product_id.isnot(None)).all()
    }
    for groep in order.get('groups') or []:
        for item in groep.get('items') or []:
            pid = item.get('productId')
            db.session.add(BestellingRegel(
                bestelling_id=pot.id,
                bron=bron,
                ingredient_id=item.get('ingredient_id') or per_product.get(pid),
                ah_product_id=pid,
                titel=item.get('title') or '',
                merk=item.get('brand') or None,
                maat=item.get('size') or None,
                aantal=item.get('quantity') or 1,
                prijs=item.get('price'),
                was_prijs=item.get('wasPrice'),
                bonus=bool(item.get('isBonus')),
            ))
    db.session.commit()
    return pot


def leg_handmatig_vast(jaar, week, ingredient_id, aantal, eenheid, bron=None):
    """Een regel die je zelf afvinkt hoort in dezelfde pot als de AH-order.

    Zonder dit mist het log juist wat je niet bij de Appie haalt. Idempotent op
    (pot, ingredient): twee keer afvinken hoort niet twee keer te tellen.

    Nooit onder bron 'ah', ook niet als het ingredient daarop staat: die regels
    zijn eigendom van de order-snapshot en worden bij het verversen vervangen.
    Zelf afgevinkt betekent dat het níét uit de order kwam -- een product dat
    nooit aan de AH is gekoppeld, of iets dat je onderweg hebt meegenomen.
    """
    ing = db.session.get(Ingredient, ingredient_id)
    if not ing:
        return None

    bron = bron or ing.bron or 'handmatig'
    if bron == 'ah':
        bron = 'handmatig'

    pot = pot_voor(jaar, week)
    regel = BestellingRegel.query.filter_by(
        bestelling_id=pot.id, ingredient_id=ingredient_id).filter(
        BestellingRegel.bron != 'ah').first()
    if regel:
        regel.aantal = aantal
        regel.eenheid = eenheid
    else:
        db.session.add(BestellingRegel(
            bestelling_id=pot.id,
            bron=bron,
            ingredient_id=ingredient_id,
            titel=ing.display,
            aantal=aantal,
            eenheid=eenheid,
        ))
    pot.bijgewerkt_op = datetime.now()
    db.session.commit()
    return pot
