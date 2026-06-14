from flask import Blueprint, redirect, url_for


bp = Blueprint('seasons', __name__)


@bp.route('/seasons')
def seasons():
    return redirect(url_for('inspiratie.inspiratie', tab='seizoen'), code=301)
