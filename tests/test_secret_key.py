"""De sleutel waarmee sessies en flash-berichten ondertekend worden.

docker-compose geeft SECRET_KEY door als lege string zodra er geen .env staat.
Een lege string is aanwezig, dus een gewone default sloeg niet aan en elke
pagina die flash() of session gebruikt gaf een 500 — waaronder het opslaan op
/settings zelf.
"""
import os

from weekmenu import _secret_key


def test_lege_omgevingsvariabele_valt_terug(monkeypatch, tmp_path):
    monkeypatch.setenv('SECRET_KEY', '')
    monkeypatch.setenv('DATABASE_URL', f'sqlite:////{tmp_path}/weekmenu.db')
    assert _secret_key()


def test_gevulde_omgevingsvariabele_wint(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'uit-de-omgeving')
    assert _secret_key() == 'uit-de-omgeving'


def test_sleutel_blijft_dezelfde_na_herstart(monkeypatch, tmp_path):
    """Een sleutel die per herstart wisselt zou iedereen uitloggen."""
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:////{tmp_path}/weekmenu.db')
    eerste = _secret_key()
    assert eerste == _secret_key()
    assert (tmp_path / 'secret_key').exists()


def test_bewaarde_sleutel_is_niet_te_lezen_door_anderen(monkeypatch, tmp_path):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('DATABASE_URL', f'sqlite:////{tmp_path}/weekmenu.db')
    _secret_key()
    assert oct(os.stat(tmp_path / 'secret_key').st_mode)[-3:] == '600'


def test_geheugendatabase_krijgt_een_sleutel_zonder_bestand(monkeypatch, tmp_path):
    """Tests draaien in het geheugen; dan valt er niets naast te bewaren."""
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.chdir(tmp_path)
    assert _secret_key()
    assert not (tmp_path / 'secret_key').exists()


def test_flash_werkt_met_lege_omgevingsvariabele(monkeypatch, tmp_path):
    """De regressie zoals de gebruiker hem tegenkwam: opslaan op /settings."""
    monkeypatch.setenv('SECRET_KEY', '')
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')

    from weekmenu import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        resp = client.post('/settings', data={'default_serves': '4'})
    assert resp.status_code in (200, 302)
