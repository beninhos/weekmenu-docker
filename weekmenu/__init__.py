import os
import secrets

from flask import Flask

from weekmenu.extensions import db


def _secret_key():
    """De sleutel waarmee sessies en flash-berichten ondertekend worden.

    Let op de `or`: docker-compose geeft SECRET_KEY door als lege string zodra
    er geen .env staat, en een lege string is wél aanwezig. Met een gewone
    default sloop je daarmee elke pagina die flash() of session gebruikt —
    opslaan op /settings gaf zo een 500.

    Staat er niets, dan maken we er eenmalig een aan naast de database. Een
    sleutel die elke herstart verandert zou iedereen uitloggen, en een vaste
    tekst in de broncode is er geen: daarmee kan iedereen die de code kent een
    sessiekoekje vervalsen.
    """
    uit_omgeving = os.environ.get('SECRET_KEY')
    if uit_omgeving:
        return uit_omgeving

    map_ = _data_map()
    if not map_:
        # Geen bestandsdatabase (tests draaien in het geheugen): niets om naast
        # te bewaren, en er valt ook niets uit te loggen.
        return secrets.token_hex(32)

    pad = os.path.join(map_, 'secret_key')
    try:
        if os.path.exists(pad):
            bewaard = open(pad).read().strip()
            if bewaard:
                return bewaard
        nieuw = secrets.token_hex(32)
        with open(pad, 'w') as bestand:
            bestand.write(nieuw)
        os.chmod(pad, 0o600)
        return nieuw
    except OSError:
        # Read-only volume: liever draaien met een sleutel die per herstart
        # wisselt dan helemaal niet starten.
        return secrets.token_hex(32)


def _data_map():
    """De map van de SQLite-database, of None als die niet op schijf staat."""
    url = os.environ.get('DATABASE_URL', 'sqlite:////data/weekmenu.db')
    if not url.startswith('sqlite:////'):
        return None
    return os.path.dirname(url[len('sqlite:///'):]) or None


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    app.config['SECRET_KEY'] = _secret_key()
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:////data/weekmenu.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)

    from weekmenu.routes import register_blueprints
    register_blueprints(app)

    with app.app_context():
        db.create_all()
        from weekmenu.migrations import migrate_db
        migrate_db()

    return app
