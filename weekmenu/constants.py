import re

# ── Dagen & maaltijden ────────────────────────────────────────────────────

DAYS = [
    (0, 'Maandag'),
    (1, 'Dinsdag'),
    (2, 'Woensdag'),
    (3, 'Donderdag'),
    (4, 'Vrijdag'),
    (5, 'Zaterdag'),
    (6, 'Zondag')
]

MEAL_TYPES = [
    ('ontbijt', 'Ontbijt'),
    ('lunch', 'Lunch'),
    ('diner', 'Diner')
]

# ── Productcategorieën ────────────────────────────────────────────────────

PRODUCT_CATEGORIES = [
    'Groente, Fruit & Aardappelen',
    'Vlees & Gevogelte',
    'Vis & Schaaldieren',
    'Vegetarisch & Plantaardig',
    'Zuivel, Plantaardige Zuivel & Eieren',
    'Kaas & Vleeswaren',
    'Kruiden & Specerijen',
    'Oliën, Sauzen & Smaakmakers',
    'Pasta, Rijst & Granen',
    'Conserven & Peulvruchten',
    'Noten, Zaden & Gedroogd Fruit',
    'Brood & Bakkerij',
    'Ontbijt, Bakken & Desserts',
    'Diepvries',
    'Dranken',
    'Snacks & Zoetwaren',
    'Non-Food & Huishouden',
    'Overig',
]

CATEGORY_ORDER_SUPERMARKET = [
    'Groente, Fruit & Aardappelen',
    'Vlees & Gevogelte',
    'Vis & Schaaldieren',
    'Vegetarisch & Plantaardig',
    'Kaas & Vleeswaren',
    'Zuivel, Plantaardige Zuivel & Eieren',
    'Kruiden & Specerijen',
    'Oliën, Sauzen & Smaakmakers',
    'Pasta, Rijst & Granen',
    'Conserven & Peulvruchten',
    'Noten, Zaden & Gedroogd Fruit',
    'Brood & Bakkerij',
    'Ontbijt, Bakken & Desserts',
    'Snacks & Zoetwaren',
    'Dranken',
    'Diepvries',
    'Non-Food & Huishouden',
    'Overig',
]

CATEGORY_BG = {
    'Groente, Fruit & Aardappelen':           '#fef9f5',
    'Vlees & Gevogelte':                       '#f5f0eb',
    'Vis & Schaaldieren':                      '#f0ede8',
    'Vegetarisch & Plantaardig':               '#fef9f5',
    'Zuivel, Plantaardige Zuivel & Eieren':    '#fdf6f0',
    'Kaas & Vleeswaren':                       '#f5f0eb',
    'Kruiden & Specerijen':                    '#fef9f5',
    'Oliën, Sauzen & Smaakmakers':            '#fdf6f0',
    'Pasta, Rijst & Granen':                   '#f0ede8',
    'Conserven & Peulvruchten':                '#f5f0eb',
    'Noten, Zaden & Gedroogd Fruit':           '#fdf6f0',
    'Brood & Bakkerij':                        '#fef9f5',
    'Ontbijt, Bakken & Desserts':              '#f5f0eb',
    'Diepvries':                               '#ede9e3',
    'Dranken':                                 '#f0ede8',
    'Snacks & Zoetwaren':                      '#fdf6f0',
    'Non-Food & Huishouden':                   '#ede9e3',
    'Overig':                                  '#f0ede8',
}

# ── AH verpakkings-eenheden ──────────────────────────────────────────────

_SIZE_UNIT_MAP = {
    'gram': 'g', 'gr': 'g', 'g': 'g',
    'kilogram': 'kg', 'kilo': 'kg', 'kg': 'kg',
    'liter': 'l', 'litre': 'l', 'l': 'l',
    'milliliter': 'ml', 'ml': 'ml',
    'cl': 'cl', 'dl': 'dl',
    'stuks': 'stuks', 'stuk': 'stuks', 'st': 'stuks',
    'bollen': 'bol', 'bol': 'bol',
    'teen': 'teen', 'tenen': 'teen',
    'bosje': 'bosje', 'bos': 'bosje',
    'plak': 'plak', 'plakken': 'plak',
    'pakje': 'pakje', 'pak': 'pak',
}

# ── Unit normalisatie ────────────────────────────────────────────────────

_UNIT_NORMALIZE = {
    'gram': 'g', 'gr': 'g',
    'kilogram': 'kg', 'kilo': 'kg',
    'liter': 'l', 'litre': 'l',
    'milliliter': 'ml',
    'eetlepel': 'el', 'eetlepels': 'el',
    'theelepel': 'tl', 'theelepels': 'tl',
    'stuk': 'stuks', 'st': 'stuks',
    'bollen': 'bol', 'tenen': 'teen', 'teentjes': 'teen', 'teentje': 'teen',
    'bos': 'bosje', 'tros': 'bosje',
    'plakken': 'plak', 'plakje': 'plak', 'plakjes': 'plak',
    'takjes': 'takje', 'takken': 'takje',
    'stengels': 'stengel', 'stelen': 'steel',
    'blad': 'blad', 'blaadjes': 'blad', 'blaadje': 'blad', 'bladeren': 'blad',
    'blikje': 'blik', 'blikjes': 'blik',
    'blokjes': 'blokje',
}

_UNIT_CONVERSIONS = {
    ('g', 'kg'): 0.001, ('kg', 'g'): 1000,
    ('ml', 'l'): 0.001, ('l', 'ml'): 1000,
    ('cl', 'l'): 0.01,  ('dl', 'l'): 0.1,
    ('cl', 'ml'): 10,   ('dl', 'ml'): 100,
}

_UNIT_BUY_ONE = {
    'g', 'gr', 'gram',
    'kg', 'kilogram', 'kilo',
    'ml', 'cl', 'dl', 'l', 'liter', 'litre',
    'el', 'eetlepel', 'eetlepels',
    'tl', 'theelepel', 'theelepels',
    'mespunt', 'snuf', 'snufje', 'scheutje', 'scheut', 'toef',
    'cm', 'mm',
    'takje', 'stengel', 'steel', 'blad', 'handvol',
}

# ── Dutch units (ingrediënt parsing) ─────────────────────────────────────

DUTCH_UNITS = {
    'el': 'el', 'eetlepel': 'el', 'eetlepels': 'el',
    'tl': 'tl', 'theelepel': 'tl', 'theelepels': 'tl',
    'kl': 'kl', 'koffielepel': 'kl', 'koffielepels': 'kl',
    'dl': 'dl', 'deciliter': 'dl',
    'ml': 'ml', 'milliliter': 'ml',
    'l': 'l', 'liter': 'l', 'liters': 'l',
    'g': 'g', 'gr': 'g', 'gram': 'g', 'grams': 'g',
    'kg': 'kg', 'kilogram': 'kg',
    'stuks': 'stuks', 'stuk': 'stuks',
    'snuf': 'snufje', 'snufje': 'snufje', 'snufjes': 'snufje',
    'scheutje': 'scheutje', 'scheut': 'scheutje',
    'teen': 'teen', 'tenen': 'teen',
    'blik': 'blik', 'blikje': 'blik',
    'pakje': 'pakje', 'pak': 'pakje', 'zakje': 'zakje',
    'bosje': 'bosje', 'bos': 'bosje',
    'plak': 'plak', 'plakken': 'plak',
    'bol': 'bol', 'bollen': 'bol',
    'takje': 'takje', 'takjes': 'takje',
    'blaadje': 'blaadje', 'blaadjes': 'blaadje',
    'cup': 'cup', 'cups': 'cup',
    'tablespoon': 'el', 'tablespoons': 'el', 'tbsp': 'el', 'tbs': 'el',
    'teaspoon': 'tl', 'teaspoons': 'tl', 'tsp': 'tl',
    'pound': 'pond', 'pounds': 'pond', 'lb': 'pond', 'lbs': 'pond',
    'ounce': 'oz', 'ounces': 'oz',
    'clove': 'teen', 'cloves': 'teen',
    'bunch': 'bosje', 'handful': 'handvol', 'pinch': 'snufje', 'dash': 'scheutje',
    'can': 'blik', 'slice': 'plak', 'slices': 'plak',
    'piece': 'stuks', 'pieces': 'stuks',
}

# ── Ingredient parsing regex patterns ────────────────────────────────────

_UNIT_KEYS = '|'.join(re.escape(k) for k in sorted(DUTCH_UNITS.keys(), key=len, reverse=True))
_AMOUNT_RE = r'(?:[\d]+(?:[,.][\d]+)?(?:\s*[-–]\s*[\d]+(?:[,.][\d]+)?)?|[½¼¾⅓⅔⅛⅜⅝⅞]|\d+\s*/\s*\d+|\d+\s+\d+\s*/\s*\d+)'
_INGREDIENT_RE = re.compile(
    r'^(' + _AMOUNT_RE + r')\s+(' + _UNIT_KEYS + r')\b\.?\s+(.+)$',
    re.IGNORECASE
)
_AMOUNT_ONLY_RE = re.compile(
    r'^(' + _AMOUNT_RE + r')\s+(.+)$'
)

# ── Category guesser keywords ────────────────────────────────────────────

_CATEGORY_KEYWORDS = [
    ('Groente, Fruit & Aardappelen', ['vleestomaat', 'vleestomaten', 'bladspinazie', 'sperziebonen', 'sperzieboon', 'winterpeen', 'winterpenen', 'puntpaprika', 'bosui', 'bosuitje', 'bleekselderij', 'augurk', 'casave', 'cassave']),
    ('Oliën, Sauzen & Smaakmakers', ['satésaus', 'sesamolie', 'ahornsiroop', 'boemboe', 'jus', 'saus']),
    ('Ontbijt, Bakken & Desserts', ['maizena', 'maïzena', 'zelfrijzend']),
    ('Brood & Bakkerij', ['volkoren bolletje', 'bolletje', 'papadum', 'chapati', 'wraps']),
    ('Kaas & Vleeswaren', ['ontbijtspek', 'ontbijtspekje', 'burrata']),
    ('Pasta, Rijst & Granen', ['basmatirijst', 'zilvervliesrijst', 'zilvervlies', 'conchiglie', 'bami goreng', 'nasi goreng', 'papadums']),
    ('Dranken', ['bronwater', 'kraanwater']),
    ('Vlees & Gevogelte', ['kipfilet', 'kippendij', 'kip', 'gehakt', 'varkensvlees', 'varken', 'rundvlees', 'rund', 'lamsrack', 'lam', 'biefstuk', 'tartaar', 'ossenhaas', 'entrecote', 'speklap', 'kalkoen', 'eend', 'konijn', 'wild', 'hert', 'klapstuk', 'riblap', 'cordon bleu', 'saté ajam', 'saté', 'vlees']),
    ('Vis & Schaaldieren', ['zalm', 'tonijn', 'vis', 'garnaal', 'mossel', 'inktvis', 'forel', 'haring', 'makreel', 'ansjovis', 'kabeljauw', 'tilapia', 'kreeft', 'krab', 'schol', 'sardine', 'zeebaars', 'dorade', 'paling', 'sint-jakobsschelp']),
    ('Vegetarisch & Plantaardig', ['tofu', 'tempeh', 'tahoe', 'seitan', 'quorn', 'soja', 'lupine']),
    ('Kaas & Vleeswaren', ['kaas', 'parmezaan', 'mozzarella', 'feta', 'ricotta', 'mascarpone', 'grana', 'pecorino', 'emmentaler', 'gorgonzola', 'brie', 'camembert', 'cheddar', 'gouda', 'edam', 'gruyère',
                           'ham', 'salami', 'rookworst', 'cervelaat', 'leverworst', 'worst', 'chorizo', 'pancetta', 'prosciutto', 'spek', 'bacon', 'rookvlees', 'pastrami']),
    ('Zuivel, Plantaardige Zuivel & Eieren', ['slagroom', 'karnemelk', 'volle melk', 'melk', 'yoghurt', 'kwark', 'boter', 'margarine', 'crème fraîche', 'fromage frais', 'zure room', 'room', 'ei', 'quark',
                                               'kokosmelk', 'amandelmelk', 'havermelk', 'sojamelk']),
    ('Kruiden & Specerijen', ['paprikapoeder', 'chilipoeder', 'komijn', 'kaneel', 'kurkuma', 'oregano', 'laurier', 'nootmuskaat', 'kardemom', 'kruidnagel', 'steranijs', 'kerrie', 'curry', 'ras el hanout', 'five spice', 'za\'atar', 'sumak', 'garam', 'massala', 'zout', 'peper', 'italiaanse kruiden', 'kruiden',
                              'peterselie', 'basilicum', 'rozemarijn', 'tijm', 'bieslook', 'dragon', 'koriander', 'munt', 'salie', 'dille']),
    ('Oliën, Sauzen & Smaakmakers', ['tomatenpuree', 'olijfolie', 'zonnebloemolie', 'koolzaadolie', 'bouillon', 'fond', 'soep', 'ketchup', 'mosterd', 'mayonaise', 'sojasaus', 'ketjap', 'worcester', 'tabasco', 'pesto', 'sambal', 'harissa', 'hoisin', 'misopasta', 'tahini', 'honing', 'siroop', 'stroop', 'azijn', 'olie']),
    ('Pasta, Rijst & Granen', ['spaghetti', 'penne', 'rigatoni', 'fusilli', 'lasagne', 'tagliatelle', 'fettuccine', 'noodle', 'noedel', 'couscous', 'bulgur', 'quinoa', 'polenta', 'gnocchi', 'tortellini', 'ravioli', 'macaroni', 'pasta', 'rijst', 'risotto', 'mie', 'orzo']),
    ('Conserven & Peulvruchten', ['tomatenblokje', 'tomatenstukje', 'passata', 'kikkererwt', 'linzen', 'linze', 'bruine bonen', 'witte bonen', 'kidneybonen', 'kidney', 'zwarte bonen', 'chili boon', 'bonen', 'olijf']),
    ('Noten, Zaden & Gedroogd Fruit', ['amandel', 'walnoot', 'cashew', 'hazelnoot', 'pistache', 'pijnboompit', 'sesamzaad', 'lijnzaad', 'chiazaad', 'zonnebloempit', 'pompoenpit', 'rozijn', 'cranberry', 'sultana', 'gedroogd fruit', 'dadel', 'pinda']),
    ('Brood & Bakkerij', ['stokbrood', 'ciabatta', 'baguette', 'croissant', 'focaccia', 'brioche', 'tortilla', 'pitabrood', 'naan', 'brood']),
    ('Ontbijt, Bakken & Desserts', ['bloem', 'zelfrijzend', 'bakpoeder', 'maizena', 'gist', 'baksoda', 'vanille', 'vanillesuiker', 'amandelpoeder', 'amandelmeel', 'suiker', 'poedersuiker', 'basterdsuiker', 'rietsuiker', 'cacaopoeder', 'cacao', 'paneermeel',
                                    'jam', 'marmelade', 'pindakaas', 'notenpasta', 'hagelslag', 'vlokken', 'muesli', 'havermout', 'granola', 'cornflakes']),
    ('Snacks & Zoetwaren', ['chocolade', 'pure chocolade', 'melkchocolade', 'witte chocolade', 'koek', 'stroopwafel', 'biscuit', 'marshmallow', 'chips', 'popcorn', 'snoep', 'kroepoek']),
    ('Dranken', ['koffie', 'espresso', 'thee', 'groene thee',
                 'limonade', 'cola', 'spa', 'mineraalwater', 'appelsap', 'sinaasappelsap', 'tomatensap', 'water',
                 'wijn', 'rode wijn', 'witte wijn', 'rosé', 'bier', 'cognac', 'rum', 'wodka', 'gin', 'whisky', 'port', 'marsala', 'sherry', 'champagne', 'prosecco', 'likeur', 'calvados', 'armagnac']),
    ('Diepvries', ['diepvries', 'ingevroren', 'bevroren']),
    ('Groente, Fruit & Aardappelen', ['ui', 'rode ui', 'sjalot', 'knoflook', 'wortel', 'aardappel', 'zoete aardappel', 'bataat', 'prei', 'courgette', 'paprika', 'paparika', 'champignon', 'paddenstoel', 'shiitake', 'broccoli', 'bloemkool', 'romanesco', 'spinazie', 'komkommer', 'tomaat', 'tomaten', 'tomat', 'venkel', 'asperge', 'doperwt', 'erwt', 'biet', 'radijs', 'spruitje', 'kool', 'rode kool', 'witlof', 'paksoi', 'aubergine', 'chilipeper', 'gember', 'andijvie', 'sla', 'ijsbergsla', 'selderij', 'knolselderij', 'pastinaak', 'rettich', 'raap', 'avocado', 'peen', 'groente', 'mais', 'maïs', 'palmhart', 'radicchio', 'rucola', 'rucolo', 'waterkers',
                                      'appel', 'peer', 'citroen', 'limoen', 'sinaasappel', 'mandarijn', 'grapefruit', 'banaan', 'banan', 'aardbei', 'framboos', 'blauwe bes', 'bosbes', 'braambes', 'kiwi', 'mango', 'ananas', 'papaja', 'passievrucht', 'granaatappel', 'pruim', 'kers', 'abrikoos', 'perzik', 'nectarine', 'vijg', 'meloen', 'watermeloen', 'lychee', 'kokos', 'artisjok']),
]

# ── AH API constanten ────────────────────────────────────────────────────

_AH_LOGIN_BASE       = 'https://login.ah.nl'
_AH_AUTHORIZE_PATH   = '/secure/oauth/authorize?client_id=appie&redirect_uri=appie%3A%2F%2Flogin-exit&response_type=code'
_AH_ANON_TOKEN_URL   = 'https://api.ah.nl/mobile-auth/v1/auth/token/anonymous'
_AH_TOKEN_URL        = 'https://api.ah.nl/mobile-auth/v1/auth/token'
_AH_REFRESH_URL      = 'https://api.ah.nl/mobile-auth/v1/auth/token/refresh'
_AH_SEARCH_URL       = 'https://api.ah.nl/mobile-services/product/search/v2'
_AH_SHOPPINGLIST_URL = 'https://api.ah.nl/mobile-services/shoppinglist/v2/items'
_AH_HEADERS          = {'User-Agent': 'Appie/8.22.3', 'x-application': 'AHWEBSHOP'}

_AH_CAPTCHA_SITEKEY = '617563f1-54b0-496d-a13d-95de4a9c641a'
_AH_CAPTCHA_PAGE    = 'https://login.ah.nl/login'

# ── Web scraping ─────────────────────────────────────────────────────────

_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7',
    'DNT': '1',
}

_KNOWN_SITES = {
    'jumbo.com': 'Jumbo',
    'ah.nl': 'Albert Heijn',
    'allerhande.nl': 'Albert Heijn',
    'leukerecepten.nl': 'Leuke Recepten',
    '15gram.nl': '15GRAM',
    'culy.nl': 'Culy',
    'smulweb.nl': 'Smulweb',
    'njam.tv': 'Njam!',
    'recepten.nl': 'Recepten.nl',
    'kookmutsjes.nl': 'Kookmutsjes',
    'lekkerensimpel.nl': 'Lekker en Simpel',
    'margriet.nl': 'Margriet',
    'libelle.nl': 'Libelle',
    'jamieoliver.com': 'Jamie Oliver',
    'bbcgoodfood.com': 'BBC Good Food',
    'allrecipes.com': 'Allrecipes',
    'epicurious.com': 'Epicurious',
    'foodnetwork.com': 'Food Network',
}
