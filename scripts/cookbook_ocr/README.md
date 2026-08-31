# cookbook_ocr — ingrediëntenlijsten uit een gefotografeerde kookboekpagina

Leest de ingrediëntenlijst van een kookboekpagina met Tesseract: de losse regels,
met de blokkoppen als scheiding, zonder ingemengde bereidingstekst, en met de
breuktekens intact.

```bash
python3 scripts/cookbook_ocr static/uploads/dump/<job>/000.pdf --page 2
```

```
Rijst
  1 mok (300 g) snelkookzilvervlies- of basmatirijst
  ½ bosje verse tijm
  200 g jonge bladspinazie

Zuur
  2 kleine rode uien
  ...
```

`--json` geeft `{"blocks": [{"header": ..., "lines": [...]}]}`, `--debug` zet op
stderr welke kolommen gevonden zijn en welke glyphs als breukteken zijn
bijgesteld. Een losse afbeelding mag ook in plaats van een pdf; `--page` geldt
alleen voor een pdf.

## Benodigdheden

`pypdfium2` en `Pillow` staan al in `requirements.txt`. Daarnaast:

```bash
sudo apt install tesseract-ocr tesseract-ocr-nld
pip install pytesseract opencv-python-headless
```

Die twee pip-pakketten staan bewust niet in `requirements.txt`: dit is een
losstaand script en opencv hoort niet zomaar in het app-image. De app-container
heeft tesseract en opencv dan ook niet; wie dit in de app wil gebruiken moet ze
aan de `Dockerfile` en aan `requirements.txt` toevoegen.

## Hoe het werkt

**Eerste pas — waar staat wat.** Tesseract met `--psm 3` over de hele pagina,
puur voor de layout. Zijn blokken worden op horizontale overlap tot kolommen
samengevoegd. De ingrediëntenkolom is de kolom waarvan de meeste regels met een
hoeveelheid beginnen: op de testpagina 0,67 tegen 0,00 voor de bereidingstekst.
Elke kolom wordt eerst in verticale groepen geknipt, zodat het paginanummer
onderaan er vanzelf afvalt.

Wat er van de kolom afvalt — een paginavoet, een blok dat te klein is om een
lijst te zijn — verdwijnt niet stilzwijgend maar komt in `weggelaten` terecht, en
met `--debug` op je scherm. Een paginavoet is aan de witruimte erboven niet te
herkennen (op pagina 14 staat hij op 2,03 maal de regelafstand en de blokkoppen
op 2,00 tot 2,07); wat hem verraadt is dat hij in de paginamarge staat, links van
de tekstkolom: x=91 tegen x=116 voor de ingrediënten.

Waar de goot tussen twee kolommen smal is voegt Tesseract ze soms samen. Dat
wordt achteraf gerepareerd door de kolom te knippen op lege verticale corridors:
plekken waar over de volle hoogte geen enkel woord overheen loopt. Gemeten over
vijf pagina's waar de layoutanalyse het goed deed bevat geen enkele juiste kolom
zo'n corridor van 0,4 letterhoogte of breder; op de pagina waar het misging zit
er precies één, van 1,35. De drempel staat op 0,5 en de reparatie verandert dus
niets aan een kolom die al klopt.

**Tweede pas — wat staat er.** Alleen die kolom nog eens door Tesseract, als los
beeld. Dat is de belangrijkste ingreep in de hele pijplijn. Met de bereidingstekst
uit beeld leest Tesseract de smalle kolom schoon; in één pas over de hele pagina
verzint hij op de plek van het breukteken losse letters en plakt hij regels uit
beide kolommen aan elkaar.

**Regels opbouwen.** Binnen de kolom komt de regelindeling van Tesseract zelf
(blok-, alinea- en regelnummer). Dat is steviger dan zelf clusteren op verticale
overlap van de bboxen: woorden met en zonder staartletters hebben nogal
verschillende bboxen, en dan raken twee opeenvolgende regels elkaar al gauw.

**Blokkoppen.** De koppen (*Rijst*, *Zuur*, *Stroganoff*) zijn cursief. De
schuinstand van een regel meten we door het knipsel over een reeks hoeken te
scheren en de hoek te houden waar de verticale projectie het scherpst piekt. De
rechte regels bepalen zelf de nullijn, dus dit werkt ook bij een scheve scan.
Gemeten: koppen 14 tot 18 graden boven de nullijn, gewone regels hooguit 7. Een
minder uitgesproken cursief telt ook mee als er duidelijk extra witruimte boven
staat — Lato-Italic haalt bijvoorbeeld maar 7 graden. Een regel die met een
hoeveelheid begint is nooit een kop.

**Omgeslagen regels.** Een vervolgregel springt in ten opzichte van de regel waar
het ingrediënt begon — niet ten opzichte van één linkermarge voor de hele kolom.
Dat onderscheid is nodig: het papier ligt bol, en op pagina 8 schuift de
linkerkant daardoor van x=124 bovenaan naar x=101 onderaan. Tegen één vaste marge
zou de halve kolom ingesprongen lijken en aan elkaar geplakt worden.

## Het breukteken

**Geen enkel Tesseract-model kan `½` schrijven.** Het teken staat niet in de
unicharset van `nld`, `eng` of het `Latin`-scriptmodel — niet in de versie van
Ubuntu, niet in `tessdata_best`, niet in `tessdata`. Na te gaan met:

```bash
combine_tessdata -u /usr/share/tesseract-ocr/5/tessdata/nld.traineddata /tmp/nld.
grep -cP '^½ ' /tmp/nld.lstm-unicharset   # 0
```

Die unicharsets tellen 151 (nld), 112 (eng) en 303 (Latin) tekens, en `½ ¼ ¾`
zitten in geen ervan. Een andere taal, een ander model, een andere `--psm` of een
hogere resolutie verandert daar niets aan: Tesseract kiest onvermijdelijk het
dichtstbijzijnde teken dat het wél kent. Welk teken dat is hangt van de omgeving
af — in deze ene pdf zagen we `½` terugkomen als `%`, als `Y`, als `M`, als `W`
en als het tekenpaar `Ya`, en `¼` als `4`. Herstellen kan dus alleen door de
pixels opnieuw te bekijken.

Dat gebeurt in `breuken.py`, met twee signalen:

* **Topologie.** `%` bestaat uit twee gesloten rondjes en heeft dus twee gaten,
  `½` bestaat uit een 1, een schuine streep en een 2 en heeft er nul, `¼` en `¾`
  hebben er één. Getest op alle systeemfonts: klopt zonder uitzondering, en het
  overleeft blur en ruis veel beter dan enige vormvergelijking.
* **Vorm.** Het genormaliseerde silhouet wordt vergeleken met datzelfde teken uit
  alle systeemfonts. Het alfabet bevat naast de breuken ook alle cijfers en
  letters, zodat de uitkomst "dit is gewoon een 4" óók mogelijk is. Alleen als
  een breukteken als beste uit het hele alfabet komt, én met een duidelijke
  voorsprong op de beste niet-breuk, grijpen we in.
Welke glyphs worden voorgelegd: de eerste twee tekens van het eerste woord van
elke regel, mits dat woord hooguit drie tekens telt (`½`, `1½`, `½-1`), en mits
de glyph zo hoog is als een cijfer in dezelfde kolom. Plus elke glyph die
Tesseract als `%` las, waar in de regel ook. Beide eisen zijn nodig: zonder de
woordlengte wordt de `w` van *worcestersaus* een kandidaat, en die haalde in de
proef inderdaad een hogere score voor `½` dan voor `w`.

Elke verdachte glyph wordt uit de pdf opnieuw gerenderd tot hij veertig pixels
hoog is (`bron.py`). Dat is niet hetzelfde als opschalen: er komt echte
detailinformatie bij. Dat is nodig omdat onder de twintig pixels de rondjes van
een `%` dichtlopen en de topologie nul gaten telt — dan gaat een procentteken op
een breuk lijken. Gemeten over de systeemfonts verliest een `%` van 12 px in vijf
van de 26 fonts zijn topologie, van 14 px in twee, en vanaf 30 px in geen enkele.
Bij een losse afbeelding kan er niet hergerenderd worden; een glyph onder de
twintig pixels wordt daar dan ook niet beoordeeld en de lezing van Tesseract
blijft staan.

Maakt Tesseract van één breukglyph twee tekens (`Ya` voor `½`), dan liggen hun
bboxen over elkaar heen, want ze beschrijven dezelfde inkt. Alle tekens die de
herkende glyph overlappen verdwijnen daarom mee.

Een blinde vervanging `%` → `½` zou hier fout zijn: er staan legitieme percentages
in kookboeken (*melk 3,5%*). De correctie hangt daarom niet aan het teken maar
aan de pixels, en `test_geen_breuk_verzonnen` controleert over alle systeemfonts
dat een echt procentteken, elk cijfer en de letters `w M Y V` nooit een breuk
worden.

## Gemeten

Op de testpagina (`--page 2`, de derde pagina van de pdf), tegen een handmatig
geverifieerde meetlat van 15 ingrediëntregels:

| | |
|---|---|
| letterlijk correcte regels | **15/15** |
| `½` correct gelezen | **ja** |
| blokkoppen herkend | **3/3** (Rijst, Zuur, Stroganoff) |
| ingemengde bereidingstekst | **0 regels** |

Ter vergelijking, kale Tesseract op een handmatig bijgesneden boekpagina, met
dezelfde meetlat:

| aanpak | correcte regels | ingemengd | `½` |
|---|---|---|---|
| `--psm 4` (de uitgangsmeting) | 1/15 | 24 regels | nee |
| `--psm 6` | 0/15 | 40 regels | nee |
| `--psm 3` | 11/15 | 31 regels | nee |
| deze pijplijn | 15/15 | 0 regels | ja |

Over alle veertien pagina's van dezelfde pdf wordt op elke pagina de
ingrediëntenkolom gevonden en gescheiden van de bereidingstekst; het aandeel
regels dat met een hoeveelheid begint ligt daar tussen 0,55 en 0,80 tegen 0,00 en
0,09 voor de bereidingskolom. Alle acht paginavoeten worden herkend en gemeld.
Op die veertien pagina's staan achttien breuktekens; zestien daarvan worden
hersteld — uit een `%`, een `4`, een `Y` en een `a` — zonder één valspositief. De
twee missers staan hieronder bij "wat het niet kan".

Hoe ver het houdt, gemeten op dezelfde meetlat met bewerkte varianten van de
testpagina:

| variant | correcte regels |
|---|---|
| schaal 4, 5 of 6 | 15/15 |
| schaal 3 | 10/15 |
| losse png op schaal 4 | 15/15 |
| 1 graad gedraaid | 15/15 |
| 2 graden gedraaid | 13/15 |
| kolommen van plaats gewisseld | 15/15 |
| 45% helderheid | 15/15 |
| jpeg-kwaliteit 40 | 13/15 |
| ruis sigma 8 | 13/15 |
| ruis sigma 15 | 2/15 |
| gespiegeld | weigert netjes, `blocks: []` |

Een echt procentteken blijft een procentteken: 1638 glyphs (62 niet-breuktekens
in 26 systeemfonts) leverden geen enkele valspositief op, en een echte `%` die op
de plaats van de `½` in de pagina geplakt werd bleef staan, evenals een
toegevoegde regel `30% room`.

Renderschaal is de enige tesseract-instelling die er echt toe doet. Op de
ingrediëntenkolom haalt schaal 2 negen van de 21 fysieke regels, schaal 3 twintig
en schaal 4 alle 21, met een tekenfout van nul. Daarboven wordt het niet beter,
alleen trager. Het taalmodel maakt niet uit: de `nld` van Ubuntu doet het even
goed als `tessdata_best` en als het `Latin`-scriptmodel — 86 van de 1150 beproefde
configuraties halen alle 21 regels foutloos. Voorbewerking (deskew, Sauvola,
contrastrekken) leverde op deze scan niets op boven wat Tesseract zelf al doet.
Daarom staat er geen van alle in de pijplijn.

## Wat het niet kan

* **Cursief is het enige signaal voor een blokkop**, aangevuld met de witruimte
  erboven. Een boek dat zijn koppen vet zet in plaats van cursief wordt niet
  herkend.
* **Een breuk die Tesseract niet op zijn eigen glyphgrens afknipt** blijft staan.
  Op pagina 4 leest hij `½-1` als `Y-1`, waarbij de `Y`-box maar een deel van de
  breuk beslaat en de `-`-box de breuk plus het koppelteken; geen van beide is de
  glyph, en er wordt dus niets veranderd. Om dat te repareren zou het teken uit
  de inkt zelf gesegmenteerd moeten worden in plaats van uit Tesseracts vakjes.
* **Een uitgelijnde ingrediëntenlijst** — hoeveelheid rechts uitgelijnd, naam op
  een vaste tab — valt uiteen in twee kolommen, en dan kiest de kolomkeuze de
  kolom met alleen de getallen. Op een verzonnen testpagina met die opmaak bleven
  alleen de hoeveelheden over.
* **Een scan met flinke ruis** (sigma 15 en hoger) valt uit elkaar; bij sigma 22
  weigert het script netjes in plaats van te gokken.
* **Twijfelgevallen blijven staan.** De vormvergelijking moet een duidelijke
  voorsprong hebben; op pagina 7 haalt een `½` maar 0,72 tegen 0,71 voor het
  beste alternatief en blijft de `%` dus staan. Dat is de bedoelde kant om fout
  te gaan.
* **Losse afbeeldingen** kunnen niet scherper opnieuw gerenderd worden; staat het
  breukteken daar kleiner dan 20 pixels, dan blijft de lezing van Tesseract staan.
* De **hoeveelheidsregel** waarmee de ingrediëntenkolom herkend wordt gaat ervan
  uit dat ingrediënten met een getal beginnen. Een lijst zonder hoeveelheden
  (*olijfolie, zout, peper*) wordt niet als ingrediëntenkolom herkend.
* Alles is gemeten op één kookboek uit één fotografeersessie. Andere boeken,
  andere lettertypes, andere belichting: niet getest.

## Bestanden

| | |
|---|---|
| `__main__.py` | de opdrachtregel |
| `pagina.py` | de pijplijn: kolom kiezen, regels, koppen, breuken |
| `ocrlines.py` | woorden, kolommen en regels uit Tesseract |
| `breuken.py` | de breukclassificatie op vorm en topologie |
| `bron.py` | de pagina als beeld, en stukken op hogere resolutie |

Tests: `tests/test_cookbook_ocr.py`, 63 stuks, draait zonder tesseract en zonder
de pdf. Ze zijn tegen een mutatieproef gehouden: tien ingrepen in de pijplijn —
koppen negeren, de breukvervanging uitzetten, de corridorreparatie slopen, de
grootte-grens weghalen, alleen de grootste groep houden — worden alle tien
betrapt.

Het script zet `OMP_THREAD_LIMIT=1`. Tesseract verdeelt één pagina anders over
vier OpenMP-threads en wordt daar op een bezette machine juist trager van;
gemeten liep dezelfde pagina met één thread in tien seconden waar vier threads er
minuten over deden.
