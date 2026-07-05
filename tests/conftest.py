import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ['DATABASE_URL'] = 'sqlite://'  # in-memory

from weekmenu import create_app
from weekmenu.extensions import db as _db


@pytest.fixture()
def app(tmp_path):
    app = create_app()
    app.config['TESTING'] = True
    app.static_folder = str(tmp_path / 'static')
    os.makedirs(os.path.join(app.static_folder, 'uploads'), exist_ok=True)
    with app.app_context():
        yield app
        _db.session.rollback()


@pytest.fixture()
def client(app):
    return app.test_client()
