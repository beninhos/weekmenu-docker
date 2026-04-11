import os

from flask import Flask

from weekmenu.extensions import db


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-in-production')
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
