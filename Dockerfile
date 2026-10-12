# Python applicatie. De AH-connector (privé-repo weekmenu-ah, met de login-
# proxy) komt via de build-context `ah` mee: zie docker-compose*.yml.
#
# Het OCR-hulpscript scripts/cookbook_ocr draait bewust buiten dit image: het
# heeft tesseract en opencv nodig en die horen hier niet (zie de README daar).
# De importroute in de app praat met Cloud Vision over HTTPS en heeft daarvoor
# niets extra's nodig: ocr.py komt toe met de standaardlibrary plus Pillow, dat
# hier toch al voor de fotoverwerking staat.
FROM python:3.12-slim

WORKDIR /app

# Geen .pyc-bestanden, en logregels meteen doorgeven in plaats van bufferen:
# anders blijven de waarschuwingen uit de OCR-stap in de buffer hangen en zie
# je ze niet terug in `docker compose logs`.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Eerst de afhankelijkheden, dan pas de code: zo blijft deze laag in de cache
# staan zolang requirements.txt niet verandert.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de applicatiecode. Wat er niet in hoort staat in .dockerignore —
# vooral static/uploads, dat bij het draaien toch als volume gemonteerd wordt.
COPY . .

# De AH-connector uit de privé-repo: compose wijst context `ah` naar die map
# (additional_contexts). Een lege map (docker/zonder-ah) geeft een app zonder AH;
# de connector-afhankelijkheden gaan dan ook niet mee.
COPY --from=ah / /app/weekmenu_ah/
RUN if [ -f /app/weekmenu_ah/requirements.txt ]; then \
        pip install --no-cache-dir -r /app/weekmenu_ah/requirements.txt; fi

# De Picnic-connector, zelfde patroon (context `picnic`, lege map docker/zonder-picnic).
# shortcut: python-picnic-api2 eist Python 3.13 maar draait op 3.12; upgraden naar
# python:3.13-slim zodra SQLAlchemy een 3.13-wheel heeft, dan kan de env-var weg.
# De import-check laat de build falen, niet de app bij de eerste klik.
COPY --from=picnic / /app/weekmenu_picnic/
RUN if [ -f /app/weekmenu_picnic/requirements.txt ]; then \
        PIP_IGNORE_REQUIRES_PYTHON=1 pip install --no-cache-dir -r /app/weekmenu_picnic/requirements.txt \
        && python -c "import python_picnic_api2"; fi

# Data-directory en de map waar de uploads overheen gemonteerd worden
RUN mkdir -p /data /app/static/uploads && chmod -R 755 /app/static/uploads

# Niet als root draaien: een kwaadaardige recept-PDF of afbeelding gaat door
# Pillow/pypdfium2, en die parsers zijn zwaar C-based; als daar ooit iets
# stukgaat, willen we niet dat het als root gebeurt. De user is systeem-account
# (login shell uit); /data en /app/static/uploads worden meegemount vanaf de
# host als hun bind-mount volumes, dus die krijgen hun eigenaar van de host.
# UID/GID 1000 komt overeen met de host-user, zodat bind-mounts (./data,
# ./static/uploads) zonder handmatige chown werken.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -s /usr/sbin/nologin app \
    && chown -R app:app /app /data
USER app

# Poort waarop de applicatie draait
EXPOSE 5001
EXPOSE 9002

ENV FLASK_APP=app.py
ENV DATABASE_URL=sqlite:////data/weekmenu.db

# Start de applicatie
COPY --chown=app:app start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
