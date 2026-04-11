import re
import os
import hashlib

from flask import current_app

from weekmenu.extensions import db
from weekmenu.models import Ingredient, IngredientAlias, Cookbook, Settings
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


def _get_or_create_site_cookbook(domain, html_text, scraper, requests_module):
    """Find or create a Cookbook entry for a website. Returns Cookbook or None."""
    clean_domain = re.sub(r'^www\.', '', domain)

    name = _KNOWN_SITES.get(clean_domain)
    if not name:
        try:
            name = scraper.site_name() or clean_domain.split('.')[0].capitalize()
        except Exception:
            name = clean_domain.split('.')[0].capitalize()

    cookbook = Cookbook.query.filter_by(name=name).first()
    if cookbook:
        return cookbook

    # Download logo
    image_path = None
    try:
        urls_to_try = [
            f'https://logo.clearbit.com/{clean_domain}?size=128',
        ]
        from urllib.parse import urljoin
        for tag in ['apple-touch-icon', 'icon']:
            match = re.search(
                rf'<link[^>]*rel=["\'](?:apple-touch-icon|{tag})["\'][^>]*href=["\']([^"\']+)',
                html_text, re.IGNORECASE,
            )
            if match:
                urls_to_try.insert(0, urljoin(f'https://{domain}', match.group(1)))
                break

        for logo_url in urls_to_try:
            try:
                r = requests_module.get(logo_url, headers=_BROWSER_HEADERS, timeout=5)
                if r.status_code == 200 and len(r.content) > 500:
                    ext = '.png'
                    ct = r.headers.get('content-type', '')
                    if 'svg' in ct:
                        ext = '.svg'
                    elif 'jpeg' in ct or 'jpg' in ct:
                        ext = '.jpg'
                    fname = f"site_{hashlib.md5(clean_domain.encode()).hexdigest()[:8]}{ext}"
                    dest = os.path.join(current_app.root_path, 'static', 'uploads', fname)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, 'wb') as f:
                        f.write(r.content)
                    image_path = f'static/uploads/{fname}'
                    break
            except Exception:
                continue
    except Exception:
        pass

    cookbook = Cookbook(name=name, image_path=image_path)
    db.session.add(cookbook)
    db.session.flush()
    return cookbook


def _get_gemini_api_key():
    """Get Gemini API key from database or environment."""
    s = Settings.query.filter_by(key='gemini_api_key').first()
    if s and s.value:
        return s.value
    return os.environ.get('GEMINI_API_KEY')
