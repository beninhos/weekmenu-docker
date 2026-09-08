"""De enige plek waar een platte bereiding HTML wordt.

Een bereiding komt op twee manieren binnen. Uit het aanpasformulier komt hij
als HTML: Quill stuurt zijn eigen `root.innerHTML` mee. Uit een concept, een
link-import of een foto-import komt hij als PLATTE TEKST met regeleinden, met
de kopjes ('1. Snijden') op eigen regels.

Die twee moesten allebei door dezelfde deur, want alles verderop -- de
receptdetailkaart, de weekplanner, Quill in /recipe/<id>/edit -- zet de
bereiding met innerHTML in de pagina. Een \\n is daar gewone witruimte, dus
platte tekst liep aan elkaar tot één blok. Erger nog: wie zo'n recept één keer
opende in Bewerken kreeg die ene lap in Quill, en Quill schreef hem bij het
opslaan onherroepelijk zo terug naar de database.

Daarom gebeurt de omzetting hier, aan de SCHRIJFKANT: wat in recipe.instructions
staat is altijd HTML. Dat scheelt drie plekken die het ieder anders deden (het
aanpasformulier zette \\n om in <br>, de twee importknoppen deden niets), en
het houdt de leeskant dom -- die hoeft alleen nog te ontsmetten en te tonen.
Het concept zelf blijft platte tekst: de nakijkkaart toont hem met
white-space:pre-wrap, en die heeft de regeleinden nodig.
"""
import html
import re

# Genoeg om te zien dat er al opmaak in zit. Alleen blok-tags, want die zijn
# beslissend: Quill zet ELKE regel in een <p>, <li> of een kop, ook als er
# verder geen opmaak in staat. Op <strong>, <em>, <b> en <i> herkennen zou
# hier juist misgaan -- 'meng tot a < b' zou dan als opmaak worden opgevat en
# ongeschonden de database in gaan.
_LIJKT_OP_HTML = re.compile(
    r'<\s*/?(p|br|div|ol|ul|li|h[1-6]|blockquote|pre)\b', re.IGNORECASE)


def bereiding_naar_html(tekst):
    """Platte bereidingstekst omzetten naar alinea's; HTML blijft zoals hij is.

    Elke regel wordt een <p>, een lege regel een <p><br></p> -- precies de vorm
    die Quill zelf schrijft, zodat een rondje door het aanpasformulier niets
    verschuift. Leeg of alleen witruimte gaat onveranderd terug, zodat de
    aanroeper zijn eigen `or None` houdt.
    """
    if not tekst or not tekst.strip():
        return tekst
    if _LIJKT_OP_HTML.search(tekst):
        return tekst
    regels = tekst.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    return ''.join(
        '<p>{}</p>'.format(html.escape(regel.strip(), quote=False)) if regel.strip()
        else '<p><br></p>'
        for regel in regels
    )
