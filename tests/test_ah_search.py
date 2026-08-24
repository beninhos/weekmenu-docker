from unittest.mock import patch

from weekmenu.services.ah import ah_search_with_facets, _ah_taxonomies
from weekmenu.services.units import parse_size_filter, size_matches


# ── Maat-invoer van de gebruiker ─────────────────────────────────────────

def test_parse_size_filter_varianten():
    assert parse_size_filter('800 g') == (800.0, 'g')
    assert parse_size_filter('800g') == (800.0, 'g')
    assert parse_size_filter('1,5 kg') == (1.5, 'kg')
    assert parse_size_filter('800') == (800.0, '')  # zonder eenheid
    assert parse_size_filter('veel') is None
    assert parse_size_filter('') is None


def test_size_matches_over_eenheden_heen():
    want_800g = parse_size_filter('800 g')
    assert size_matches('800 g', want_800g)
    assert size_matches('ca. 800 g', want_800g)
    assert not size_matches('600 g', want_800g)
    assert not size_matches('3 stuks', want_800g)
    # 0,8 kg en 800 g zijn dezelfde verpakking
    assert size_matches('800 g', parse_size_filter('0,8 kg'))
    # Zonder eenheid telt alleen het getal
    assert size_matches('800 g', parse_size_filter('800'))
    assert size_matches('800 ml', parse_size_filter('800'))


# ── Zoeken met soort- en maat-filter ─────────────────────────────────────

def _raw(products, taxonomy_options=(), total=None):
    return {
        'products': [{'webshopId': i, 'title': t, 'salesUnitSize': s,
                      'mainCategory': c, 'currentPrice': 1.0}
                     for i, (t, s, c) in enumerate(products, start=1)],
        'filters': [{'id': 'taxonomy', 'options': list(taxonomy_options)}],
        'page': {'totalElements': total if total is not None else len(products)},
    }


KIPFILET = [
    ('AH Scharrel kipfilet 2 stuks', '300 g', 'Vlees'),
    ('AH Scharrel roasted kipfilet', '150 g', 'Vleeswaren'),
    ('AH Scharrel kipfilet', '800 g', 'Vlees'),
    ('AH Scharrel kipfilet 3 stuks', '600 g', 'Vlees'),
]


def test_maat_filter_houdt_alleen_die_verpakking_over(app):
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(KIPFILET)):
        res = ah_search_with_facets('kipfilet', size=50, pkg='800 g')
    assert [p['title'] for p in res['products']] == ['AH Scharrel kipfilet']
    assert res['products'][0]['pkgQty'] == 800.0
    assert res['products'][0]['pkgUnit'] == 'g'


def test_altijd_volledige_uitslag_ophalen(app):
    # AH's ranking zet afwijkende verpakkingen achteraan, dus halen we alles op
    # en tonen we er `size` van. Anders klopt de maten-lijst ook niet.
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(KIPFILET)) as m:
        res = ah_search_with_facets('kipfilet', size=2)
    assert m.call_args.args[1] == 300
    assert len(res['products']) == 2
    assert res['shown'] == 4


def test_maten_lijst_klein_naar_groot_gewicht_voor_stuks(app):
    catalogus = [
        ('Kipfilet 3-pack', '3 stuks', 'Vlees'),
        ('Kipfilet groot', '800 g', 'Vlees'),
        ('Kipfilet klein', '300 g', 'Vlees'),
        ('Kipfilet bulk', '1,5 kg', 'Vlees'),
        ('Kipfilet klein 2', 'ca. 300 g', 'Vlees'),
        ('Kippenbouillon', '500 ml', 'Soep'),
        ('Onbekend', '', 'Vlees'),
    ]
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(catalogus)):
        res = ah_search_with_facets('kipfilet', size=50)
    assert [(s['label'], s['count']) for s in res['sizes']] == [
        ('300 g', 2),    # "300 g" en "ca. 300 g" zijn dezelfde verpakking
        ('800 g', 1),
        ('1,5 kg', 1),   # 1,5 kg sorteert ná 800 g, niet ervoor
        ('500 ml', 1),   # volume na gewicht
        ('3 stuks', 1),  # stuks-achtige maten achteraan
    ]


def test_maat_chip_filtert_op_zijn_eigen_label(app):
    # Elk chip-label moet als filter terugkomen: de UI stuurt precies dit terug.
    catalogus = [('Eén stuk', 'per stuk', 'Vlees'), ('Bulk', '1,5 kg', 'Vlees'),
                 ('Zes', '6 stuks', 'Vlees')]
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(catalogus)):
        labels = [s['label'] for s in ah_search_with_facets('kip', size=50)['sizes']]
        assert labels == ['1,5 kg', '1 stuk', '6 stuks']  # niet "1 stuks"
        for label in labels:
            res = ah_search_with_facets('kip', size=50, pkg=label)
            assert len(res['products']) == 1, f'{label} vindt niets'


def test_onbegrijpelijke_maat_geeft_melding_zonder_ah_call(app):
    with patch('weekmenu.services.ah._ah_search_raw') as m:
        res = ah_search_with_facets('kipfilet', size=50, pkg='veel')
    assert res['products'] == []
    assert 'niet begrepen' in res['error']
    m.assert_not_called()


def test_zeldzame_maat_valt_niet_weg_uit_de_lijst(app):
    # 40 gangbare maten plus één afwijkende: die ene is nu juist de gezochte.
    catalogus = [(f'Pak {i}', f'{100 + i * 10} g', 'Vlees') for i in range(40)]
    catalogus.append(('AH Scharrel kipfilet', '800 g', 'Vlees'))
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(catalogus)):
        res = ah_search_with_facets('kipfilet', size=50)
    assert '800 g' in [s['label'] for s in res['sizes']]


def test_maat_zonder_treffer_houdt_de_maten_lijst_intact(app):
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(KIPFILET, total=283)):
        res = ah_search_with_facets('kipfilet', size=50, pkg='950 g')
    assert res['products'] == []
    assert res['total'] == 283
    # De chips blijven staan, anders kun je niet naar een andere maat springen.
    assert [s['label'] for s in res['sizes']] == ['150 g', '300 g', '600 g', '800 g']


def test_taxonomy_id_gaat_mee_naar_ah(app):
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(KIPFILET)) as m:
        ah_search_with_facets('kipfilet', size=50, taxonomy_id='1231')
    assert m.call_args.args[2] == '1231'


def test_soort_facet_grootste_eerst():
    data = _raw([], taxonomy_options=[
        {'id': 1231, 'label': 'Kipfilet stuk', 'count': 39},
        {'id': 1226, 'label': 'Kip', 'count': 164},
        {'id': 0, 'label': 'Zonder id', 'count': 5},
    ])
    tax = _ah_taxonomies(data)
    assert [t['label'] for t in tax] == ['Kip', 'Kipfilet stuk']
    assert tax[0]['id'] == '1226'


def test_ah_fout_geeft_lege_uitslag_terug(app):
    with patch('weekmenu.services.ah._ah_search_raw', side_effect=RuntimeError('AH plat')):
        res = ah_search_with_facets('kipfilet', size=50)
    assert res == {'products': [], 'taxonomies': [], 'sizes': [], 'total': 0, 'shown': 0}


def test_endpoint_geeft_products_en_taxonomies(client):
    with patch('weekmenu.services.ah._ah_search_raw', return_value=_raw(
            KIPFILET, taxonomy_options=[{'id': 1231, 'label': 'Kipfilet stuk', 'count': 39}])):
        data = client.get('/api/ah/product-search?q=kipfilet&size=50&pkg=800 g').get_json()
    assert [p['title'] for p in data['products']] == ['AH Scharrel kipfilet']
    assert data['taxonomies'] == [{'id': '1231', 'label': 'Kipfilet stuk', 'count': 39}]


def test_endpoint_lege_query(client):
    assert client.get('/api/ah/product-search?q=').get_json() == {
        'products': [], 'taxonomies': [], 'sizes': [], 'total': 0, 'shown': 0}
