import logging

from weekmenu.routes.main import bp as main_bp
from weekmenu.routes.recipes import bp as recipes_bp
from weekmenu.routes.menu import bp as menu_bp
from weekmenu.routes.shopping import bp as shopping_bp
try:
    from weekmenu_ah import bp as ah_bp  # de AH-connector, een los package naast de app
except ImportError as e:  # niet aanwezig: de app draait zonder AH (winkelmodules-onderzoek §5)
    logging.getLogger(__name__).warning('AH-connector niet geladen: %s', e)
    ah_bp = None
from weekmenu.routes.settings import bp as settings_bp
from weekmenu.routes.import_export import bp as import_export_bp
from weekmenu.routes.seasons import bp as seasons_bp
from weekmenu.routes.inspiratie import bp as inspiratie_bp
from weekmenu.routes.pantry import bp as pantry_bp
from weekmenu.routes.dump import bp as dump_bp


def register_blueprints(app):
    for blueprint in [main_bp, recipes_bp, menu_bp, shopping_bp,
                      ah_bp, settings_bp, import_export_bp,
                      seasons_bp, inspiratie_bp, pantry_bp, dump_bp]:
        if blueprint is not None:
            app.register_blueprint(blueprint)
