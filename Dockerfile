# Python applicatie (de AH login-proxy draait nu in Python via curl_cffi,
# zie ah-proxy/proxy.py — geen Go-build meer nodig).
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

# Data-directory en de map waar de uploads overheen gemonteerd worden
RUN mkdir -p /data /app/static/uploads && chmod -R 755 /app/static/uploads

# Poort waarop de applicatie draait
EXPOSE 5001
EXPOSE 9002

ENV FLASK_APP=app.py
ENV DATABASE_URL=sqlite:////data/weekmenu.db

# Start de applicatie
COPY start.sh /start.sh
RUN chmod +x /start.sh
CMD ["/start.sh"]
