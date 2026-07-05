import json

import pytest

from weekmenu.services.dump import parse_batch_response


def test_parse_batch_response_two_recipes(app):
    payload = json.dumps([
        {"title": "Shakshuka", "yields": 4, "photo_page": 1,
         "ingredients": [{"name": "ei", "amount": 3, "unit": "stuks"}],
         "instructions": "Stap 1. Bak."},
        {"title": "Dal", "yields": 2, "photo_page": None,
         "ingredients": [{"name": "linzen", "amount": 200, "unit": "g"}],
         "instructions": "Stap 1. Kook."},
    ])
    recipes = parse_batch_response("```json\n" + payload + "\n```")
    assert len(recipes) == 2
    assert recipes[0]['name'] == 'Shakshuka'
    assert recipes[0]['photo_page'] == 1
    assert recipes[0]['ingredients'][0]['name'] == 'ei'
    assert 'category' in recipes[0]['ingredients'][0]
    assert recipes[1]['serves'] == 2


def test_parse_batch_response_skips_nameless_and_raises_on_garbage(app):
    recipes = parse_batch_response('[{"title": "", "ingredients": []}, {"title": "Soep", "ingredients": []}]')
    assert [r['name'] for r in recipes] == ['Soep']

    with pytest.raises(ValueError):
        parse_batch_response('dit is geen json')
