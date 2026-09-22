# Handoff: Inspiratiepagina (Smart Chef / weekmenu-docker)

## Overview
Redesign van de Inspiratie-pagina: een redactionele, "magazine"-achtige pagina die seizoensingrediënten, ecobooster-matches en AH-bonusrecepten samenbrengt. Doel is de bestaande functionaliteit (Ecobooster + Seizoen) een rustiger, mooier en beter leesbaar jasje geven — zonder nieuwe datamodellen.

Doelrepo: `beninhos/weekmenu-docker` (Flask + Jinja + Tailwind CDN, single-user, self-hosted).

## About the Design Files
`Smart Chef - Inspiratie.html` in deze map is een **design-referentie, geen productiecode**. Het is een statische HTML-mockup die de bedoelde look & feel toont. De opdracht is om dit ontwerp te **hermaken in de bestaande omgeving van de repo**: Jinja-templates die `base.html` extenden, Tailwind-classes, en de CSS-variabelen die al in `base.html` staan. Niet de HTML kopiëren.

## Fidelity
**High-fidelity.** Kleuren, typografie, spacing en kaartopbouw zijn definitief bedoeld. De mockup is desktop-first op 1440px; de implementatie moet mobile-first werken zoals de rest van de app.

**Belangrijke afwijking:** de mockup toont een multi-user communityplatform (koks, ratings, volgers, prijzen per portie, meerdere supermarkten, seizoensindex 0–100). Die data bestaat **niet** in de huidige database. Zie "Wat wel/niet uit de DB komt" — implementeer alleen wat echt bestaat, en laat de rest weg in plaats van het met nepdata te vullen.

## Wat wel/niet uit de DB komt

**Wel beschikbaar (gebruiken):**
- Seizoenschips per maand — `resolve_seasonal_ingredients(month)` in `weekmenu/services/seasons.py`, met `matched`-vlag
- Recept-matching + score — `score_recipes(boost_ids, source)` in `weekmenu/services/recipe_matcher.py` geeft `eco_score` (0–100), `missing`, `missing_count`, `is_favorite`, `cookbook` (afkorting), `page`, `serves`
- Recipe-velden: `name`, `serves`, `image_path`, `is_favorite`, `usage_count`, `last_used`, `cookbook`, `page`, `url`
- AH-bonus op Ingredient: `ah_product_bonus`, `ah_product_price`, `ah_product_was_price`, `ah_product_bonus_mechanism`, `ah_product_image`

**Niet beschikbaar (weglaten, niet verzinnen):**
- Seizoensindex als getal (seizoen is binair: wel/niet in seizoen)
- Prijs per portie (units te onbetrouwbaar voor een eerlijke berekening)
- Koks, ratings, sterren van anderen, volgers, "X keer bewaard", collecties
- Jumbo / Picnic / Plus / Lidl / ALDI (alleen AH is geïntegreerd)
- Vegetarisch/veganistisch, bereidingstijd (velden bestaan niet op Recipe)

Waar de mockup zo'n element toont: laat het element vervallen. De layout moet zonder gaten werken.

## Screens / Views

### Inspiratie — tab "Seizoen"
**Purpose:** Zien welke Nederlandse groente/fruit nu in seizoen is, en welke recepten uit de eigen bibliotheek die ingrediënten gebruiken.

**Layout:**
- Container `max-w-5xl mx-auto`, padding `1rem`
- Hero-header, daarna tabbalk, daarna seizoenschips, daarna receptgrid
- Receptgrid: `grid-cols-1 md:grid-cols-2 lg:grid-cols-3`, `gap: 1.75rem`

**Components:**

*Hero-header*
- Eyebrow: mono/sans uppercase, `11px`, `letter-spacing: .14em`, kleur `--color-pencil` (#6B6B6B), met een `6px` rond bolletje in `--color-sepia` (#8B4513) ervoor
- Titel: Libre Baskerville (`--font-serif`), `44–56px` desktop / `30px` mobiel, `font-weight: 400`, `line-height: 1.05`, `letter-spacing: -0.02em`, kleur `--color-ink` (#2C2C2C)
- Lede: `15px`, `line-height: 1.6`, kleur `--color-pencil`, `max-width: 460px`
- Drie tellers, horizontaal met `gap: 2rem`. Waarde in serif `26px` kleur ink; label onder in uppercase `11px` `letter-spacing: .08em` kleur pencil. Echte waarden: totaal recepten, aantal favorieten, aantal recepten met een seizoensingrediënt.

*Tabbalk*
- Twee links: "Ecobooster", "Seizoen". Onderrand `1px solid var(--color-border)` over de volle breedte
- Actieve tab: bestaande `.nav-active` class (sepia tekst + sepia onderrand). Inactief: `.nav-link`
- Server-side state via `?tab=ecobooster` / `?tab=seizoen`

*Seizoenschips-blok*
- Kaart: achtergrond `--color-card` (#F5F2ED), `border: 1px solid --color-border` (#E8E4DC), `border-radius: 8px`, padding `1.5rem`
- Kop: "In seizoen — {{ month_name }}" in serif `22px`
- Chips: `border-radius: 999px`, padding `4px 12px`, `font-size: 12px`. Gematcht = achtergrond `--color-ink`, tekst `--color-paper`. Niet gematcht = wit met `1px solid --color-linen` (#D4CEC4), tekst #9B8A7A, plus `title`-tooltip "Niet gekoppeld aan een ingrediënt in de database"
- Chips in `display: flex; flex-wrap: wrap; gap: 0.5rem`

*Receptkaart (herbruikbaar — gedeeld door Seizoen, Ecobooster en Bonus)*
- Wrapper: `background: --color-paper`, `border: 1px solid --color-border`, `border-radius: 12px`, `overflow: hidden`. Hover: `border-color: --color-sepia-light` (#C9A882) + `background: #FAF8F5`
- Beeld: `aspect-ratio: 4/3`. Als `image_path` bestaat: de foto, `object-fit: cover`. Anders een placeholder-vlak in `--color-card` met een diagonale streeppatroon-overlay (`repeating-linear-gradient(45deg, rgba(0,0,0,.04) 0 1px, transparent 1px 14px)`) en de receptnaam klein en gecentreerd in kleur pencil
- Score-badge linksboven op het beeld: wit vlak, `1px solid --color-border`, `border-radius: 999px`, padding `5px 10px`, `font-size: 10px` uppercase `letter-spacing: .08em`. Tekst = `{{ eco_score }}%`. Kleur volgt de bestaande drempels: `>=75` → #4A7C59, `>=50` → #8B7A3A, anders #6B6B6B
- Body: padding `1rem 1.1rem`, `display: flex; flex-direction: column; gap: 0.4rem`
- Titel: serif `20px`, `line-height: 1.2`, kleur ink. Voorafgegaan door `★` in `--color-sepia-light` als `is_favorite`
- Bron-regel: `12px` kleur pencil — kookboek-afkorting, plus `· p.{{ page }}` als er een paginanummer is, plus `· {{ serves }} pers.` als bekend
- Statusregel: als `missing` leeg → "Alles in huis" in #4A7C59; anders "mist: {{ missing|join(', ') }}" in #9B8A7A, `12px`
- Hele kaart is een link naar `url_for('recipes.edit_recipe', id=r.id)` met `onclick="return openDetail(event, {{ r.id }})"` — zelfde patroon als nu

*Lege staat*
- Gecentreerde tekst `14px` kleur pencil, padding `2.5rem 0`: "Geen recepten gevonden die seizoens-ingrediënten gebruiken."

### Inspiratie — tab "Ecobooster"
**Purpose:** Ingrediënten invoeren die opgemaakt moeten worden, en matchende recepten vinden.

**Layout & components:** de bestaande flow blijft functioneel identiek — chip-input met autocomplete via `/api/ingredients/search`, "Zoek recepten" knop, POST naar `/api/ecobooster/match`. Alleen de **resultaatweergave** verandert: gebruik exact dezelfde receptkaart als de Seizoen-tab, in hetzelfde grid.

Het huidige "Voorraadkast"-blok hoort hier **niet** meer — dat is een eigen pagina (`/voorraad`).

### Optioneel: AH Bonus-strook
**Purpose:** Echte folder-data laten zien, als vervanging voor de verzonnen multi-supermarkt-badges in de mockup.

- Sectiekop boven de seizoensrecepten: serif `22px` "Deze week in de bonus", met subregel `13px` pencil "Recepten met een ingrediënt dat nu bij Albert Heijn in de bonus is"
- Zelfde receptgrid en kaarten, plus op de kaart een tweede badge rechtsboven met `ah_product_bonus_mechanism` als tekst (bijv. "2e halve prijs"), in `--color-sepia-bg` (#FDF8F3) met tekst `--color-sepia`
- Alleen renderen als er resultaten zijn; anders sectie volledig weglaten

## Interactions & Behavior
- Tabs: gewone links, server-side gerenderd, geen JS. `?tab=` bepaalt de actieve tab; default `ecobooster`
- Receptkaart klik: opent de bestaande detail-modal via `openDetail(event, id)`; valt terug op de edit-pagina zonder JS
- Kaart-hover: `transition: border-color .15s, background .15s`
- Ecobooster-zoeken: bestaande fetch-flow, resultaten vervangen de gridinhoud
- Autocomplete: bestaande `initChipInput` helper — debounce 200ms, pijltjestoetsen + Enter + Escape
- Responsive: 1 kolom mobiel, 2 vanaf `md`, 3 vanaf `lg`. Hero-titel schaalt terug naar `30px` mobiel

## State Management
Geen client-side state framework. Server-side:
- `active_tab` — uit `request.args.get('tab')`
- Seizoen: `month_name`, `items` (chips), `recipes`
- Ecobooster: `pantry` niet meer nodig hier; resultaten komen via fetch
- Bonus: `bonus_recipes` (nieuwe helper)

Nieuwe backend-helper (enige backend-wijziging): een functie die recepten teruggeeft met minstens één ingrediënt waarvoor `ah_product_bonus == True`. Plaats in `weekmenu/services/recipe_matcher.py`.

## Design Tokens
Gebruik de variabelen die al in `templates/base.html` staan — niet nieuwe kleuren introduceren.

| Token | Hex | Gebruik |
|---|---|---|
| `--color-ink` | #2C2C2C | Koppen, actieve chips |
| `--color-pencil` | #6B6B6B | Secundaire tekst, labels |
| `--color-sepia` | #8B4513 | Accent, actieve nav, links |
| `--color-sepia-light` | #C9A882 | Hover-randen, favoriet-sterren |
| `--color-sepia-bg` | #FDF8F3 | Bonus-badge achtergrond |
| `--color-linen` | #D4CEC4 | Inputranden, inactieve chips |
| `--color-paper` | #FAF8F5 | Pagina- en kaartachtergrond |
| `--color-card` | #F5F2ED | Blokachtergrond, placeholders |
| `--color-border` | #E8E4DC | Randen |

Score-kleuren (bestaande drempels, niet wijzigen): #4A7C59 (≥75), #8B7A3A (≥50), #6B6B6B (rest). Ontbrekend-tekst: #9B8A7A.

**Typografie:** `--font-serif` = Libre Baskerville (koppen, recepttitels, weight 400). `--font-sans` = Inter (body, labels). Schaal: hero 44–56px / sectiekop 22px / recepttitel 20px / body 14px / meta 12px / eyebrow-label 11px uppercase.

**Spacing:** 4px-basis. Kaartpadding 1rem–1.5rem, gridgap 1.75rem, sectiemarge 2.5–4rem.

**Radius:** 8px blokken, 12px receptkaarten, 999px chips en badges.

**Shadows:** geen. De stijl leunt op randen, niet op schaduw.

## Assets
- `assets/favicon.svg` — het logo (schaal-glyph), al aanwezig in de repo als `static/favicon-light.svg`
- Geen andere assets nodig. Receptfoto's komen uit `image_path`; ontbrekende foto's krijgen de gestreepte CSS-placeholder (geen afbeeldingsbestand nodig)

**Aanbeveling:** de grootste visuele winst zit in het consequent vullen van `image_path`. Zonder foto's blijft de pagina placeholder-zwaar, hoe goed de layout ook is.

## Files
- `Smart Chef - Inspiratie.html` — de design-referentie (desktop, 1440px)
- `assets/favicon.svg` — logo

In de doelrepo aan te passen/maken:
- `templates/inspiratie.html` — shell met hero + tabbalk
- `templates/_inspiratie_ecobooster.html` — partial, resultaten in nieuwe kaartstijl
- `templates/_inspiratie_seizoen.html` — partial, chips + receptgrid
- `templates/_recipe_card.html` — nieuw, herbruikbare receptkaart (Jinja-macro of include)
- `weekmenu/services/recipe_matcher.py` — bonus-helper toevoegen
