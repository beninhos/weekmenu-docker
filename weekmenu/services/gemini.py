"""Gemini API integration: key lookup, HTML/JSON helpers, recipe extraction."""
import hashlib
import json
import os
import re

from flask import current_app

from weekmenu.models import Settings
from weekmenu.constants import DUTCH_UNITS
from weekmenu.services.units import (
    _guess_ingredient_category, parse_ingredients_from_list, _parse_amount,
)
from weekmenu.services.recipes import _suggest_site_cookbook


_VALID_UNITS = sorted(set(DUTCH_UNITS.values()))
_UNITS_STR = ', '.join(_VALID_UNITS)


def _gemini_fout(e):
    """Zet een uitzondering om in de {status,message}-payload die de app tonen kan.

    De rate-limit-boodschap onderscheidt zich zodat de gebruiker weet dat een
    minuut wachten helpt; alle andere fouten krijgen een verkorte melding.
    """
    if isinstance(e, json.JSONDecodeError):
        return {'status': 'error', 'message': f'Fout in receptgegevens: {str(e)[:100]}'}, 400
    msg = str(e)
    if '429' in msg or 'quota' in msg.lower() or 'RESOURCE_EXHAUSTED' in msg:
        msg = 'Gemini is even niet beschikbaar (rate limit). Probeer het over een minuut opnieuw.'
    else:
        msg = f'Fout bij verwerken: {msg[:100]}'
    return {'status': 'error', 'message': msg}, 400

_GEMINI_RECIPE_PROMPT = f"""Extraheer het recept. Geef ALLEEN geldige JSON terug, geen markdown.

{{
  "title": "Recept naam",
  "yields": 4,
  "prep_time": 30,
  "ingredients": [
    {{"name": "bloem", "amount": 200, "unit": "g"}},
    {{"name": "eieren", "amount": 3, "unit": "stuks"}}
  ],
  "instructions": "Stap 1. Verwarm de oven...\\nStap 2. Meng..."
}}

Regels:
- Gebruik ALLEEN deze eenheden voor "unit": {_UNITS_STR}
- "amount" is een getal (int of float), of null als onbekend
- Converteer breuken naar decimalen: ½ → 0.5, ¼ → 0.25, "anderhalve" → 1.5
- Haal hoeveelheden uit de naam en zet ze in "amount"
- "name" is de ingrediëntnaam zonder hoeveelheid of eenheid
- "instructions" als enkele string met stappen gescheiden door newlines
- "prep_time" in minuten (int of null)
- Als er geen recept gevonden kan worden: {{"error": "Geen recept gevonden"}}
"""


def _get_gemini_api_key():
    """Get Gemini API key from database or environment."""
    s = Settings.query.filter_by(key='gemini_api_key').first()
    if s and s.value:
        return s.value
    return os.environ.get('GEMINI_API_KEY')


def _clean_html(raw_html):
    """Strip noise, preserve semantic structure as markdown for Gemini (max 40k chars)."""
    import html as _html_module
    if not raw_html:
        return ""
    for tag in ('script', 'style', 'nav', 'footer', 'iframe', 'header', 'aside'):
        raw_html = re.sub(rf'<{tag}[^>]*>.*?</{tag}>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
    raw_html = re.sub(r'<h[1-6][^>]*>', '\n## ', raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r'</h[1-6]>', '\n', raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r'<li[^>]*>', '\n- ', raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r'</li>', '', raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r'<(?:p|br)[^>]*>', '\n', raw_html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = _html_module.unescape(text)
    text = re.sub(r'\n[ \t]+', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text[:40000]


def _sanitize_json(text):
    """Strip markdown code fences and trailing commas from LLM response."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1] if '\n' in text else text[3:]
        if text.endswith('```'):
            text = text.rsplit('```', 1)[0]
        text = text.strip()
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text


def _as_number(value):
    """Gemini levert 'amount' soms als string ('140'), als Nederlandse komma
    ('1,5'), als breuk ('3/4', '1 1/2', '½') of als bereik ('2-3').

    _parse_amount kent al die vormen; float() kent alleen de punt. Alles wat
    ook daarna niet te lezen is wordt None, precies zoals de app een
    onbekende hoeveelheid al behandelt.
    """
    if value is None or value == '':
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return _parse_amount(str(value))


def _prep_minuten(waarde):
    """De bereidingstijd van het model als positief heel aantal minuten, of None.

    De prompt vraagt een int of null, maar het model schrijft hem ook wel eens
    als tekst ('45'). Alles wat geen positief geheel getal oplevert wordt None,
    net zoals het formulierveld dat doet (routes/recipes.py::_minuten): een 0
    of een tekstuele schatting is geen bereidingstijd om voor te vullen.
    """
    if isinstance(waarde, bool) or waarde is None:
        return None
    if isinstance(waarde, (int, float)):
        minuten = int(waarde)
    elif str(waarde).strip().isdigit():
        minuten = int(str(waarde).strip())
    else:
        return None
    return minuten if minuten > 0 else None


def _build_gemini_ingredients(raw_list):
    """Convert structured LLM ingredient dicts to app format with category."""
    ingredients = []
    for ing in raw_list:
        name = (ing.get('name') or '').strip()
        if not name:
            continue
        ingredients.append({
            'name': name,
            'amount': _as_number(ing.get('amount')),
            'unit': ing.get('unit') or '',
            'category': _guess_ingredient_category(name),
        })
    return ingredients


def _is_bot_challenge_page(html):
    """Detect anti-bot challenge pages (e.g. Akamai) served instead of real content."""
    if len(html) > 8000:
        return False
    markers = ('sec-if-cpt-container', 'powered and protected by', 'akamai', '_abck', 'cf-challenge', 'px-captcha')
    lowered = html.lower()
    return any(m in lowered for m in markers)


def _download_image_to_uploads(image_url):
    """Download an image URL into static/uploads. Returns the relative path or None."""
    if not image_url:
        return None
    try:
        from curl_cffi import requests as _cffi_requests
        from weekmenu.services.images import extensie_uit_content_type, schrijf_naar_uploads
        img_resp = _cffi_requests.get(image_url, impersonate='chrome', timeout=10)
        img_resp.raise_for_status()
        ext = extensie_uit_content_type(img_resp.headers.get('Content-Type'), default='.jpg')
        fname = hashlib.md5(image_url.encode()).hexdigest() + ext
        return schrijf_naar_uploads(fname, img_resp.content)
    except Exception:
        return None


def _clean_control_chars(s):
    """Strip stray control characters (AH-data bevat o.a. U+001F in stappen)."""
    return ''.join(ch for ch in (s or '') if ch >= ' ' or ch in '\n\t')


def map_ah_recipe(url, recipe):
    """Map an AH GraphQL recipe dict into the standard scrape-result shape.

    Data-mapping zonder netwerk; de AH-connector (weekmenu_ah.recept) roept dit aan.
    """
    from weekmenu.constants import DUTCH_UNITS

    title = _clean_control_chars(recipe.get('title') or '').strip()

    servings = recipe.get('servings') or {}
    serves = servings.get('number')

    # Instructies: intro + genummerde stappen als HTML (Quill-vriendelijk).
    steps = ((recipe.get('preparation') or {}).get('steps')) or []
    parts = []
    description = _clean_control_chars(recipe.get('description') or '').strip()
    if description:
        parts.append(f'<p>{description}</p>')
    if steps:
        parts.append('<ol>' + ''.join(f'<li>{_clean_control_chars(s)}</li>' for s in steps) + '</ol>')
    instructions = ''.join(parts)

    ingredients = []
    for ing in recipe.get('ingredients') or []:
        name = _clean_control_chars((ing.get('name') or {}).get('singular') or '').strip()
        if not name:
            continue
        amount = _as_number(ing.get('quantity'))
        raw_unit = ((ing.get('quantityUnit') or {}).get('singular') or '').strip().lower()
        unit = DUTCH_UNITS.get(raw_unit, raw_unit)
        if not unit and amount is not None:
            unit = 'stuks'
        ingredients.append({
            'amount': amount,
            'unit': unit,
            'name': name,
            'category': _guess_ingredient_category(name),
            'raw': ' '.join(str(x) for x in (amount, unit, name) if x not in (None, '')),
        })

    # Grootste afbeelding kiezen.
    images = recipe.get('images') or []
    image_url = None
    if images:
        image_url = max(images, key=lambda im: im.get('width') or 0).get('url')
    image_path = _download_image_to_uploads(image_url)

    cookbook_info = {'id': None, 'name': None, 'exists': False}
    try:
        cookbook_info = _suggest_site_cookbook('www.ah.nl', '', None)
    except Exception:
        pass

    return {
        'status': 'success',
        'name': title,
        'serves': serves,
        'url': url,
        'instructions': instructions,
        'ingredients': ingredients,
        'image_path': image_path,
        'cookbook_id': cookbook_info.get('id'),
        'cookbook_name': cookbook_info.get('name'),
        'cookbook_exists': cookbook_info.get('exists', False),
    }


# Importeurs per site die vóór de gewone scraper gaan: url -> (data, status) of
# None. De AH-connector zet hier bij import 'ah.nl' bij.
IMPORTEURS = {}


def scrape_recipe_from_url(url):
    """Fetch URL, try structured scraper, fall back to Gemini LLM. Returns (data, status)."""
    from curl_cffi import requests as _requests
    from recipe_scrapers import scrape_html

    url = (url or '').strip()
    if not url:
        return {'status': 'error', 'message': 'Geen URL opgegeven'}, 400

    for importeer in IMPORTEURS.values():
        resultaat = importeer(url)
        if resultaat is not None:
            return resultaat

    try:
        resp = _requests.get(url, impersonate='chrome', timeout=15, allow_redirects=True)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        msg = str(e)
        code = getattr(getattr(e, 'response', None), 'status_code', None)
        if 'timed out' in msg.lower() or 'timeout' in msg.lower():
            return {'status': 'error', 'message': 'De pagina reageerde niet op tijd. Probeer het opnieuw.'}, 400
        if code == 403:
            return {'status': 'error', 'message': 'Deze website blokkeert automatisch ophalen (403). Probeer een andere site.'}, 400
        if code == 404:
            return {'status': 'error', 'message': 'Pagina niet gevonden (404). Controleer de URL.'}, 400
        if code:
            return {'status': 'error', 'message': f'De pagina kon niet worden opgehaald (HTTP {code}).'}, 400
        return {'status': 'error', 'message': 'De URL kon niet worden bereikt. Controleer de URL.'}, 400

    if _is_bot_challenge_page(html):
        return {'status': 'error', 'message': 'Deze website blokkeert automatisch ophalen (bot-detectie). Plak het recept handmatig over.'}, 400

    try:
        scraper = scrape_html(html, org_url=url)
        scraper.title()
    except Exception:
        try:
            scraper = scrape_html(html, org_url=url, wild_mode=True)
        except Exception:
            scraper = None

    if scraper is None:
        return _llm_fallback_from_html(url, html)

    return _extract_from_scraper(url, html, scraper)


def _llm_fallback_from_html(url, html):
    """When the structured scraper fails, ask Gemini to parse the page text."""
    api_key = _get_gemini_api_key()
    if not api_key:
        return {'status': 'error', 'message': 'Geen receptinformatie gevonden op deze pagina. De site ondersteunt geen gestructureerde receptdata.'}, 400

    from google import genai as _genai
    from google.genai import types as _gtypes

    text = _clean_html(html)
    prompt = _GEMINI_RECIPE_PROMPT + f"\n\nTekst van de pagina:\n{text}"

    try:
        client = _genai.Client(api_key=api_key)
        # Zie de toelichting bij temperatuur 0 in services/dump.py: een recept
        # overnemen is overschrijfwerk, geen creatief werk.
        response = client.models.generate_content(
            model='gemini-2.5-flash', contents=prompt,
            config=_gtypes.GenerateContentConfig(temperature=0))
        sanitized = _sanitize_json(response.text)
        result = json.loads(sanitized)

        if 'error' in result:
            return {'status': 'error', 'message': result['error']}, 400

        cookbook_info = {'id': None, 'name': None, 'exists': False}
        try:
            from urllib.parse import urlparse as _urlparse
            domain = _urlparse(url).netloc
            cookbook_info = _suggest_site_cookbook(domain, html, None)
        except Exception:
            pass

        return {
            'status': 'success',
            'name': result.get('title', ''),
            'serves': result.get('yields'),
            'prep_time': _prep_minuten(result.get('prep_time')),
            'url': url,
            'instructions': result.get('instructions', ''),
            'ingredients': _build_gemini_ingredients(result.get('ingredients', [])),
            'image_path': None,
            'cookbook_id': cookbook_info.get('id'),
            'cookbook_name': cookbook_info.get('name'),
            'cookbook_exists': cookbook_info.get('exists', False),
        }, 200
    except Exception as e:
        return _gemini_fout(e)


def _extract_from_scraper(url, html, scraper):
    """Extract recipe data from a working recipe-scrapers scraper."""
    try:
        title = scraper.title() or ''
    except Exception:
        title = ''

    try:
        yields_str = scraper.yields() or ''
        serves_match = re.search(r'\d+', yields_str)
        serves = int(serves_match.group()) if serves_match else None
    except Exception:
        serves = None

    try:
        instructions = scraper.instructions() or ''
    except Exception:
        instructions = ''

    raw_ingredients = []
    section_names = []
    try:
        groups = scraper.ingredient_groups()
        if groups and len(groups) > 1:
            for g in groups:
                if g.ingredients:
                    raw_ingredients.extend(g.ingredients)
                if g.purpose:
                    section_names.append(g.purpose)
        else:
            raise ValueError('single group, use .ingredients()')
    except Exception:
        try:
            raw_ingredients = scraper.ingredients() or []
        except Exception:
            raw_ingredients = []

    if section_names:
        prefix = 'Secties: ' + ' + '.join(section_names) + '\n\n'
        instructions = prefix + instructions

    parsed_ingredients = parse_ingredients_from_list(raw_ingredients)

    if not title and not parsed_ingredients:
        return _llm_fallback_from_html(url, html)

    image_path = None
    try:
        image_path = _download_image_to_uploads(scraper.image())
    except Exception:
        pass

    cookbook_info = {'id': None, 'name': None, 'exists': False}
    try:
        from urllib.parse import urlparse as _urlparse
        domain = _urlparse(url).netloc
        cookbook_info = _suggest_site_cookbook(domain, html, scraper)
    except Exception:
        pass

    return {
        'status': 'success',
        'name': title,
        'serves': serves,
        'url': url,
        'instructions': instructions,
        'ingredients': parsed_ingredients,
        'image_path': image_path,
        'cookbook_id': cookbook_info.get('id'),
        'cookbook_name': cookbook_info.get('name'),
        'cookbook_exists': cookbook_info.get('exists', False),
    }, 200


def recipe_from_photos(photos):
    """Extract a recipe from up to 3 photos using Gemini vision. Returns (data, status)."""
    from google import genai as _genai
    from google.genai import types as _gtypes

    api_key = _get_gemini_api_key()
    if not api_key:
        return {'status': 'error', 'message': 'Gemini API key niet geconfigureerd'}, 400

    if not photos or len(photos) == 0 or photos[0].filename == '':
        return {'status': 'error', 'message': "Geen foto's geselecteerd"}, 400

    if len(photos) > 3:
        return {'status': 'error', 'message': "Maximaal 3 foto's toegestaan"}, 400

    image_parts = []
    first_image_path = None

    for i, photo in enumerate(photos):
        if photo.filename == '':
            continue

        image_bytes = photo.read()

        if i == 0:
            from weekmenu.services.images import extensie_uit_content_type, schrijf_naar_uploads
            ext = extensie_uit_content_type(photo.content_type, default='.jpg')
            fname = hashlib.md5(image_bytes).hexdigest() + ext
            first_image_path = schrijf_naar_uploads(fname, image_bytes)

        image_parts.append(
            _gtypes.Part.from_bytes(data=image_bytes, mime_type=photo.content_type or 'image/jpeg')
        )

    prompt = _GEMINI_RECIPE_PROMPT + "\n\nBij meerdere foto's: combineer ingrediënten en bereiding van alle pagina's."

    try:
        client = _genai.Client(api_key=api_key)
        content = [prompt] + image_parts
        response = client.models.generate_content(
            model='gemini-2.5-flash', contents=content,
            config=_gtypes.GenerateContentConfig(temperature=0))
        sanitized = _sanitize_json(response.text)
        result = json.loads(sanitized)

        if 'error' in result:
            return {'status': 'error', 'message': result['error']}, 400

        return {
            'status': 'success',
            'name': result.get('title', ''),
            'serves': result.get('yields'),
            'prep_time': _prep_minuten(result.get('prep_time')),
            'url': None,
            'instructions': result.get('instructions', ''),
            'ingredients': _build_gemini_ingredients(result.get('ingredients', [])),
            'image_path': first_image_path,
            'cookbook_id': None,
            'cookbook_name': None,
        }, 200

    except Exception as e:
        return _gemini_fout(e)
