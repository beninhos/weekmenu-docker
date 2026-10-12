# Picnic-connector: uitgang en account (stap 3 winkelmodules)

Datum: 12 oktober 2026. Besluiten van Rutger in de chat, vastgelegd hier.
Bouwt voort op `2026-10-12-winkelmodules-onderzoek.md` §3 (Picnic) en §5.

## Doel

Niveau 3 voor Picnic: koppelen met Rutgers eigen account via Instellingen
(e-mail, wachtwoord, 2FA-code), uitgang `picnic` die de Picnic-mand vult, en de
mand teruglezen in het bestel-log. Nog geen catalogus en geen productkoppeling
per ingrediënt; geen bestelling plaatsen. Alleen eigen account: geen route
waarin de app met wachtwoorden van anderen inlogt.

## Waar het staat

- Privé-repo `/pool/apps/weekmenu-picnic`, repo-root = package `weekmenu_picnic`,
  AGPL-3.0 zoals de app. README met één regel: Picnic's voorwaarden (art. 13)
  verbieden dit soort tools. Niets dat captcha's of WAF's omzeilt; de library
  stuurt alleen de vaste app-headers.
- Library: `python-picnic-api2==2.0.1` (Home Assistant core). Eist Python ≥ 3.13;
  de image is 3.12. Installeren met `PIP_IGNORE_REQUIRES_PYTHON=1` op alleen de
  `RUN`-regel die connector-requirements installeert, met `shortcut:`-commentaar
  (limiet: lib eist 3.13; upgraden zodra SQLAlchemy een 3.13-wheel heeft).
  Direct erna `RUN python -c "import python_picnic_api2"` zodat de build faalt
  in plaats van de app bij de eerste klik. Op de host bewezen: wheel importeert
  en de client werkt op 3.12.3.
- Mand vullen: de lus met `add_product(id, aantal)` uit de library, geen
  bulk-endpoint (dat komt uit de npm-lib en breekt als eerste).

## Contract van een uitgang (app-wijziging)

Een uitgang in `shopping.UITGANGEN` krijgt `(shopping_dict, qty_overrides)` en
geeft `(payload, status, sent_ingredient_ids)`. `_mandje(shopping_dict,
qty_overrides)` (lijst → `{ah_product_id: aantal}`) wordt een helper die `ah`
en `deeplink` zelf aanroepen; de melding "Geen gekoppelde AH-producten" hoort
bij die twee. `send_dict_to_ah` blijft de dispatcher: lege lijst → 200,
`papier` → 400, anders de uitgang. `UITGANG_KEUZES` vervalt: geldig is
`'papier'` of een sleutel van `UITGANGEN`.

Gevolg voor `weekmenu-ah`: `verstuur_naar_ah(shopping_dict, qty_overrides)`
roept `_mandje` aan (3 regels), en `__init__.py` registreert
`shopping.BESTELLING_LEZERS['ah']` (zie hieronder). Eén commit daar.

## Zoeken op naam bij versturen

Per open regel (bron supermarkt) `client.search(ing.display)`; de eerste tegel
wint; aantal = `qty_overrides[ing_id]` als Rutger het op de pagina aanpaste,
anders 1. Geen treffer → overslaan, niet afvinken (blijft open). De melding na
versturen toont per regel de match ("pijnboompitten → Pijnboompitten 100 g")
en de missers apart: dat is de enige bescherming tegen verkeerde treffers
zolang er geen catalogus is. Payload: `{'status': 'success', 'sent': n,
'matches': [[naam, productnaam], ...], 'not_linked': [...], 'order_id':
mand-id, 'message': ...}`; de boodschappenpagina toont `message` (regels
gescheiden door newlines) in de bestaande alert.

## Bestel-log

Na het vullen `get_cart()` teruglezen en opslaan als regels met bron
`picnic-mand` (de mand is geen bestelling; het log blijft eerlijk).
`services/bestellingen.leg_ah_order_vast(jaar, week, order, bron='ah')` krijgt
de `bron`-parameter en gebruikt `item['ingredient_id']` als die er is (de
zoekstap weet welk ingrediënt welk product werd). De connector zet de Cart om
naar dat order-dict: `groups[0].items[]` met `productId` (selling-unit-id),
`title`, `quantity`, `price` (euro uit centen), `ingredient_id`;
`orderId` leeg (Integer-kolom, Picnic-ids zijn strings), `total` uit
`total_price`. `routes/shopping._leg_de_bestelling_vast` kiest de lezer via
`shopping.BESTELLING_LEZERS[huidige_uitgang()]`; ontbreekt die, dan niets.
Roadmap: na afrekenen de echte bezorging lezen via `get_current_deliveries()`
en `get_delivery(id)`.

## Instellingen per staat

Blok `_picnic_instellingen.html`, gewone formulieren (POST + redirect + flash),
geen JS. `picnic_beschikbaar` in de context processor, zoals `ah_beschikbaar`.

- **Niet gekoppeld**: e-mail, wachtwoord (`autocomplete="current-password"`),
  keuze sms/e-mail voor de code, knop Koppelen → `POST /api/picnic/login`.
  Het wachtwoord gaat alleen die ene request in (de library md5't het zelf);
  nooit opgeslagen, nooit gelogd. Login zonder 2FA-eis → meteen gekoppeld.
- **2FA-code nodig**: "Code gestuurd per sms/e-mail", invoerveld, Bevestigen
  (`POST /api/picnic/2fa`), Opnieuw sturen, Annuleren. De half-ingelogde
  `PicnicAPI` blijft in het procesgeheugen (één gebruiker), met vervaltijd van
  tien minuten; daarna begint de koppeling opnieuw. Pas na een goede code gaat
  het token naar `Settings` (`picnic_auth_token`, `picnic_email`).
- **Gekoppeld**: "✓ Verbonden als <e-mail>", Verbinding testen (`get_user`),
  Ontkoppelen (wist beide keys).

`PicnicAuthError` tijdens versturen → 401 "Picnic-koppeling verlopen, koppel
opnieuw in Instellingen"; het token blijft staan tot Rutger ontkoppelt.

## In de image

- Dockerfile: `COPY --from=picnic / /app/weekmenu_picnic/` + requirements-regel
  met `PIP_IGNORE_REQUIRES_PYTHON=1` + import-check.
- Context `picnic: ../../weekmenu-picnic` in `docker-compose.yml`,
  `docker-compose.dev.yml` en `docker-compose.beta.yml` (anders breekt de build
  van dev en live zodra de branch gemerged wordt).
- `docker-compose.zonder-picnic.yml` wijst `picnic` naar de lege map
  `docker/zonder-picnic` (`.gitkeep`).
- `weekmenu_picnic` in `.gitignore` en `.dockerignore`; symlink in `beta/`.

## Overige app-wijzigingen

- Optie "Naar je Picnic-mand" in het uitgang-menu als `picnic_beschikbaar`.
- Knop op de boodschappenpagina: "Verstuur naar Picnic" bij uitgang `picnic`.
- Patch naar 0.8.5-beta met changelog-regel.

## Tests (alles gemockt, geen echte Picnic-aanroepen)

Connector (`weekmenu_picnic/tests`, conftest als bij AH, `FakePicnic` via
monkeypatch op `weekmenu_picnic.client.PicnicAPI`): koppeling registreert
blueprint, uitgang en lezer; login → 2FA-staat → goede code → gekoppeld;
foute code blijft in 2FA; verlopen pending client → opnieuw beginnen; uitgang
zoekt per naam, add_product per treffer, slaat missers over, vinkt alleen
treffers af, melding toont matches; AuthError → 401; mand → regels met bron
`picnic-mand`. App: zonder connector geen optie `picnic`; `deeplink` en `ah`
werken met het nieuwe contract (bestaande tests).

## Verificatie

Pytest app + beide connectors; beta rebuild; koppelen doet Rutger zelf op
`http://10.0.1.3:5003/settings`; daarna één lijst versturen, mand in de
Picnic-app controleren (Rutger maakt hem zelf leeg; geen bestelling); beta één
keer met `zonder-picnic` bouwen: app start, optie ontbreekt. Drie repo's, één
commit per repo, alle drie pushen.
