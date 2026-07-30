from flask_babel import gettext as _
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

_ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/avif'}

_BATCH_PROMPT = f"""Dit zijn pagina's uit een kookboek (foto's en/of een PDF). Er kunnen MEERDERE recepten in staan.
Extraheer ALLE volledige recepten. Geef ALLEEN geldige JSON terug, geen markdown: een array van recepten.

[
  {{
    "title": "Recept naam",
    "yields": 4,
    "photo_page": 2,
    "ingredients": [
      {{"name": "bloem", "amount": 200, "unit": "g"}}
    ],
    "instructions": "Stap 1. ...\\nStap 2. ..."
  }}
]

Regels:
- Gebruik ALLEEN deze eenheden voor "unit": {_UNITS_STR}
- "amount" is een getal (int of float), of null als onbekend
- Converteer breuken naar decimalen: ½ → 0.5, ¼ → 0.25, "anderhalve" → 1.5
- "name" is de ingrediëntnaam zonder hoeveelheid of eenheid
- "instructions" als enkele string met stappen gescheiden door newlines
- Een recept dat over meerdere pagina's doorloopt is ÉÉN recept: combineer de pagina's
- "photo_page": het 1-gebaseerde paginanummer (over alle invoer heen, in volgorde) met de mooiste foto van het gerecht, of null als er geen gerechtfoto is
- Sla onvolledige fragmenten (alleen een inhoudsopgave, half recept zonder ingrediënten) over
- Als er helemaal geen recept te vinden is: []
"""


def parse_batch_response(text):
    """Parse het Gemini-batchantwoord naar een lijst receptdicts. Raises ValueError."""
    try:
        data = json.loads(_sanitize_json(text))
    except json.JSONDecodeError as e:
        raise ValueError(f'Unreadable response from Gemini: {str(e)[:100]}')
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError(_('Unexpected response format from Gemini'))

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
        raise ValueError(_("No usable files (photos or PDF) received"))

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
                msg = _('Gemini is briefly unavailable (rate limit). Try again in a minute.')
            job.status = 'error'
            job.error_message = msg[:500]
        db.session.commit()


def _process(job):
    from google import genai as _genai
    from google.genai import types as _gtypes

    api_key = _get_gemini_api_key()
    if not api_key:
        raise ValueError(_('Gemini API key not configured'))

    job_dir = _job_dir(job.id)
    file_paths = sorted(
        os.path.join(job_dir, n) for n in os.listdir(job_dir)
        if not n.startswith('page_')  # eerder gerenderde PDF-pagina's overslaan bij retry
    )

    parts = []
    # page_map: 1-gebaseerd paginanummer → (bronpad, pdf_page_index|None)
    page_map = {}
    page_no = 0
    for path in file_paths:
        with open(path, 'rb') as fh:
            data = fh.read()
        if path.endswith('.pdf'):
            parts.append(_gtypes.Part.from_bytes(data=data, mime_type='application/pdf'))
            for pdf_idx in range(_pdf_page_count(path)):
                page_no += 1
                page_map[page_no] = (path, pdf_idx)
        else:
            mime = {'jpg': 'image/jpeg', 'png': 'image/png',
                    'webp': 'image/webp', 'avif': 'image/avif'}[path.rsplit('.', 1)[1]]
            parts.append(_gtypes.Part.from_bytes(data=data, mime_type=mime))
            page_no += 1
            page_map[page_no] = (path, None)

    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model='gemini-2.5-flash', contents=[_BATCH_PROMPT] + parts)
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


def _pdf_page_count(path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return len(pdf)
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
