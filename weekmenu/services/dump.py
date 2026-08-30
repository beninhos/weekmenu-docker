import io
import json
import os
import threading
import uuid

from flask import current_app

from weekmenu.extensions import db
from weekmenu.models import DumpJob, RecipeDraft
from weekmenu.services.gemini import (
    _get_gemini_api_key, _sanitize_json, _build_gemini_ingredients, _UNITS_STR,
)
from weekmenu.services.ocr import ocr_pages, pages_as_labelled_text

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
    "instructions": "Stap 1. ...\\nStap 2. ..."
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
- Staat er wel een maat maar geen getal ("een handvol augurken", "een scheutje melk"),
  gebruik dan amount "1"
- "instructions" LETTERLIJK overnemen uit de tekst, alleen opgeknipt in stappen
  met newlines ertussen. Niets weglaten, niets toevoegen, niets herschrijven
- "photo_page": het paginanummer waarop dit recept staat
- "yields": het aantal personen als dat op de pagina staat, anders null
- Verzin NIETS dat niet in de tekst staat. Ontbreekt een hoeveelheid, gebruik null
- "title" in normale schrijfwijze, NIET in volledige kapitalen. Behoud eigennamen,
  merknamen en afkortingen zoals ze horen (Cajun, Koreaanse, BBQ, Tikka)
- Staat er een hoofdtitel met daaronder een ondertitel? Verbind ze met " - "
- Sla onvolledige fragmenten (alleen een inhoudsopgave, half recept zonder ingrediënten) over
- Als er helemaal geen recept te vinden is: []
"""


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


def parse_batch_response(text):
    """Parse het Gemini-batchantwoord naar een lijst receptdicts. Raises ValueError."""
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
        recipes.append({
            'name': name[:100],
            'serves': item.get('yields'),
            'instructions': item.get('instructions') or '',
            'ingredients': _build_gemini_ingredients(item.get('ingredients', [])),
            'photo_page': int(photo_page) if isinstance(photo_page, (int, float)) else None,
        })
    return recipes


def _job_dir(job_id):
    return os.path.join(current_app.static_folder, 'uploads', 'dump', job_id)


def start_dump_job(files):
    """Sla uploads op, maak een DumpJob en start de verwerkingsthread. Returns job_id."""
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

    job = DumpJob(id=job_id, status='processing')
    db.session.add(job)
    db.session.commit()
    _start_thread(job_id)
    return job_id


def retry_dump_job(job_id):
    """Verwijder oude drafts, zet de job terug op processing en verwerk opnieuw."""
    job = DumpJob.query.get_or_404(job_id)
    RecipeDraft.query.filter_by(job_id=job_id).delete()
    job.status = 'processing'
    job.error_message = None
    db.session.commit()
    _start_thread(job_id)


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

    texts = ocr_pages(images)
    if not any(t.strip() for t in texts):
        raise ValueError('Geen tekst gevonden op de aangeleverde pagina\'s. '
                         'Is de scan scherp genoeg?')

    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=[_BATCH_PROMPT + '\n\n' + pages_as_labelled_text(texts)])
    _warn_if_truncated(response)
    recipes = parse_batch_response(response.text)

    for idx, r in enumerate(recipes):
        image_path = _resolve_image(job.id, r['photo_page'], page_map)
        db.session.add(RecipeDraft(
            job_id=job.id, name=r['name'],
            serves=int(r['serves']) if r['serves'] else None,
            instructions=r['instructions'],
            ingredients_json=json.dumps(r['ingredients']),
            image_path=image_path, source_page=r['photo_page'], status='pending',
        ))


def _warn_if_truncated(response):
    """Log waarom een antwoord onvolledig is, zodat een halve batch verklaarbaar is."""
    try:
        candidate = (response.candidates or [None])[0]
        reason = getattr(candidate, 'finish_reason', None)
        usage = response.usage_metadata
        if reason is not None and getattr(reason, 'name', str(reason)) != 'STOP':
            current_app.logger.warning(
                'Gemini stopte met %s (output %s, thinking %s). Upload eventueel in kleinere delen.',
                reason, usage.candidates_token_count,
                getattr(usage, 'thoughts_token_count', None))
    except Exception:  # diagnostiek mag de import nooit laten vallen
        pass


def _pdf_page_jpegs(path, scale=2.5, quality=90):
    """Render elke PDF-pagina naar JPEG-bytes voor de OCR-stap."""
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
            with open(src, 'rb') as fh:
                fname = hashlib.md5(fh.read()).hexdigest() + os.path.splitext(src)[1]
            shutil.copyfile(src, os.path.join(uploads, fname))
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
