"""Wat er per versie veranderde, in gewone taal. Nieuwste bovenaan.

Getoond op /wat-is-er-nieuw (link op de instellingenpagina). Bij elke
versiebump in weekmenu/__init__.py komt hier een regel bij;
tests/test_changelog.py faalt als dat vergeten is. Schrijf voor wie de app
gebruikt: wat merk je ervan, niet hoe het gebouwd is.
"""

WIJZIGINGEN = [
    {
        'versie': '0.8.5-beta',
        'datum': '12 oktober 2026',
        'titel': 'Boodschappen naar je Picnic-mand',
        'punten': [
            'Koppel je eigen Picnic-account in de instellingen (e-mail, wachtwoord en de '
            'code die Picnic per sms of e-mail stuurt). Je wachtwoord wordt niet bewaard.',
            'Kies als uitgang "Naar je Picnic-mand": de knop op de boodschappenpagina zoekt '
            'elk ingrediënt op naam bij Picnic en zet de eerste treffer in je mand. De '
            'melding daarna laat per regel zien wat het werd; wat niet gevonden is blijft open.',
            'Wat er na het versturen in je Picnic-mand staat, komt in het bestel-log als '
            '"picnic-mand": een mand is nog geen bestelling.',
        ],
    },
    {
        'versie': '0.8.4-beta',
        'datum': '12 oktober 2026',
        'titel': 'Kies waar je boodschappenlijst heen gaat',
        'punten': [
            'In de instellingen kies je wat de knop op de boodschappenpagina doet: '
            'naar je gekoppelde AH-account sturen, je lijst openen op ah.nl zonder '
            'koppeling, of niet versturen en alleen printen.',
            'Kies je ah.nl, dan krijg je een link naar je AH-lijst met de producten '
            'erop; bij meer dan 25 producten een paar links, die je één voor één opent. '
            'Tik daarna op Klaar: pas dan worden ze op je lijst hier afgevinkt.',
        ],
    },
    {
        'versie': '0.8.3-beta',
        'datum': '10 oktober 2026',
        'titel': 'Afgevinkt blijft afgevinkt',
        'punten': [
            'Voeg je iets toe (een recept plannen, + Recept, + Los item of meer '
            'personen), dan komt alleen de nieuwe hoeveelheid op de boodschappenlijst. '
            'Wat je al had afgevinkt of weggehaald, blijft dat.',
            'Staat een recept al als los recept op je lijst en kies je het opnieuw, '
            'dan vraagt de app of het dezelfde maaltijd is. Zo komt het niet per '
            'ongeluk dubbel op je lijst.',
            'Wat je met ✕ weghaalt, staat onderaan bij Afgevinkt. Met Terugzetten '
            'komt het weer op de lijst.',
            'Afgevinkt toont alleen de laatste 14 dagen, met de hoeveelheid die je '
            'toen afvinkte.',
            'Maak je een recept groter, dan komt er niets extra op de lijst van wat '
            'je al gekocht hebt. Een ingrediënt dat nieuw in het recept komt wel.',
            'Een vinkje uitzetten haalt geen oude weken meer terug op de lijst.',
            'Een los item in een andere eenheid (eerst stuks, dan gram) telt niet '
            'meer verkeerd op.',
            'Nieuw: deze pagina, met wat er per versie veranderd is.',
        ],
    },
    {
        'versie': '0.8.2-beta',
        'datum': '4 oktober 2026',
        'titel': 'Recept bewerken',
        'punten': [
            'Een recept bewerken zet niets meer terug op de boodschappenlijst wat je '
            'al had afgevinkt of weggehaald.',
        ],
    },
    {
        'versie': '0.8.1-beta',
        'datum': '4 oktober 2026',
        'titel': 'Nieuw recept werkt weer',
        'punten': [
            'Ingrediënten toevoegen bij een nieuw recept, importeren via een link en '
            'Aanpassen vanuit de foto-dump gaven een fout. Dat werkt weer.',
        ],
    },
    {
        'versie': '0.8.0-beta',
        'datum': '4 oktober 2026',
        'titel': 'Lopende weken en bestellingen',
        'punten': [
            'Een recept toevoegen via + Recept komt op de boodschappenlijst, ook als '
            'je die ingrediënten die week al had afgevinkt.',
            'Weken die voorbij zijn tellen niet meer mee op de boodschappenlijst.',
            'De app onthoudt per week wat je bij de AH bestelde.',
        ],
    },
]
