"""Een telbare receptmaat tegenover een verpakking die weegt.

Tien kerstomaatjes bestelden tien pakken van 380 g — bijna vier kilo tomaat —
omdat 'stuks' en 'g' niets van elkaar weten en de berekening dan terugvalt op
"rond het aantal maar af". Alle gevallen hieronder staan zo in
data/weekmenu.db; de tegenproeven staan erbij omdat die twee pakken juist
kloppen en niet stuk mogen.
"""
from datetime import date

from weekmenu.extensions import db
from weekmenu.models import Ingredient, MaatOverslaan, Recipe, RecipeIngredient
from weekmenu.services.units import _calc_ah_qty, verpakkingsroute
from weekmenu.services.verpakking import (
    antwoord_uit_conversie, bevestig_maat, conversie_uit_antwoord, schat_maat,
    sla_maat_over, verpakkingskandidaten, vraagrichting,
)

VANDAAG = date(2026, 7, 11)


# ── bouwstenen ───────────────────────────────────────────────────────────

def _ing(naam, **velden):
    ing = Ingredient(name=naam,
                     display_name=velden.pop('display_name', naam.capitalize()),
                     category=velden.pop('category', 'Groente, Fruit & Aardappelen'))
    for veld, waarde in velden.items():
        setattr(ing, veld, waarde)
    db.session.add(ing)
    db.session.flush()
    return ing


def _recept(naam, ing, hoeveelheid, eenheid):
    r = Recipe(name=naam, serves=4)
    db.session.add(r)
    db.session.flush()
    db.session.add(RecipeIngredient(recipe_id=r.id, ingredient_id=ing.id,
                                    amount=hoeveelheid, unit=eenheid))
    db.session.flush()
    return r


def _pagina(app):
    return app.test_client().get('/ah-producten').get_data(as_text=True)


def _kerstomaatjes():
    return _ing('rijpe kerstomaatjes', display_name='rijpe kerstomaatjes',
                ah_product_id=1, ah_product_name='AH Tasty Tom trostomaten',
                ah_product_size='380 g', ah_pkg_qty=380.0, ah_pkg_unit='g')


def _witte_ui():
    return _ing('witte ui', display_name='Witte Ui',
                ah_product_id=2, ah_product_name='AH Gele uien',
                ah_product_size='1 kg', ah_pkg_qty=1.0, ah_pkg_unit='kg')


def _knoflook():
    return _ing('knoflook', display_name='Knoflook',
                ah_product_id=3, ah_product_name='AH Knoflook',
                ah_product_size='2 stuks', ah_pkg_qty=2.0, ah_pkg_unit='stuks')


def _zwarte_bonen():
    return _ing('zwarte boon', display_name='Zwarte Boon',
                category='Conserven & Peulvruchten',
                ah_product_id=4, ah_product_name='AH Zwarte bonen',
                ah_product_size='400 g', ah_pkg_qty=400.0, ah_pkg_unit='g')


def _ui_per_net():
    return _ing('ui', display_name='Ui',
                ah_product_id=5, ah_product_name='AH Gele uien',
                ah_product_size='3 stuks', ah_pkg_qty=3.0, ah_pkg_unit='stuks')


# ── zo staat het er nu bij ───────────────────────────────────────────────

def test_tien_kerstomaatjes_bestellen_nu_bijna_vier_kilo(app):
    ing = _kerstomaatjes()
    assert _calc_ah_qty(ing, 10, 'stuks') == 10          # 10 × 380 g
    assert verpakkingsroute(ing, 'stuks') == 'gokken'


def test_twee_uien_bestellen_nu_twee_kilo(app):
    ing = _witte_ui()
    assert _calc_ah_qty(ing, 2, 'stuks') == 2            # 2 × 1 kg


def test_vijf_tenen_knoflook_bestellen_nu_tien_bollen(app):
    ing = _knoflook()
    assert _calc_ah_qty(ing, 5, 'teen') == 5             # 5 × 2 bollen


# ── de tegenproeven: deze twee pakken kloppen ────────────────────────────

def test_achthonderd_gram_bonen_blijft_twee_blikken(app):
    ing = _zwarte_bonen()
    assert _calc_ah_qty(ing, 800, 'g') == 2
    assert verpakkingsroute(ing, 'g') == 'zelfde-eenheid'


def test_vier_uien_blijft_twee_netten(app):
    ing = _ui_per_net()
    assert _calc_ah_qty(ing, 4, 'stuks') == 2
    assert verpakkingsroute(ing, 'stuks') == 'zelfde-eenheid'


def test_een_kilo_bonen_blijft_drie_blikken_van_vierhonderd(app):
    ing = _zwarte_bonen()
    assert _calc_ah_qty(ing, 1, 'kg') == 3
    assert verpakkingsroute(ing, 'kg') == 'maattabel'


# ── de vraag staat in de richting die bij de verpakking past ─────────────

def test_bij_een_gewichtsverpakking_vraagt_hij_wat_een_stuk_weegt(app):
    assert vraagrichting('g') == 'per_stuk'
    assert vraagrichting('kg') == 'per_stuk'
    assert vraagrichting('ml') == 'per_stuk'


def test_bij_een_telbare_verpakking_vraagt_hij_wat_er_in_een_verpakking_gaat(app):
    assert vraagrichting('stuks') == 'per_verpakking'
    assert vraagrichting('bosje') == 'per_verpakking'
    assert vraagrichting('blik') == 'per_verpakking'


def test_honderd_gram_per_tomaat_wordt_het_opslagformaat(app):
    """"1 stuks weegt 100 g" is opgeslagen als "1 g = 0,01 stuks"."""
    assert conversie_uit_antwoord('per_stuk', 100) == 0.01


def test_tien_tenen_per_bol_gaat_ongewijzigd_het_opslagformaat_in(app):
    assert conversie_uit_antwoord('per_verpakking', 10) == 10


def test_het_formulier_leest_het_opslagformaat_terug_in_de_gestelde_richting(app):
    assert antwoord_uit_conversie('per_stuk', 0.01) == 100
    assert antwoord_uit_conversie('per_verpakking', 10) == 10


def test_onzin_als_antwoord_levert_geen_conversie(app):
    assert conversie_uit_antwoord('per_stuk', 0) is None
    assert conversie_uit_antwoord('per_verpakking', -3) is None
    assert conversie_uit_antwoord('per_stuk', None) is None


# ── de schatting als startpunt ───────────────────────────────────────────

def test_de_productnaam_telt_mee_als_hij_een_aantal_noemt(app):
    """"AH Scharrel kipfilet 3 stuks" van 600 g: 200 g per filet."""
    ing = _ing('kipfilet', display_name='Kipfilet', category='Vlees & Gevogelte',
               ah_product_id=6, ah_product_name='AH Scharrel kipfilet 3 stuks',
               ah_product_size='600 g', ah_pkg_qty=600.0, ah_pkg_unit='g')
    voorstel = schat_maat(ing, 'stuks')
    assert voorstel['waarde'] == 200
    assert voorstel['richting'] == 'per_stuk'
    assert '3 stuks' in voorstel['bron'] and '600 g' in voorstel['bron']


def test_de_keukenmaten_springen_bij_als_de_productnaam_zwijgt(app):
    voorstel = schat_maat(_witte_ui(), 'stuks')
    assert voorstel['waarde'] == 150
    assert voorstel['richting'] == 'per_stuk'
    assert 'keukenmaat' in voorstel['bron']


def test_de_keukenmaat_rekent_zich_om_naar_de_eenheid_van_de_verpakking(app):
    """Een ui van 150 g tegenover een zak van 1 kg blijft in kilo's gevraagd."""
    voorstel = schat_maat(_witte_ui(), 'stuks')
    assert voorstel['eenheid'] == 'kg'
    assert voorstel['waarde'] == 150      # het antwoord staat in grammen
    assert voorstel['toon_eenheid'] == 'g'


def test_een_telbare_verpakking_krijgt_een_telbaar_voorstel(app):
    voorstel = schat_maat(_knoflook(), 'teen')
    assert voorstel['richting'] == 'per_verpakking'
    assert voorstel['waarde'] == 10       # 1 bol ≈ 10 tenen
    assert 'keukenmaat' in voorstel['bron']


def test_enkelvoud_en_meervoud_vinden_allebei_hun_keukenmaat(app):
    """'tomaat' en 'tomaten' zijn twee verschillende woorden voor de tabel."""
    for naam in ('tomaat', 'tomaten', 'trostomaten'):
        ing = _ing(naam, ah_product_id=8, ah_product_name='AH Tomaten',
                   ah_product_size='500 g', ah_pkg_qty=500.0, ah_pkg_unit='g')
        assert schat_maat(ing, 'stuks')['waarde'] == 100, naam


def test_zonder_bron_geen_voorstel(app):
    ing = _ing('papadum', display_name='Papadum', category='Overig',
               ah_product_id=7, ah_product_name="Patak's Pappadums naturel",
               ah_product_size='64 g', ah_pkg_qty=64.0, ah_pkg_unit='g')
    assert schat_maat(ing, 'stuks') is None


# ── het scherm ───────────────────────────────────────────────────────────

def test_het_scherm_toont_de_zwaarste_gevallen_bovenaan(app):
    tomaat, ui, knof = _kerstomaatjes(), _witte_ui(), _knoflook()
    _recept('Pasta', tomaat, 10, 'stuks')
    _recept('Stoof', ui, 2, 'stuks')
    _recept('Soep', knof, 5, 'teen')
    db.session.commit()

    kandidaten = verpakkingskandidaten()
    namen = [k['naam'] for k in kandidaten]
    assert namen[0] == 'rijpe kerstomaatjes'      # 10 pakken → 1
    assert set(namen) == {'rijpe kerstomaatjes', 'Witte Ui', 'Knoflook'}

    top = kandidaten[0]
    assert top['nu'] == 10
    assert top['straks'] == 1
    assert top['vraagt'] == '10 stuks'
    assert top['verpakking'] == '380 g'


def test_het_scherm_laat_de_terechte_gevallen_met_rust(app):
    bonen, ui = _zwarte_bonen(), _ui_per_net()
    _recept('Chili', bonen, 800, 'g')
    _recept('Stoof', ui, 4, 'stuks')
    db.session.commit()

    assert verpakkingskandidaten() == []


def test_de_regel_die_de_meeste_verpakkingen_kost_telt_als_bewijs(app):
    """Knoflook staat in data/weekmenu.db met 24 tenen én met 5 tenen.

    Boven de twintig geeft de gok het op en bestelt hij er één; de grootste
    regel is dus juist niet de ergste. Op hoeveelheid sorteren zou knoflook
    daarmee van het scherm laten verdwijnen.
    """
    knof = _knoflook()
    _recept('Spaghetti', knof, 24, 'teen')
    _recept('Jachtschotel', knof, 5, 'teen')
    db.session.commit()

    kandidaat = verpakkingskandidaten()[0]
    assert kandidaat['vraagt'] == '5 teen'
    assert kandidaat['nu'] == 5
    assert kandidaat['straks'] == 1
    assert kandidaat['recept'] == 'Jachtschotel'
    assert kandidaat['regels'] == 2


def test_het_scherm_waarschuwt_als_een_maat_wordt_vervangen(app):
    """Een ingredient houdt één maat vast; dat mag niet stil verdwijnen."""
    ing = _ing('pancetta', display_name='Pancetta', category='Kaas & Vleeswaren',
               ah_product_id=9, ah_product_name='AH Pancetta',
               ah_product_size='80 g', ah_pkg_qty=80.0, ah_pkg_unit='g',
               ah_conv_factor=0.02, ah_conv_unit='stuks')
    _recept('Pasta', ing, 8, 'plak')
    db.session.commit()

    kandidaat = verpakkingskandidaten()[0]
    assert kandidaat['eenheid'] == 'plak'
    assert kandidaat['vervangt'] == 'stuks'

    html = _pagina(app)
    assert 'vervangt de maat voor stuks' in html


def test_zonder_voorstel_staat_het_geval_er_toch_bij(app):
    ing = _ing('papadum', display_name='Papadum', category='Overig',
               ah_product_id=7, ah_product_name="Patak's Pappadums naturel",
               ah_product_size='64 g', ah_pkg_qty=64.0, ah_pkg_unit='g')
    _recept('Curry', ing, 4, 'stuks')
    db.session.commit()

    kandidaat = verpakkingskandidaten()[0]
    assert kandidaat['voorstel'] is None
    assert kandidaat['nu'] == 4
    assert kandidaat['straks'] is None


def test_een_bevestigde_maat_verdwijnt_van_het_scherm(app):
    tomaat = _kerstomaatjes()
    _recept('Pasta', tomaat, 10, 'stuks')
    db.session.commit()

    payload, status = bevestig_maat(tomaat.id, 'stuks', 15, 'per_stuk')
    assert status == 200 and payload['qty'] == 1

    assert verpakkingskandidaten() == []
    assert _calc_ah_qty(tomaat, 10, 'stuks') == 1
    assert (tomaat.ah_conv_unit, round(tomaat.ah_conv_factor, 4)) == ('stuks', 0.0667)


def test_niet_vragen_laat_de_berekening_staan_maar_leegt_het_scherm(app):
    ing = _ing('papadum', display_name='Papadum', category='Overig',
               ah_product_id=7, ah_product_name="Patak's Pappadums naturel",
               ah_product_size='64 g', ah_pkg_qty=64.0, ah_pkg_unit='g')
    _recept('Curry', ing, 4, 'stuks')
    db.session.commit()

    payload, status = sla_maat_over(ing.id, 'stuks')
    assert status == 200

    assert verpakkingskandidaten() == []
    assert MaatOverslaan.query.count() == 1
    assert ing.ah_conv_factor is None
    assert _calc_ah_qty(ing, 4, 'stuks') == 4


def test_niets_gaat_stil_vanzelf(app):
    """Zonder klik blijft de berekening staan zoals hij stond."""
    tomaat = _kerstomaatjes()
    _recept('Pasta', tomaat, 10, 'stuks')
    db.session.commit()

    verpakkingskandidaten()

    assert tomaat.ah_conv_factor is None
    assert _calc_ah_qty(tomaat, 10, 'stuks') == 10


# ── de pagina ────────────────────────────────────────────────────────────

def test_de_pagina_toont_het_blok_met_voorstel_en_bewijs(app, client):
    tomaat = _kerstomaatjes()
    _recept('Pasta', tomaat, 10, 'stuks')
    db.session.commit()

    html = client.get('/ah-producten').get_data(as_text=True)
    assert 'Verpakkingen die niet kloppen' in html
    assert 'rijpe kerstomaatjes' in html
    assert 'keukenmaat' in html
    assert '10 stuks' in html


def test_de_pagina_zwijgt_als_er_niets_te_doen_is(app, client):
    bonen = _zwarte_bonen()
    _recept('Chili', bonen, 800, 'g')
    db.session.commit()

    html = client.get('/ah-producten').get_data(as_text=True)
    assert 'Verpakkingen die niet kloppen' not in html


def test_bevestigen_via_de_knop(app, client):
    tomaat = _kerstomaatjes()
    _recept('Pasta', tomaat, 10, 'stuks')
    db.session.commit()

    r = client.post(f'/api/ah/ingredient/{tomaat.id}/maat',
                    json={'eenheid': 'stuks', 'waarde': 15, 'richting': 'per_stuk'})
    assert r.status_code == 200
    assert r.get_json()['qty'] == 1
    assert _calc_ah_qty(Ingredient.query.get(tomaat.id), 10, 'stuks') == 1


def test_niet_vragen_via_de_knop(app, client):
    tomaat = _kerstomaatjes()
    _recept('Pasta', tomaat, 10, 'stuks')
    db.session.commit()

    r = client.post(f'/api/ah/ingredient/{tomaat.id}/maat/overslaan',
                    json={'eenheid': 'stuks'})
    assert r.status_code == 200
    assert verpakkingskandidaten() == []


def test_het_formulier_slaat_de_omgedraaide_vraag_goed_op(app, client):
    """Wat het formulier stuurt is het antwoord, niet de factor."""
    tomaat = _kerstomaatjes()
    db.session.commit()

    r = client.post(f'/api/ah/ingredient/{tomaat.id}/pkg-config',
                    json={'ah_pkg_qty': 380, 'ah_pkg_unit': 'g',
                          'maat_eenheid': 'stuks', 'maat_waarde': 15,
                          'maat_richting': 'per_stuk'})
    assert r.status_code == 200
    ing = Ingredient.query.get(tomaat.id)
    assert ing.ah_conv_unit == 'stuks'
    assert round(ing.ah_conv_factor, 4) == 0.0667
    assert _calc_ah_qty(ing, 10, 'stuks') == 1


def test_een_leeg_antwoord_wist_de_conversie(app, client):
    tomaat = _kerstomaatjes()
    tomaat.ah_conv_factor, tomaat.ah_conv_unit = 0.0667, 'stuks'
    db.session.commit()

    r = client.post(f'/api/ah/ingredient/{tomaat.id}/pkg-config',
                    json={'ah_pkg_qty': 380, 'ah_pkg_unit': 'g',
                          'maat_eenheid': '', 'maat_waarde': None,
                          'maat_richting': 'per_stuk'})
    assert r.status_code == 200
    ing = Ingredient.query.get(tomaat.id)
    assert ing.ah_conv_factor is None and ing.ah_conv_unit is None
