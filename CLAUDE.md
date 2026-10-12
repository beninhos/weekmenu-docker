# Weekmenu-planner — hoe deze repo werkt

Een single-user Flask-app die het weekmenu plant, boodschappenlijsten samenstelt en recepten importeert. Draait in Docker op de host van de eigenaar; er zijn geen externe gebruikers.

## Eerste sessies: lees dit, dan hoef je niets meer op te zoeken.

## Waarom, in één zin per subsysteem

- **`/week/<jaar>/<week>`**: het weekmenu. Recepten koppelen aan dagen, keer aantal personen, dat bepaalt de rest.
- **`/boodschappen`**: aggregeert de receptregels van de **lopende** weken naar één lijst, filtert wat in de voorraadkast staat, mergt varianten van hetzelfde ingredient, en stuurt op verzoek naar AH. Een week die geweest is doet niet meer mee; wat er gekocht is staat in het bestel-log.
- **`/dump`**: kookboekfoto's of receptkaarten opnemen. Cloud Vision leest de tekst, Gemini structureert het naar recept-JSON, de gebruiker keurt goed op de nakijkkaart. Twee modi: **boek** (één pagina = één recept) en **kaart** (twee pagina's = één recept, tabel is leidend).
- **`/twijfelgevallen`**: waar de app twee ingrediënten als vermoedelijke variant ziet (Bosui/Lente-Ui), of een categorie afwijkt van wat de gokker zegt. Één klik voegt samen of markeert als "apart".
- **`/ah-producten`**: per ingredient een AH-product koppelen zodat "Stuur naar AH" weet welk product te bestellen.
- **`/voorraad`**: ingrediënten die altijd in huis zijn — verdwijnen dan van de boodschappenlijst.
- **`/inspiratie`**: seizoen + eco-booster-scoring om recepten voor te stellen die passen bij wat nu goedkoop of duurzaam is.

## Architectuur

Driedeling **routes → services → models**. Één richting, geen cyclus.

```
weekmenu/
├── routes/         # HTTP-schil, dun. Blueprints per domein.
├── services/       # De business-logica. Praten met models + elkaar.
├── models.py       # SQLAlchemy — 21 tabellen.
├── migrations.py   # v1..v23, additief, draaien op elke opstart.
├── constants.py    # Categorieën, eenheidstabellen, AH-endpoint-URLs.
├── extensions.py   # db-object, geïmporteerd waar nodig — breekt de cyclus.
└── __init__.py     # create_app(), context-processor, __version__.
```

**Import-richting**: routes importeren services, services importeren models. Nooit andersom. Als je een import van route ➔ route ziet: fix.

**Services die de kern dragen**:
- `services/units.py`: parseren en normaliseren van hoeveelheden en eenheden. Utility-laag, bijna alle andere services leunen erop.
- `services/ingredienten.py`: samenvoegen van dubbele ingrediënten (varianten), aliassen, "apart"-besluiten. Groot (~1150r) — mag over de tijd splitsen naar `samenvoegen.py` + `kandidaten.py`.
- `services/dump.py`: orkestreert de OCR-flow. Bewust één plek om de keten (bronbeelden → Cloud Vision → Gemini → concepten → RecipeDraft) te zien.
- `services/ankers.py`: knipt bereidingstekst uit de OCR-tekst op basis van eerste/laatste-woord-ankers van Gemini. Kernvondst: het model schrijft niet meer over, wijst alleen aan.
- `services/kaart.py` + `services/kaartsignaturen.py`: alles wat merkspecifiek is aan een receptkaart (HelloFresh-logo, "Zelf toevoegen"-kop, "Bereidingstijd: N min"). Merkloos ontwerp: een nieuw merk is een nieuw dict in `MERKEN`, geen nieuwe code.
- `services/verpakking.py`: de vraag "1 tomaat weegt hoeveel gram" — brug tussen telbare recepteenheid en gewichtsverpakking.
- `services/pantry.py`: voorraadhints + review-lijsten voor `/twijfelgevallen`.
- `services/shopping.py`: aggregatie van receptregels naar de boodschappenlijst. Per week: `open = nodig − afgevinkt − weggehaald` (`week_nodig`, `_week_stand`). `window_weeks()` geeft alle geplande weken, `lopende_weken()` de weken waarin een zijdelingse wijziging nog mag doorwerken — die tweede is de grens tussen 'nog mee bezig' en 'geweest'.
- `services/afgehandeld.py`: wat er per week per ingredient al afgevinkt of weggehaald is, als hoeveelheid per eenheid (NULL = alles). Toevoegen raakt dit nooit aan: wat afgevinkt is blijft afgevinkt, alleen het nieuwe komt op de lijst (Rutger, 4 okt 2026). Uitzonderingen: uit de voorraad halen zet terug, een voorbije week wordt afgesloten, en recept bewerken laat het afgehandelde deel naar rato meegroeien.
- `services/bestellingen.py`: het bestel-log. Eén pot per week, AH-regels teruggelezen uit de order (niet wat de app stuurde), handmatig afgevinkte regels in dezelfde pot.
- `services/ah.py`: AH-API-client — tokens, product-search, prijsadvies, order-write.
- `services/gemini.py`: Gemini-integratie voor URL- en foto-imports (los van de OCR-dump).

## Conventies

- **API-payload-vorm**: succes = `{status: 'success', ...}`, fout = `{status: 'error', message: '...'}, 4xx/5xx`. Service-functies retourneren consequent `(payload, statuscode)`; de route ontrafelt via `_antwoord(...)`-helper in `routes/pantry.py`. Frontend checkt `data.status === 'success'`.
- **Nederlands vs Engels**: gebruikersvlakken en business-jargon in het Nederlands (`voeg_samen`, `bereiding`, `koppel_alias`); utility-code (units, generieke helpers) mag Engels. Op één plek gemixt: `services/menu.py` (Engels, `plan_recipe` etc.).
- **Docstrings**: waarom-gedreven, verwijzen naar échte metingen ("gemeten op 22 pagina's: 252 van 252 ankers exact"). Geen ceremoniële one-liners.
- **Private prefix `_`**: hard voor helpers die niemand buiten het bestand hoort te importeren. Als iets `_` heet én van buiten wordt geïmporteerd, is een van beide fout.
- **Template-data doorgeven aan JS**: `<script type="application/json" id="data-x">{{ x|tojson }}</script>` + `JSON.parse(document.getElementById('data-x').textContent)`. **Niet** `window.__DATA` — vervuilt de namespace.
- **Migraties**: `weekmenu/migrations.py` bevat 23 versies achter `schema_version`-guards. Nieuw = `_migrate_vN()` erbij, oude nooit wijzigen. Migraties zijn additief; ze rollen niet terug.
- **AH-tokens en API-sleutels**: via `/settings` in de database (of via env-var als fallback). Nooit hardcoden.
- **Testen**: `pytest`, ~600 tests, Nederlandse gedragsnamen (`test_zondag_valt_niet_buiten_de_printmarge`). Fixtures in `tests/conftest.py`, mocks op de netwerkrand (Cloud Vision, Gemini, AH). In-memory sqlite, geen echte DB-writes.

## Ontwikkelen en draaien

**Twee worktrees** onder `/pool/apps/weekmenu/`:

| Worktree | Branch | Container | Poort |
|---|---|---|---|
| `live/` | `main` | `weekmenu-live-weekmenu-1` | 5001 |
| `dev/`  | `stabiliseren-*` (of feature-branch) | `weekmenu-dev-weekmenu-dev-1` | 5002 |

**Live rebuilden**:
```bash
cd /pool/apps/weekmenu/live
docker compose -p weekmenu-live build weekmenu
docker compose -p weekmenu-live up -d weekmenu
```

**Dev rebuilden**:
```bash
cd /pool/apps/weekmenu/dev
docker compose -p weekmenu-dev -f docker-compose.dev.yml up -d --build weekmenu-dev
```

De dev-container draait als `app:1000` (matcht host-user beninho), heeft eigen `data/weekmenu_dev.db` en eigen `static/uploads/`. De live-container is identiek als user, maar deelt de eigenaars-data.

**Debug-mode**: aan (`app.py:6` — `debug=True`), maar `use_reloader=False`. De Werkzeug-PIN-console is toegankelijk bij een crash; **kritiek**: reloader mág niet aan want dat fork-t Flask en breekt de `herstel_verloren_jobs()`-supervisor plus de `threading.Lock` in `services/ah.py`.

**Version**: `0.8.4-beta` in `weekmenu/__init__.py`. Zichtbaar in de footer van elke pagina. Bump volgens semver-lite:
- **patch** (0.8.x): bugfixes zonder gedragsverandering
- **minor** (0.x.0): substantiële refactors, nieuwe features, kwaliteitssprongen
- **major** (x.0.0): incompatible schema-migraties of API-breuk (niet van toepassing zolang de app single-user is)

**Changelog**: bij elke versiebump een regel bovenaan `weekmenu/changelog.py`, in gewone taal voor wie de app gebruikt (wat merk je ervan, niet hoe het gebouwd is). Te zien op `/wat-is-er-nieuw`, gelinkt vanaf de instellingen. `tests/test_changelog.py` faalt als de huidige versie er niet bovenaan staat.

## Sleutels en secrets

- `SECRET_KEY`: env-var, of anders eenmalig gegenereerd in `data/secret_key` (0600).
- `GEMINI_API_KEY` / `VISION_API_KEY`: via `/settings` in de database, of env-var als fallback.
- AH-tokens: via `/settings → AH koppelen`, opgeslagen in `Settings`-tabel.

**Nooit** een sleutel in code hardcoden. **Nooit** een sleutel loggen; alle logregels lopen via `current_app.logger` en de app logt geen `Settings`-waarden.

## Service worker

`static/sw.js` wordt via Flask geserveerd (`routes/main.py::sw_js`), niet als statisch bestand. Bij opstart hasht `_bouw_sw_inhoud()` alle JS + sw.js zelf en zet dat in de `CACHE = 'weekmenu-<hex>'`-regel. Nieuwe container-start met gewijzigde JS = automatisch nieuwe cache-naam = oude cache verdwijnt via de `activate`-listener. Handmatige `weekmenu-vN`-ophoging is dus niet meer nodig.

## Wat wél en wat NIET

**Wél**:
- Kleine, gerichte commits met een Nederlandse commit-boodschap die uitlegt **wat** en **waarom**, niet **hoe**.
- Tests na elke commit — `python3 -m pytest -q` moet groen blijven.
- Verificatie op scenario's: kopieer de DB naar scratchpad en meet erop. Twee van de vier eerdere diagnoses werden door adversariële verificatie omvergegooid.
- Bij UI-wijzigingen: rebuild dev, open in de browser, klik het scenario door.

**Niet**:
- Schrijven naar `/pool/apps/weekmenu/live/data/weekmenu.db` buiten de app om.
- Force-push naar main.
- Cloud Vision / Gemini / AH-endpoints aanroepen tijdens tests (alles is gemockt).
- `.claude/`-worktrees weggooien zonder eerst `git worktree remove` te doen — dat maakt de git-metadata stuk.
- `Co-Authored-By: Claude`-lijnen in commits — Rutger houdt daar niet van.

## Waar de scherven van eerdere sessies liggen

- **Geheugen**: twee mappen, allebei met een eigen `MEMORY.md` als index. `~/.claude/projects/-pool-apps-weekmenu-planner/memory/` is het archief tot 13 sep 2026 (OCR-routekeuze, DB-schema-migraties, opruimingen); `~/.claude/projects/-pool-apps-weekmenu/memory/` is waar nieuwe sessies schrijven.
- **Scratchpad** (per sessie): tijdelijke metingen, database-backups met sha256, audit-rapporten. Nooit in git.
- **Landing-pagina**: `landing/` is untracked (opzettelijk). Rutgers eigen landing-experiment; buiten scope voor de app-refactor.

## Open gesprekspunten (uit de audit van 13 sep 2026)

Niet dringend, wel bekend:
1. **JS-extractie uit templates**: nog aan de gang tijdens deze commit. Zie de `static/js/`-map voor de status.
2. **CSRF-bescherming**: bewust uit (single-user), noteren voor als de app ooit meer gebruikers krijgt.
3. **Migratie-consolidatie**: v1..v14 kunnen samenklappen tot een baseline; dev en live staan op v20, cloudvision-backup op v14.
4. **AH-proxy** (`ah-proxy/proxy.py`): 172 regels ongetest reverse-proxy voor de Capsolver-login-flow. Eigen module, eigen tests waardig.
5. **Uploads-cleanup**: `static/uploads/dump/<uuid>/` wordt nooit opgeruimd — disk-groei per import-batch.
