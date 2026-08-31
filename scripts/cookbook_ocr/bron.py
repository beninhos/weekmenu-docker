# -*- coding: utf-8 -*-
"""De pagina als beeldbron, op elke gewenste resolutie.

Voor een PDF kunnen we een klein stukje pagina opnieuw en scherper renderen. Dat
is niet hetzelfde als een bestaand knipsel opschalen: bij opnieuw renderen komt
er echte detailinformatie bij. Dat is precies wat de breukclassificatie nodig
heeft, want die kijkt naar de rondjes in een glyph van nog geen twintig pixels.
"""

from PIL import Image


class Bron:
    """Levert de pagina op de basisschaal, en desgevraagd stukken op maat."""

    def __init__(self, pad, pagina=0, basisschaal=4.0):
        self.pad = pad
        self.pagina = pagina
        self.schaal = basisschaal
        self._page = None
        if pad.lower().endswith(".pdf"):
            import pypdfium2 as pdfium
            self._pdf = pdfium.PdfDocument(pad)
            if not 0 <= pagina < len(self._pdf):
                raise ValueError(f"pagina {pagina} bestaat niet, de pdf heeft er {len(self._pdf)}")
            self._page = self._pdf[pagina]
            self._basis = self._page.render(scale=basisschaal).to_pil().convert("RGB")
        else:
            self._basis = Image.open(pad).convert("RGB")
            self.schaal = 1.0

    @property
    def basis(self):
        return self._basis

    @property
    def herrenderbaar(self):
        """True als we stukken op hogere resolutie kunnen opvragen."""
        return self._page is not None

    def knipsel(self, box, min_hoogte):
        """Een knipsel van `box` (pixels op de basisschaal), minstens `min_hoogte` hoog.

        Bij een PDF renderen we het gebied opnieuw op een hogere schaal, en komt
        er echte detailinformatie bij. Bij een losse afbeelding kunnen we alleen
        opschalen en is dat niet zo. Geeft (beeld, hergerenderd), waarbij het
        tweede lid alleen True is als er werkelijk opnieuw gerasterd is.
        """
        x0, y0, x1, y1 = [int(v) for v in box]
        hoogte = max(1, y1 - y0)
        if hoogte >= min_hoogte:
            return self._basis.crop((x0, y0, x1, y1)), False
        factor = min_hoogte / hoogte
        if not self.herrenderbaar:
            knip = self._basis.crop((x0, y0, x1, y1))
            groot = (max(1, int(knip.width * factor)), max(1, int(knip.height * factor)))
            return knip.resize(groot, Image.LANCZOS), False

        # crop is (links, onder, rechts, boven) in punten, gemeten vanaf de rand
        bw, bh = self._basis.size
        pw, ph = self._page.get_size()
        links = x0 / bw * pw
        rechts = (bw - x1) / bw * pw
        boven = y0 / bh * ph
        onder = (bh - y1) / bh * ph
        beeld = self._page.render(scale=self.schaal * factor,
                                  crop=(links, onder, rechts, boven)).to_pil()
        return beeld.convert("RGB"), True
