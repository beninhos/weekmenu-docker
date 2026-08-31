"""Google Cloud Vision: receptpagina's omzetten naar letterlijke tekst.

Waarom een aparte leesstap, terwijl een vision-model de pagina ook kan lezen:
dat model haalde ½ en 1½ stelselmatig door elkaar (een half bosje munt werd
anderhalf) en ging bij veertien pagina's in één aanroep ingrediënten verzinnen
die het niet kon ontcijferen. Cloud Vision transcribeert alleen — het
reproduceert niets uit eigen kennis, dus beide faalwijzen bestaan hier niet.
Het taalmodel krijgt daarna tekst in plaats van beeld en kan een hoeveelheid
dus ook niet meer verkeerd lezen.

Eerste 1.000 pagina's per maand zijn gratis; daarna $1,50 per 1.000.
"""
import base64
import json
import os
import re
import urllib.error
import urllib.request

from flask import current_app

from weekmenu.models import Settings

class VisionKeyError(ValueError):
    """Vision weigert de sleutel zelf; het nog eens proberen helpt niet.

    Apart van de overige fouten omdat de instellingenpagina hierop een sleutel
    mag weigeren, terwijl een haperende verbinding niets zegt over de sleutel.
    """


_ENDPOINT = 'https://vision.googleapis.com/v1/images:annotate'
# De API staat 16 afbeeldingen per aanroep toe, maar begrenst de request ook op
# 20 MB. Pagina's worden op schaal 4 gerenderd (~1 MB elk, ~1,4 MB na base64),
# dus acht per keer houdt ruime marge. Het kost niets extra: Vision rekent per
# pagina, ongeacht hoe je ze over aanroepen verdeelt.
_MAX_PER_REQUEST = 8
_TIMEOUT = 120
# De proefaanroep bij het opslaan van een sleutel stuurt één blanco vierkantje
# en laat de gebruiker wachten. Die mag de batch-timeout niet erven: acht
# kookboekpagina's mogen twee minuten duren, een klik op Opslaan niet.
_TIMEOUT_PROEF = 15


def _get_vision_api_key():
    """Vision-sleutel uit de database, anders uit de omgeving."""
    setting = Settings.query.filter_by(key='vision_api_key').first()
    if setting and setting.value:
        return setting.value
    return os.environ.get('VISION_API_KEY')


def vision_configured():
    return bool(_get_vision_api_key())


def _annotate(api_key, images, language, timeout=_TIMEOUT):
    """Één aanroep naar de Vision-API voor maximaal 16 pagina's."""
    body = {'requests': [{
        'image': {'content': base64.b64encode(img).decode()},
        'features': [{'type': 'DOCUMENT_TEXT_DETECTION'}],
        'imageContext': {'languageHints': [language]},
    } for img in images]}

    request = urllib.request.Request(
        f'{_ENDPOINT}?key={api_key}',
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response).get('responses', [])
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = json.load(e).get('error', {}).get('message', '')
        except Exception:
            pass
        if e.code in (401, 403):
            raise VisionKeyError('Cloud Vision weigert de sleutel. Controleer of de '
                                 'Vision-API aanstaat en of de sleutel bij het juiste '
                                 f'project hoort. ({detail[:120]})')
        # Een verkeerd overgenomen sleutel komt niet terug als 401 maar als 400
        # met 'API key not valid'; zonder deze tak zou een typefout een vage
        # HTTP 400 opleveren in plaats van 'de sleutel klopt niet'.
        if e.code == 400 and 'api key' in detail.lower():
            raise VisionKeyError('Cloud Vision herkent deze sleutel niet. Controleer '
                                 f'of hij volledig is overgenomen. ({detail[:120]})')
        if e.code == 429:
            raise ValueError('Cloud Vision is even niet beschikbaar (limiet bereikt). '
                             'Probeer het over een minuut opnieuw.')
        raise ValueError(f'Cloud Vision gaf een fout (HTTP {e.code}). {detail[:120]}')
    except urllib.error.URLError as e:
        raise ValueError(f'Cloud Vision niet bereikbaar: {str(e.reason)[:80]}')


def verify_vision_key(api_key):
    """Leg een sleutel even aan Cloud Vision voor.

    Geeft (True, '') als Vision hem accepteert, (False, reden) als Vision hem
    weigert, en (None, reden) als het niet vast te stellen was. Dat laatste is
    een eigen geval: bij een haperende verbinding mag een sleutel die misschien
    prima is niet geweigerd worden.

    Kost één van de duizend gratis pagina's per maand — een blanco vierkantje
    is de goedkoopste manier om te weten of de sleutel het echt doet, want
    alleen een volledige aanroep laat zien of de Vision-API ook aanstaat.
    """
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buffer, format='JPEG')
    try:
        _annotate(api_key, [buffer.getvalue()], 'nl', timeout=_TIMEOUT_PROEF)
        return True, ''
    except VisionKeyError as e:
        return False, str(e)
    except Exception as e:
        # Bewust alles: urllib wikkelt lang niet elke storing in een URLError.
        # Een leestimeout komt als kale TimeoutError naar boven en een proxy die
        # de verbinding dichtgooit als ConnectionResetError. Zou zo'n fout hier
        # ontsnappen, dan geeft de instellingenpagina een 500 en raakt de
        # gebruiker een sleutel kwijt die waarschijnlijk gewoon goed was — het
        # tegenovergestelde van wat deze functie moet doen. Wel loggen, want zo
        # breed vangen verbergt ook een programmeerfout.
        try:
            current_app.logger.warning('Sleutelcontrole afgebroken: %s: %s',
                                       e.__class__.__name__, str(e)[:200])
        except Exception:
            pass
        return None, str(e) or e.__class__.__name__


def ocr_pages(images, language='nl'):
    """Lees JPEG-pagina's uit als tekst; geeft even veel teksten terug als pagina's.

    Een pagina die niets oplevert wordt een lege string in plaats van dat hij
    wegvalt: de paginanummering moet blijven kloppen met de aanroeper, want die
    koppelt er de receptfoto aan.
    """
    api_key = _get_vision_api_key()
    if not api_key:
        raise ValueError('Cloud Vision API key niet geconfigureerd')

    texts = []
    for start in range(0, len(images), _MAX_PER_REQUEST):
        responses = _annotate(api_key, images[start:start + _MAX_PER_REQUEST], language)
        for offset in range(len(images[start:start + _MAX_PER_REQUEST])):
            item = responses[offset] if offset < len(responses) else {}
            if item.get('error'):
                current_app.logger.warning(
                    'Vision-fout op pagina %d: %s',
                    start + offset + 1, item['error'].get('message', '')[:120])
                texts.append('')
                continue
            texts.append((item.get('fullTextAnnotation') or {}).get('text', ''))

    leeg = sum(1 for t in texts if not t.strip())
    if leeg:
        current_app.logger.warning('Vision: %d van %d pagina\'s leverden geen tekst op',
                                   leeg, len(texts))
    return texts


_FRACTIONS = '½⅓⅔¼¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞'


def _clean_ocr_text(text):
    """Ruim herkenbare OCR-artefacten op vóór het model de tekst ziet.

    Een verdubbeld breukteken ('½½ el ketjap') komt in geen enkel recept voor.
    Blijft het staan, dan gaat het model de passage 'repareren' en verandert het
    ook getallen die wél goed gelezen waren — dat maakte van '½ el olijfolie'
    een '2 el olijfolie'. Rommelige invoer is dus duurder dan alleen die ene fout.

    Dezelfde glyph levert soms het breukteken én een los cijfer op ('½2 citroen'
    waar '½ citroen' staat): Vision leest de twee helften van het teken dan een
    keer als geheel en een keer als cijfer. Ook dat komt in geen recept voor —
    een hoeveelheid schrijf je niet als breuk met een cijfer erachter geplakt.
    Beide opruimingen laten een losse breuk en een gemengd getal als '1½'
    ongemoeid, want daar staat het cijfer vóór de breuk.
    """
    schoon = re.sub(rf'([{_FRACTIONS}])\1+', r'\1', text or '')
    return re.sub(rf'(?<![0-9])([{_FRACTIONS}])[0-9](?![0-9])', r'\1', schoon)


def pages_as_labelled_text(texts):
    """Voeg de paginateksten samen met expliciete labels.

    Die labels zijn niet cosmetisch: zonder anker weet het taalmodel niet waar
    een pagina begint en gaat het recepten samenvoegen die los horen te staan.
    """
    blokken = []
    for index, text in enumerate(texts, 1):
        blokken.append(f'--- Pagina {index} ---\n{_clean_ocr_text(text).strip()}')
    return '\n\n'.join(blokken)
