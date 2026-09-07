import io
import json
import os
import re
import threading
import uuid

from flask import current_app

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft
from weekmenu.services.gemini import (
    _get_gemini_api_key, _sanitize_json, _build_gemini_ingredients, _UNITS_STR,
)
from weekmenu.services.ankers import knip_stappen
from weekmenu.services.kaart import (benodigdheden, controleer_tegen_tabel, kaart_invoer,
                                     paren, zonder_tabelregels)
from weekmenu.services.kaartsignaturen import bereidingstijd, is_voorkant, zonder_logo
from weekmenu.services.ocr import (_clean_ocr_text, lees_paginas, lees_paginas_met_annotaties,
                                   pages_as_labelled_text)

_ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/avif'}

_BATCH_PROMPT = f"""Hieronder staat de uitgelezen tekst van kookboekpagina's, per pagina gescheiden
door een regel '--- Pagina N ---'. Er kunnen MEERDERE recepten in staan.
Zet ALLE volledige recepten om naar JSON. Geef ALLEEN geldige JSON terug, geen markdown.

[
  {{
    "title": "Recept naam",
    "yields": 4,
    "photo_page": 2,
    "ingredients": [
      {{"name": "bloem", "amount": "200", "unit": "g"}},
      {{"name": "verse munt", "amount": "½", "unit": "bosje"}}
    ],
    "steps": [
      {{"start": "Verkruimel de gedroogde peper", "end": "laat hem even zo staan"}},
      {{"start": "Snijd de steeltjes van", "end": "schroei ze rondom"}}
    ]
  }}
]

Regels:
- Gebruik ALLEEN deze eenheden voor "unit": {_UNITS_STR}
- "amount" is TEKST: neem de hoeveelheid LETTERLIJK over uit de pagina ("½", "1½", "200").
  Reken breuken NIET zelf om naar decimalen; de software doet dat
- "name" is de ingrediëntnaam zonder hoeveelheid of eenheid
- Een ingrediënt dat over twee regels doorloopt is ÉÉN ingrediënt
  ("1 volle theelepel (zoet)" + "paprikapoeder" is samen 1 tl paprikapoeder)
- "volle" hoort niet bij de hoeveelheid: "1 volle theelepel harissa" is 1 tl harissa,
  "4 volle eetlepels yoghurt" is 4 el yoghurt
- Staat er OP DE INGREDIËNTREGEL wel een maat maar geen getal ("een handvol
  augurken", "een scheutje melk"), gebruik dan amount "1" met die maat als unit
- Een gewicht of inhoud die IN de ingrediëntregel staat is de hoeveelheid, ook
  achter "van" of tussen haakjes. Zet die in "amount"+"unit", niet in "name":
    "1 blik van 400 g gemengde bonen" -> amount "400", unit "g"
    "1 mok (300 g) bulghur"           -> amount "300", unit "g"
  Tussen haakjes staat het TOTAAL, dus niet vermenigvuldigen:
    "2 bundels asperges (600 g)"      -> amount "600", unit "g"
  Bij "van N g elk" of "à N g" is het gewicht PER stuk; vermenigvuldig aantal
  maal gewicht. Dit is de ENIGE berekening die je mag maken:
    "2 kipfilets van 200 g elk"       -> amount "400", unit "g"
    "2 blikken van 400 g linzen"      -> amount "800", unit "g"
  Breuken doen hier NOOIT aan mee: "½ komkommer" blijft "½"
- "steps": schrijf de bereidingstekst NIET over. Geef per bereidingsstap alleen
  de eerste 3 à 5 woorden ("start") en de laatste 3 à 5 woorden ("end"), exact
  zoals ze in de tekst staan (zelfde spelling, zelfde hoofdletters). De software
  knipt de stap zelf uit de tekst
- Een stap eindigt waar een nieuwe zin met een bullet of op een nieuwe alinea
  begint. Neem ALLE stappen op, van de eerste tot de laatste, en laat geen zin
  tussen twee stappen vallen
- "photo_page": het paginanummer waarop dit recept staat
- "yields": het aantal personen als dat op de pagina staat, anders null
- Neem alleen ingrediënten uit de INGREDIËNTENLIJST over, niet uit de bereiding.
  Staat "een snuf peper" alleen in een bereidingsstap, dan hoort het er niet bij
- Verzin NIETS dat niet in de tekst staat. Staat er op de ingrediëntregel echt
  geen hoeveelheid en ook geen maat ("olijfolie", "peper"), gebruik dan null
- "title": schrijf de titel in normale schrijfwijze, ook als de pagina hem in
  HOOFDLETTERS drukt ("KIP-DIMSUM" wordt "Kip-dimsum"). Behoud eigennamen,
  merknamen en afkortingen zoals ze horen (Cajun, Koreaanse, BBQ, Tikka)
- Staat er een hoofdtitel met daaronder een ondertitel? Verbind ze met " - "
- Sla onvolledige fragmenten (alleen een inhoudsopgave, half recept zonder ingrediënten) over
- Als er helemaal geen recept te vinden is: []
"""

# De kaartprompt deelt alle regels met de boekprompt (eenheden, breuken
# letterlijk, "volle", niets verzinnen, ankers) en verschilt alleen in de kop:
# één recept, de ingrediënten uitsluitend uit het tabelblok, geen photo_page.
_KAART_PROMPT = f"""Hieronder staat de uitgelezen tekst van ÉÉN receptkaart, in drie blokken:
de voorkant, de ingrediëntentabel als regels 'naam | hoeveelheid', en de achterkant.
Het is precies één recept. Geef ALLEEN geldige JSON terug, geen markdown: een lijst
met één object.

[
  {{
    "title": "Recept naam",
    "yields": 2,
    "ingredients": [
      {{"name": "halfkruimige aardappelen", "amount": "500", "unit": "g"}},
      {{"name": "zonnebloemolie", "amount": "½", "unit": "el"}}
    ],
    "steps": [
      {{"start": "Verwarm de oven voor", "end": "Schep halverwege om."}}
    ]
  }}
]

Regels voor de kaart:
- "ingredients": uitsluitend de regels uit het blok '--- Ingrediënten (tabel) ---', in
  die volgorde, één ingrediënt per regel. Vóór '|' staat de naam, erna de hoeveelheid
  met eenheid. 'naar smaak' of een lege hoeveelheid wordt amount null
- "yields": het getal uit 'voor N personen' als dat op de kaart staat, anders null
- Een bereidingsstap kan op de voorkant beginnen; de stapkoppen ('Frietjes maken')
  horen bij de stap die eronder staat
- Tips en weetjes zijn bereidingstekst en horen bij de stap waar ze onder staan

Regels:""" + '\n'.join(
    regel for regel in _BATCH_PROMPT.split('Regels:', 1)[1].split('\n')
    if '"photo_page"' not in regel
)


def _salvage_objects(text):
    """Haal de complete objecten uit een afgekapte JSON-array.

    Loopt het model tegen zijn outputplafond, dan eindigt het antwoord midden in
    een recept. De recepten die er al helemaal in staan zijn prima bruikbaar en
    veel beter dan de hele batch weggooien.
    """
    decoder = json.JSONDecoder()
    objects = []
    i = text.find('[')
    if i < 0:
        return objects
    i += 1
    while i < len(text):
        while i < len(text) and text[i] in ' \t\r\n,':
            i += 1
        if i >= len(text) or text[i] != '{':
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except ValueError:
            break
        objects.append(obj)
    return objects


def parse_batch_response(text, page_texts=None, standaard_pagina=None):
    """Parse het Gemini-batchantwoord naar een lijst receptdicts. Raises ValueError.

    `page_texts` is de opgeschoonde OCR-tekst per pagina (index 0 = pagina 1).
    Daaruit wordt de bereidingstekst geknipt op de ankers die het model geeft;
    zie services/ankers.py. Geeft het model toch een 'instructions'-tekst
    (ouder antwoordformaat), dan wordt die gebruikt zoals vroeger.

    `standaard_pagina`: als gezet, wordt `photo_page` van het model genegeerd
    (kaartmodus: één samengevoegde tekst).
    """
    if not text:
        raise ValueError('Gemini gaf een leeg antwoord terug. Probeer het opnieuw.')
    try:
        data = json.loads(_sanitize_json(text))
    except json.JSONDecodeError as e:
        data = _salvage_objects(text)
        if not data:
            raise ValueError(f'Onleesbaar antwoord van Gemini: {str(e)[:100]}')
        current_app.logger.warning(
            'Batchantwoord afgekapt; %d volledige recepten gered', len(data))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError('Onverwacht antwoordformaat van Gemini')

    recipes = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = (item.get('title') or '').strip()
        if not name:
            continue
        photo_page = item.get('photo_page')
        photo_page = int(photo_page) if isinstance(photo_page, (int, float)) else None
        if standaard_pagina is not None:
            # Kaartmodus: het model kent maar één (samengevoegde) tekst en
            # mag geen paginanummer kiezen dat er niet is.
            photo_page = standaard_pagina
        ingredients = _build_gemini_ingredients(item.get('ingredients') or [])
        instructions, meldingen = _bereiding(item, photo_page, page_texts,
                                             [i['name'] for i in ingredients])
        recipes.append({
            'name': name[:100],
            'serves': _eerste_getal(item.get('yields')),
            'instructions': instructions,
            'ingredients': ingredients,
            'photo_page': photo_page,
            'meldingen': meldingen,
        })
    return recipes


def _bereiding(item, photo_page, page_texts, ingredienten):
    """Bereidingstekst van één recept: geknipt op ankers, anders zoals het model hem gaf."""
    steps = item.get('steps')
    if not steps:
        tekst = item.get('instructions') or ''
        return tekst, [] if tekst else ['geen bereidingsstappen aangewezen']
    if not page_texts or not photo_page or photo_page > len(page_texts):
        return item.get('instructions') or '', [
            'bereidingsstappen aangewezen maar geen paginatekst om uit te knippen']
    tekst, meldingen = knip_stappen(page_texts[photo_page - 1], steps,
                                    corpus='\n'.join(page_texts), ingredienten=ingredienten,
                                    titel=item.get('title'))
    if not tekst:
        elders = _pagina_met_anker(steps, page_texts, photo_page)
        if elders:
            # Een recept dat over twee pagina's loopt, of een verkeerd
            # paginanummer van het model: de ankers staan er wel, maar op een
            # andere pagina. Dat is een andere fout dan 'niet gevonden', en de
            # gebruiker moet weten welke.
            meldingen.append(f'de bereidingsstappen staan op pagina {elders}, niet op '
                             f'pagina {photo_page}; loopt dit recept over twee pagina\'s?')
    return tekst, meldingen


def _pagina_met_anker(steps, page_texts, behalve):
    """Paginanummer waar het eerste beginanker wél letterlijk staat, of None."""
    from weekmenu.services.ankers import normaliseer
    eerste = next((s.get('start') for s in steps if isinstance(s, dict)
                   and isinstance(s.get('start'), str) and s.get('start').strip()), None)
    if not eerste:
        return None
    anker = re.sub(r'\s+', ' ', eerste).strip()
    for nummer, tekst in enumerate(page_texts, 1):
        if nummer != behalve and anker in normaliseer(tekst).replace('\n', ' '):
            return nummer
    return None


def _eerste_getal(waarde):
    """Het aantal personen als heel getal, of None.

    Het model hoort een getal te geven maar schrijft soms '4-6' of '4 personen'.
    Dat mag de rest van de batch niet kosten: eerder liep de lus die de
    concepten aanmaakt daarop stuk, waarna de al aangemaakte concepten bleven
    staan en de job op 'error' sprong — een halve oogst die er compleet uitzag.
    """
    if isinstance(waarde, bool) or waarde is None:
        return None
    if isinstance(waarde, (int, float)):
        return int(waarde)
    treffer = re.search(r'\d+', str(waarde))
    return int(treffer.group()) if treffer else None


def _job_dir(job_id):
    return os.path.join(current_app.static_folder, 'uploads', 'dump', job_id)


def start_dump_job(files, mode='boek'):
    """Sla uploads op, maak een DumpJob en start de verwerkingsthread. Returns job_id.

    `mode` is 'boek' (één pagina = één recept) of 'kaart' (twee pagina's =
    één recept). Alles anders wordt 'boek': liever een batch te veel als
    kookboek dan een stil verkeerde koppeling.
    """
    saved = []
    job_id = str(uuid.uuid4())
    job_dir = _job_dir(job_id)
    os.makedirs(job_dir, exist_ok=True)

    for i, f in enumerate(files):
        if not f or not f.filename:
            continue
        ctype = f.content_type or ''
        if ctype == 'application/pdf':
            ext = '.pdf'
        elif ctype in _ALLOWED_IMAGE_TYPES:
            ext = {'image/jpeg': '.jpg', 'image/png': '.png',
                   'image/webp': '.webp', 'image/avif': '.avif'}[ctype]
        else:
            continue
        path = os.path.join(job_dir, f'{i:03d}{ext}')
        f.save(path)
        saved.append(path)

    if not saved:
        raise ValueError("Geen bruikbare bestanden (foto's of PDF) ontvangen")

    job = DumpJob(id=job_id, status='processing', mode='kaart' if mode == 'kaart' else 'boek')
    db.session.add(job)
    db.session.commit()
    _start_thread(job_id)
    return job_id


def retry_dump_job(job_id):
    """Lees de job opnieuw in met de huidige pijplijn.

    Wat de gebruiker al heeft afgehandeld blijft staan: een geaccepteerd
    concept is een recept geworden, en dat recept mag niet stilzwijgend zijn
    herkomst verliezen. Alleen wat nog open stond of was afgewezen verdwijnt.
    De pagina's achter de geaccepteerde concepten worden bij het opnieuw
    inlezen overgeslagen (zie _accepted_pages), anders krijgt de gebruiker een
    tweede concept voor een recept dat hij al heeft.
    """
    job = DumpJob.query.get_or_404(job_id)
    RecipeDraft.query.filter(RecipeDraft.job_id == job_id,
                             RecipeDraft.status != 'accepted').delete()
    job.status = 'processing'
    job.error_message = None
    db.session.commit()
    _start_thread(job_id)


def _accepted_pages(job_id):
    """Paginanummers waarvoor al een recept is aangemaakt."""
    return {d.source_page for d in
            RecipeDraft.query.filter_by(job_id=job_id, status='accepted').all()
            if d.source_page is not None}


def _start_thread(job_id):
    app = current_app._get_current_object()
    threading.Thread(target=process_dump_job, args=(app, job_id), daemon=True).start()


def process_dump_job(app, job_id):
    """Threadworker: één Gemini-call over alle bestanden in de jobmap, drafts opslaan."""
    with app.app_context():
        job = DumpJob.query.get(job_id)
        try:
            _process(job)
            job.status = 'done'
        except Exception as e:
            # Alles terugdraaien wat _process al had klaargezet. Zonder deze
            # rollback bleven de concepten staan die vóór de fout waren
            # aangemaakt: de gebruiker zag dan zeven kaarten naast een
            # foutmelding en kon niet weten dat er negen ontbraken.
            db.session.rollback()
            job = DumpJob.query.get(job_id)
            msg = str(e)
            if '429' in msg or 'quota' in msg.lower() or 'RESOURCE_EXHAUSTED' in msg:
                msg = 'Gemini is even niet beschikbaar (rate limit). Probeer het over een minuut opnieuw.'
            job.status = 'error'
            job.error_message = msg[:500]
        db.session.commit()


def _process(job):
    from google import genai as _genai
    from google.genai import types as _gtypes

    api_key = _get_gemini_api_key()
    if not api_key:
        raise ValueError('Gemini API key niet geconfigureerd')

    job_dir = _job_dir(job.id)
    file_paths = sorted(
        os.path.join(job_dir, n) for n in os.listdir(job_dir)
        if not n.startswith('page_')  # eerder gerenderde PDF-pagina's overslaan bij retry
    )

    # Elke pagina wordt eerst uitgelezen door Cloud Vision. Het taalmodel krijgt
    # dus tekst en geen beeld: het kan een hoeveelheid niet meer verkeerd lezen
    # en niets verzinnen wat het niet kan ontcijferen.
    images = []
    # page_map: 1-gebaseerd paginanummer → (bronpad, pdf_page_index|None)
    page_map = {}
    page_no = 0
    for path in file_paths:
        if path.endswith('.pdf'):
            for pdf_idx, jpeg in enumerate(_pdf_page_jpegs(path)):
                page_no += 1
                images.append(jpeg)
                page_map[page_no] = (path, pdf_idx)
        else:
            with open(path, 'rb') as fh:
                images.append(fh.read())
            page_no += 1
            page_map[page_no] = (path, None)

    if job.mode == 'kaart':
        texts, twijfels, annotaties = lees_paginas_met_annotaties(images)
    else:
        texts, twijfels = lees_paginas(images)
        annotaties = None
    if not any(t.strip() for t in texts):
        raise ValueError('Geen tekst gevonden op de aangeleverde pagina\'s. '
                         'Is de scan scherp genoeg?')

    job.page_count = len(images)
    meldingen = []
    zonder_tekst = [n for n, t in enumerate(texts, 1) if not t.strip()]
    if zonder_tekst:
        meldingen.append(
            'Pagina {} leverde geen tekst op — opnieuw fotograferen helpt meestal.'
            .format(', '.join(str(n) for n in zonder_tekst)))

    # Temperatuur 0: het structureren van een pagina is geen creatief werk, en
    # zonder deze instelling gokt het model. Gemeten op dezelfde uitgelezen
    # tekst gaf drie aanroepen drie verschillende uitkomsten — in één ervan
    # werd '½ komkommer' (door de OCR gelezen als '12 komkommer') letterlijk
    # 12 komkommers, in de andere twee terecht een halve. Ook de hoeveelheden
    # bij 'kipfilets van 200 g elk' vielen willekeurig weg. Met temperatuur 0
    # bleef de breukafhandeling over drie aanroepen gelijk.
    client = _genai.Client(api_key=api_key)
    config = _gtypes.GenerateContentConfig(temperature=0)
    if job.mode == 'kaart':
        recipes, kaartmeldingen, verwacht = _verwerk_kaarten(texts, annotaties, client, config)
        meldingen += kaartmeldingen
    else:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[_BATCH_PROMPT + '\n\n' + pages_as_labelled_text(texts)],
            config=config)
        if _warn_if_truncated(response):
            meldingen.append('Het antwoord van Gemini was afgekapt; er kunnen recepten '
                             'ontbreken. Probeer het opnieuw of splits de batch.')
        recipes = parse_batch_response(response.text, [_clean_ocr_text(t) for t in texts])
        verwacht = len(images) - len(zonder_tekst)
        # Vangnet: kaarten in boekmodus leveren twee halve recepten per kaart op.
        kaarten = [n for n, t in enumerate(texts, 1) if is_voorkant(t)]
        if len(kaarten) >= 2:
            meldingen.append("Pagina's {} lijken receptkaarten. Kies 'receptkaarten' als soort "
                             "scan en probeer opnieuw.".format(', '.join(map(str, kaarten))))
    _markeer_twijfels(recipes, twijfels)

    al_afgehandeld = _accepted_pages(job.id)
    overgeslagen = 0
    for r in recipes:
        if r['photo_page'] in al_afgehandeld:
            current_app.logger.info(
                'Pagina %s overgeslagen: daar is al een recept van gemaakt', r['photo_page'])
            overgeslagen += 1
            continue
        image_path = _resolve_image(job.id, r['photo_page'], page_map)
        db.session.add(RecipeDraft(
            job_id=job.id, name=r['name'],
            serves=r['serves'],
            prep_time=r.get('prep_time'),
            instructions=r['instructions'],
            ingredients_json=json.dumps(r['ingredients']),
            # Wat over dit ene recept gaat staat op het concept, naast het
            # veld waar het over gaat; job.warning is voor de hele batch.
            meldingen_json=json.dumps(r.get('meldingen') or [], ensure_ascii=False),
            image_path=image_path,
            back_image_path=(_resolve_image(job.id, r['back_page'], page_map)
                             if r.get('back_page') else None),
            source_page=r['photo_page'], status='pending',
        ))

    # Twee pagina's kunnen samen één recept zijn, dus minder recepten dan
    # pagina's is niet per se fout — maar het is wel het patroon waarmee een
    # halve batch er compleet uitziet, dus de gebruiker krijgt het te zien.
    gemaakt = len(recipes) - overgeslagen
    if gemaakt < verwacht:
        meldingen.append(f'{len(images)} pagina\'s aangeleverd, {gemaakt} recept(en) '
                         f'herkend. Controleer of er niets ontbreekt.')
    # Eén melding per regel: de pagina toont ze los van elkaar.
    job.warning = '\n'.join(meldingen) or None


def _verwerk_kaarten(texts, annotaties, client, config):
    """Kaartmodus: per paar één modelaanroep. Geeft (recipes, meldingen, aantal paren).

    Elk recept krijgt 'photo_page' (voorkant), 'back_page' (achterkant),
    'prep_time' uit de merksignatuur, benodigdheden vooraan in de bereiding,
    en de tabelcontrole (check/kaart_voorraad op de ingrediënten).
    """
    paren_lijst, meldingen = paren(texts, annotaties)
    recipes = []
    for paar in paren_lijst:
        voor, achter, rijen = paar['voor'], paar['achter'], paar['rijen']
        voortekst = _clean_ocr_text(texts[voor - 1])
        achtertekst = _clean_ocr_text(texts[achter - 1])
        achter_zonder_tabel = zonder_tabelregels(achtertekst, rijen)
        gecombineerd = voortekst.strip() + '\n' + achter_zonder_tabel.strip()
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[_KAART_PROMPT + '\n\n'
                      + kaart_invoer(voortekst, achter_zonder_tabel, rijen, voor, achter)],
            config=config)
        waar = f"Pagina's {voor}+{achter}"
        if _warn_if_truncated(response):
            meldingen.append(f'{waar}: het antwoord van Gemini was afgekapt. Probeer het opnieuw.')
        # Alleen een onleesbaar antwoord (ValueError) wordt hier opgevangen: dat
        # is één slechte kaart, de rest van de batch mag door. Een fout uit
        # generate_content zelf (bv. een 429) moet wél doorschieten naar het
        # vangnet in _process, want dat is een quotaprobleem — één duidelijke
        # foutmelding met retry, niet twaalf keer 'geen recept teruggekregen'.
        try:
            gevonden = parse_batch_response(response.text, [gecombineerd], standaard_pagina=1)
        except ValueError as e:
            meldingen.append(f'{waar}: {e}')
            continue
        if not gevonden:
            meldingen.append(f'{waar}: het model gaf geen recept terug.')
            continue
        r = gevonden[0]
        if len(gevonden) > 1:
            r['meldingen'].append(f'het model maakte {len(gevonden)} recepten van deze ene kaart; '
                                  'alleen het eerste is bewaard')
        r['photo_page'], r['back_page'] = voor, achter
        r['name'] = zonder_logo(r['name'], voortekst) or r['name']
        r['prep_time'] = bereidingstijd(voortekst) or bereidingstijd(achtertekst)
        nodig = benodigdheden(achtertekst)
        # Alleen vooraan een bestaande bereiding: zonder deze voorwaarde maakt
        # de kop van een leeg concept een niet-leeg concept, en dan toont de
        # nakijkkaart geen 'bereiding ontbreekt' meer en laat accepteren het
        # er stil doorheen (_bereiding_ontbreekt in routes/dump.py).
        if nodig and (r['instructions'] or '').strip():
            r['instructions'] = f'Benodigdheden: {nodig}\n' + r['instructions']
        r['meldingen'] += controleer_tegen_tabel(r, rijen)
        recipes.append(r)
    return recipes, meldingen, len(paren_lijst)


def _markeer_twijfels(recipes, twijfels):
    """Zet Vision's twijfel over een begingetal op het bijbehorende ingrediënt.

    Het model heeft de regel al omgezet naar naam, getal en eenheid, dus de
    twijfel moet van de OCR-regel naar die ingrediëntregel worden overgezet.
    Dat gaat op de naam: het ingrediënt van dezelfde pagina dat de meeste
    woorden met de regel deelt.

    Sinds de bredere tokenfilter in `onzekere_hoeveelheden` (ook '1,8' en 'I')
    is dit ook de enige rem op voedingswaardentabellen: zo'n regel deelt geen
    woord met een ingrediënt en wordt stil genegeerd, niet gemeld — anders
    spamt elk laag-zeker cijfer uit de tabel de batch vol met meldingen.
    Bewuste keerzijde: een echt gemiste ingrediëntregel (het model sloeg hem
    over) verdwijnt daarmee ook zonder melding als zijn naam nergens anders op
    de pagina terugkomt. Hetzelfde geldt voor een twijfel die eigenlijk in de
    bereidingstekst staat (bv. '½ - 1 cm' bij een bak-instructie): die deelt
    ook geen woord met een ingrediënt en krijgt dus nooit een 'check', ook al
    is de twijfel zelf terecht.

    De treffers krijgen een 'check'-tekst in de ingrediëntregel, en de
    nakijkkaart laat die zien.
    """
    per_pagina = {}
    for r in recipes:
        for p in (r.get('photo_page'), r.get('back_page')):
            if p:
                per_pagina.setdefault(p, []).append(r)
    for pagina, lijst in enumerate(twijfels or [], 1):
        for twijfel in lijst:
            treffer = _ingredient_bij_regel(twijfel['regel'], per_pagina.get(pagina, []))
            if treffer is not None:
                # Voor de nakijker, niet voor de ontwikkelaar: geen
                # percentage, wel wat er gelezen is en wat het kan zijn.
                nieuwe = f"Vision twijfelde aan dit getal: '{twijfel['cijfer']}' kan ½ zijn"
                bestaande = treffer.get('check')
                # Nooit overschrijven: de tabel (controleer_tegen_tabel) heeft
                # 'check' al gezet vóórdat deze functie draait en is leidend,
                # dus die tekst blijft voorop staan.
                treffer['check'] = f'{bestaande}; {nieuwe}' if bestaande else nieuwe


def _ingredient_bij_regel(regel, recipes):
    """Het ingrediënt (dict) dat het best bij een OCR-regel past, of None."""
    woorden = {w for w in re.findall(r'[^\W\d_]{3,}', regel.lower())}
    beste, beste_score = None, 0
    for r in recipes:
        for ing in r['ingredients']:
            naam = set(re.findall(r'[^\W\d_]{3,}', (ing.get('name') or '').lower()))
            score = len(woorden & naam)
            if score > beste_score:
                beste, beste_score = ing, score
    return beste


def _warn_if_truncated(response):
    """Meld of het antwoord onvolledig is, zodat een halve batch verklaarbaar is.

    Geeft True als het model niet netjes is uitgestopt; de aanroeper zet dat
    door naar de gebruiker, want alleen in de log zien is hier niet genoeg.
    """
    try:
        candidate = (response.candidates or [None])[0]
        reason = getattr(candidate, 'finish_reason', None)
        usage = response.usage_metadata
        if reason is not None and getattr(reason, 'name', str(reason)) != 'STOP':
            current_app.logger.warning(
                'Gemini stopte met %s (output %s, thinking %s). Upload eventueel in kleinere delen.',
                reason, usage.candidates_token_count,
                getattr(usage, 'thoughts_token_count', None))
            return True
    except Exception:  # diagnostiek mag de import nooit laten vallen
        pass
    return False


def _pdf_page_jpegs(path, scale=4.0, quality=92):
    """Render elke PDF-pagina naar JPEG-bytes voor de OCR-stap.

    Schaal 4 is gemeten, niet gegokt: op 2,5 las Cloud Vision '3 lente-uitjes'
    als 'lente-uitjes' en viel de hoeveelheid weg. Vanaf 4 komt het cijfer mee;
    daarboven levert het niets meer op. Het kost ook niets, want Vision rekent
    per pagina en niet per byte.
    """
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        for idx in range(len(pdf)):
            buf = io.BytesIO()
            pdf[idx].render(scale=scale).to_pil().convert('RGB').save(
                buf, 'JPEG', quality=quality)
            yield buf.getvalue()
    finally:
        pdf.close()


def _resolve_image(job_id, photo_page, page_map):
    """Kopieer de aangewezen foto of render de PDF-pagina naar static/uploads. Nooit een exception."""
    import hashlib
    import shutil
    try:
        if not photo_page or photo_page not in page_map:
            return None
        src, pdf_idx = page_map[photo_page]
        uploads = os.path.join(current_app.static_folder, 'uploads')
        os.makedirs(uploads, exist_ok=True)

        if pdf_idx is None:
            # De foto gaat door normaliseer_orientatie heen zodat een
            # EXIF-draai in de pixels zelf terechtkomt. Anders toont de browser
            # (die de tag wél leest) iets anders dan PIL bij het bijsnijden
            # ziet, en dan landt de uitsnede naast het aangewezen stuk.
            #
            # De md5 gaat bewust over de GENORMALISEERDE bytes en niet meer
            # over het bronbestand: de bestandsnaam hoort bij de inhoud die we
            # opslaan, anders wijzen twee verschillende beelden naar één naam.
            # Gevolg is dat dezelfde bronfoto voortaan een andere naam krijgt
            # dan vóór deze wijziging; bestaande records blijven gewoon naar
            # hun eigen, nog aanwezige bestand wijzen.
            from weekmenu.services.images import normaliseer_orientatie
            with open(src, 'rb') as fh:
                data = fh.read()
            data, ext = normaliseer_orientatie(data, os.path.splitext(src)[1] or '.jpg')
            fname = hashlib.md5(data).hexdigest() + ext
            with open(os.path.join(uploads, fname), 'wb') as fh:
                fh.write(data)
            return os.path.join('static/uploads', fname)

        import pypdfium2 as pdfium
        rendered = os.path.join(_job_dir(job_id), f'page_{pdf_idx}.jpg')
        pdf = pdfium.PdfDocument(src)
        try:
            pil = pdf[pdf_idx].render(scale=2.0).to_pil()
            pil.convert('RGB').save(rendered, 'JPEG', quality=85)
        finally:
            pdf.close()
        with open(rendered, 'rb') as fh:
            fname = hashlib.md5(fh.read()).hexdigest() + '.jpg'
        shutil.copyfile(rendered, os.path.join(uploads, fname))
        return os.path.join('static/uploads', fname)
    except Exception:
        current_app.logger.warning('Dump %s: afbeelding voor pagina %s mislukt', job_id, photo_page, exc_info=True)
        return None
