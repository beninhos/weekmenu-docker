import re
import os
import hashlib

from flask import current_app

from weekmenu.extensions import db
from weekmenu.models import Ingredient, IngredientAlias, Cookbook
from weekmenu.constants import _KNOWN_SITES, _BROWSER_HEADERS
from weekmenu.services.units import _normalize_ingredient, _guess_ingredient_category


def _resolve_or_create_ingredient(raw_name, category=None):
    """Resolve an ingredient name via the alias system, or create a new one."""
    normalized = _normalize_ingredient(raw_name.lower().strip())

    alias = IngredientAlias.query.filter(
        IngredientAlias.alias.in_([normalized])
    ).first()
    if alias:
        return alias.ingredient

    existing = Ingredient.query.filter_by(name=normalized).first()
    if existing:
        return existing

    existing = Ingredient.query.filter(
        db.func.lower(Ingredient.display_name) == raw_name.strip().lower()
    ).first()
    if existing:
        return existing

    if not category or category == 'Overig':
        category = _guess_ingredient_category(raw_name)

    display_name = raw_name.strip()
    canonical = normalized

    ing = Ingredient(name=canonical, display_name=display_name, category=category)
    db.session.add(ing)
    db.session.flush()

    try:
        db.session.add(IngredientAlias(alias=canonical, ingredient_id=ing.id))
        db.session.flush()
    except Exception:
        db.session.rollback()
        db.session.add(ing)
        db.session.flush()

    return ing


def _suggest_site_cookbook(domain, html_text, scraper):
    """Check if a cookbook exists for this domain, or suggest a name.
    Returns dict with 'id', 'name', 'exists'."""
    clean_domain = re.sub(r'^www\.', '', domain)

    name = _KNOWN_SITES.get(clean_domain)
    if not name:
        try:
            name = scraper.site_name() or clean_domain.split('.')[0].capitalize()
        except Exception:
            name = clean_domain.split('.')[0].capitalize()

    cookbook = Cookbook.query.filter_by(name=name).first()
    if cookbook:
        return {'id': cookbook.id, 'name': cookbook.name, 'exists': True}

    return {'id': None, 'name': name, 'exists': False, 'domain': clean_domain}


def _download_site_logo(domain, html_text, requests_module):
    """Download a high-quality logo for a website. Returns image_path or None."""
    clean_domain = re.sub(r'^www\.', '', domain)
    from urllib.parse import urljoin

    urls_to_try = []

    # 1. Large touch/PWA icons from HTML
    for pattern in [
        r'<link[^>]*rel=["\']apple-touch-icon["\'][^>]*href=["\']([^"\']+)',
        r'<link[^>]*href=["\']([^"\']+)["\'][^>]*rel=["\']apple-touch-icon["\']',
    ]:
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            urls_to_try.append(urljoin(f'https://{domain}', match.group(1)))
            break

    # 2. Standard PWA icon paths
    for path in ['/android-chrome-192x192.png', '/favicon-192x192.png', '/apple-touch-icon.png']:
        urls_to_try.append(f'https://{clean_domain}{path}')

    # 3. Clearbit (high quality)
    urls_to_try.append(f'https://logo.clearbit.com/{clean_domain}?size=256')

    for logo_url in urls_to_try:
        try:
            r = requests_module.get(logo_url, headers=_BROWSER_HEADERS, timeout=5)
            if r.status_code == 200 and len(r.content) > 2000:
                ext = '.png'
                ct = r.headers.get('content-type', '')
                if 'svg' in ct:
                    ext = '.svg'
                elif 'jpeg' in ct or 'jpg' in ct:
                    ext = '.jpg'
                fname = f"site_{hashlib.md5(clean_domain.encode()).hexdigest()[:8]}{ext}"
                dest = os.path.join(current_app.static_folder, 'uploads', fname)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, 'wb') as f:
                    f.write(r.content)
                return f'static/uploads/{fname}'
        except Exception:
            continue
    return None
