FROM python:3.12-slim

WORKDIR /app

# Installeer benodigde pakketten
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer de applicatiecode
COPY . .

# Maak de data-directory aan
RUN mkdir -p /data
RUN mkdir -p /app/static/uploads
RUN chmod -R 755 /app/static/uploads

# Poort waarop de applicatie draait
EXPOSE 5001

# Configureer environment variabelen
ENV FLASK_APP=app.py
ENV FLASK_ENV=development
ENV FLASK_RUN_PORT=5001
ENV FLASK_RUN_HOST=10.0.1.3
ENV DATABASE_URL=sqlite:////data/weekmenu.db

# Start de applicatie
CMD ["python", "app.py"]
