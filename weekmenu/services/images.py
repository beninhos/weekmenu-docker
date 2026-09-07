import hashlib
import io
import math
import os

from flask import current_app

# Cropper.js draait met de klok mee (net als een CSS-transform); PIL.rotate()
# draait er juist tegenin. Deze tabel doet de kwartslagen zonder resampling,
# dus zonder kwaliteitsverlies en zonder zwarte randen.
_KWARTSLAGEN = {90: 'ROTATE_270', 180: 'ROTATE_180', 270: 'ROTATE_90'}


def _parse_rotatie(waarde):
    """Maak van een hoek een kwartslag 0/90/180/270, of None als dat niet kan.

    Cropper telt draaiingen op zonder ze terug te brengen tot onder de 360, dus
    -90 en 450 zijn allebei gewoon geldig. Een hoek die géén kwartslag is
    kunnen we niet uitvoeren, en stilzwijgend op 0 zetten zou het verkeerde
    stuk uitsnijden zonder dat iemand het merkt. Dan liever een nette 400.
    """
    if waarde is None or waarde == '':
        return 0
    try:
        graden = float(waarde)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(graden) or graden % 90 != 0:
        return None
    return int(graden) % 360


def parse_crop_body(body):
    """Valideer crop-fracties uit een JSON-body. Returns (x, y, w, h, rotatie) of None.

    De rotatie is het VERSCHIL met de stand waarin de browser het beeld al
    toonde (de EXIF-oriëntatie), niet de absolute hoek: die EXIF-stand zet de
    server zelf al met exif_transpose, en zou er anders dubbel op komen.
    """
    try:
        x = float(body['x'])
        y = float(body['y'])
        w = float(body['width'])
        h = float(body['height'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1
            and x + w <= 1.0001 and y + h <= 1.0001):
        return None
    rotatie = _parse_rotatie(body.get('rotate', 0))
    if rotatie is None:
        return None
    return x, y, w, h, rotatie


def normaliseer_orientatie(data, ext='.jpg'):
    """Bak een EXIF-oriëntatie in de pixels. Returns (bytes, extensie).

    Zolang de draai alleen als tag in het bestand staat, kijken de browser en
    PIL naar twee verschillende beelden: de browser leest de tag, PIL negeert
    hem. Elk bijsnijden gaat dan mis. De spiegelstanden (2/4/5/7) zijn boven-
    dien met geen enkele serverdraai achteraf recht te zetten, dus dit moet
    bij binnenkomst gebeuren.

    Zonder oriëntatietag geven we de bytes onveranderd terug: opnieuw coderen
    kost kwaliteit en levert dan niets op. Een bestand dat PIL niet aankan
    laten we ook met rust; het bijsnijden geeft er later een nette melding over.
    """
    from PIL import Image, ImageOps
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.getexif().get(274, 1) in (None, 1):
                return data, ext
            recht = ImageOps.exif_transpose(im) or im
            buf = io.BytesIO()
            recht.convert('RGB').save(buf, 'JPEG', quality=95,
                                      icc_profile=im.info.get('icc_profile'))
            return buf.getvalue(), '.jpg'
    except Exception:
        return data, ext


def crop_image(src_rel, x, y, w, h, rotatie=0):
    """Crop 'static/...'-bron naar nieuw jpg in static/uploads. Returns nieuw relatief pad.

    De fracties horen bij het beeld ZOALS DE BROWSER HET TOONDE: met de
    EXIF-oriëntatie toegepast, en daarna de kwartslagen die de gebruiker zelf
    draaide. We brengen het bestand hier in diezelfde stand vóór het snijden,
    anders landt de uitsnede op een heel ander stuk van de pagina.
    """
    src_abs = os.path.join(current_app.static_folder, src_rel.replace('static/', '', 1))
    if not os.path.exists(src_abs):
        raise FileNotFoundError(src_rel)

    from PIL import Image, ImageOps
    try:
        im = Image.open(src_abs)
        im.load()
        icc_profile = im.info.get('icc_profile')
        # exif_transpose staat bewust bínnen deze try: bij een half kapotte jpg
        # struikelt getexif() en dan hoort de gebruiker dezelfde nette melding
        # te krijgen als bij een onleesbaar bestand, geen 500.
        im = ImageOps.exif_transpose(im) or im
    except Exception:
        raise ValueError('Dit afbeeldingsformaat kan niet bijgesneden worden')

    if rotatie:
        im = im.transpose(getattr(Image.Transpose, _KWARTSLAGEN[rotatie]))

    width, height = im.size
    left = int(x * width)
    top = int(y * height)
    right = max(left + 1, int((x + w) * width))
    bottom = max(top + 1, int((y + h) * height))
    cropped = im.crop((left, top, right, bottom)).convert('RGB')

    buf = io.BytesIO()
    cropped.save(buf, 'JPEG', quality=85, icc_profile=icc_profile)
    data = buf.getvalue()
    fname = hashlib.md5(data).hexdigest() + '.jpg'
    uploads = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    with open(os.path.join(uploads, fname), 'wb') as f:
        f.write(data)
    return os.path.join('static/uploads', fname)
