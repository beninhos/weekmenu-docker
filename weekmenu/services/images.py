import hashlib
import io
import os

from flask import current_app


def parse_crop_body(body):
    """Valideer crop-fracties uit een JSON-body. Returns (x, y, w, h) of None."""
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
    return x, y, w, h


def crop_image(src_rel, x, y, w, h):
    """Crop 'static/...'-bron naar nieuw jpg in static/uploads. Returns nieuw relatief pad."""
    src_abs = os.path.join(current_app.static_folder, src_rel.replace('static/', '', 1))
    if not os.path.exists(src_abs):
        raise FileNotFoundError(src_rel)

    from PIL import Image
    try:
        im = Image.open(src_abs)
        im.load()
    except Exception:
        raise ValueError('Dit afbeeldingsformaat kan niet bijgesneden worden')

    width, height = im.size
    left = int(x * width)
    top = int(y * height)
    right = max(left + 1, int((x + w) * width))
    bottom = max(top + 1, int((y + h) * height))
    cropped = im.crop((left, top, right, bottom)).convert('RGB')

    buf = io.BytesIO()
    cropped.save(buf, 'JPEG', quality=85)
    data = buf.getvalue()
    fname = hashlib.md5(data).hexdigest() + '.jpg'
    uploads = os.path.join(current_app.static_folder, 'uploads')
    os.makedirs(uploads, exist_ok=True)
    with open(os.path.join(uploads, fname), 'wb') as f:
        f.write(data)
    return os.path.join('static/uploads', fname)
