// Twijfelgevallen: samenvoegvoorstellen bevestigen/afwijzen en categorieen bijstellen.
// Vereist esc() uit utils.js.

function flash(row, tekst) {
    if (!row) return;
    // Rij blijft staan zodat de lijst niet verspringt terwijl je doorwerkt.
    row.classList.add('opacity-50');
    const mark = document.createElement('span');
    mark.className = 'text-xs text-[#3B6D11] shrink-0';
    mark.textContent = tekst;
    row.appendChild(mark);
}

async function toPantry(id, btn) {
    btn.disabled = true;
    let data;
    try {
        const resp = await fetch('/api/pantry', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ingredient_id: id}),
        });
        data = await resp.json();
    } catch (e) {
        btn.disabled = false;    // offline: laat de knop bruikbaar
        return;
    }
    // Buiten de try: anders slikt hij ook fouten in deze DOM-code op.
    if (!data || (data.status !== 'success' && data.status !== 'exists')) {
        btn.disabled = false;
        return;
    }
    const row = btn.closest('.review-row');   // vóór remove(), anders null
    btn.remove();
    flash(row, '✓ op voorraad');
}

/** Zet de kaart op klaar: knoppen weg, resultaat blijft leesbaar staan. */
function sluitKaart(kaartOfKnop, tekst, kleur) {
    const kaart = kaartOfKnop.closest ? kaartOfKnop.closest('.dubbel-kaart') : null;
    if (!kaart) return;
    kaart.querySelectorAll('button, input').forEach(b => b.remove());
    kaart.classList.add('opacity-60', 'kaart-af');
    const mark = document.createElement('p');
    mark.className = `text-xs mt-1 whitespace-pre-line ${kleur || 'text-[#3B6D11]'}`;
    mark.textContent = tekst;
    kaart.appendChild(mark);
}

/** De twee ingredient-ids die op deze kaart staan. */
function kaartIds(kaart) {
    return (kaart.dataset.ids || '').split(',').map(Number).filter(Boolean);
}

/** De verse kaarten van de server, of null als die niet te halen zijn. */
async function verseKaarten() {
    try {
        const resp = await fetch('/twijfelgevallen/dubbel');
        if (!resp.ok) return null;
        const houder = document.createElement('div');
        houder.innerHTML = await resp.text();
        return Array.from(houder.querySelectorAll('.dubbel-kaart'));
    } catch (e) {
        return null;   // offline: dan blijft staan wat er staat
    }
}

/**
 * Werk de kaarten bij die door deze klik veranderd zijn.
 *
 * Eén samenvoeging raakt meer dan één kaart: hetzelfde ingredient staat soms
 * op twee voorstellen. Verdwijnt het, dan gaat die tweede kaart over een naam
 * die niet meer bestaat — beide knoppen gaven daar een stille 404. We halen
 * de bijgewerkte kaarten op en zetten ze op hun eigen plek terug, zodat de
 * lijst niet verspringt terwijl je doorwerkt. Is er geen voorstel meer voor
 * dat paar, dan zegt de kaart dat hij vervallen is.
 */
async function werkKaartenBij(verliezerId, winnaarId, verliezerNaam, winnaarNaam) {
    const lijst = document.getElementById('dubbel-lijst');
    if (!lijst) return;
    const geraakt = Array.from(lijst.querySelectorAll('.dubbel-kaart')).filter(k => {
        const ids = kaartIds(k);
        return !k.classList.contains('kaart-af')
               && (ids.includes(verliezerId) || ids.includes(winnaarId));
    });
    if (!geraakt.length) return;

    const vers = await verseKaarten();
    geraakt.forEach(kaart => {
        const rest = kaartIds(kaart).filter(id => id !== verliezerId);
        const nieuw = (vers || []).find(k => {
            const ids = kaartIds(k);
            return ids.includes(winnaarId) && rest.every(id => ids.includes(id));
        });
        if (nieuw) {
            kaart.replaceWith(nieuw);
        } else if (kaartIds(kaart).includes(verliezerId)) {
            sluitKaart(kaart.querySelector('button') || kaart,
                       `✗ vervallen: “${verliezerNaam}” is opgegaan in “${winnaarNaam}”`,
                       'text-[#8A6A2F]');
        }
    });
}

async function voegSamen(winnaarId, verliezerId, btn) {
    btn.disabled = true;
    const kaart = btn.closest('.dubbel-kaart');
    // De AH-koppeling is een keuze op zich: welke naam je ook houdt, je zegt
    // hier welk product er overblijft. Zonder keuze beslist de server zoals
    // altijd — de koppeling van de naam die je houdt.
    const gekozen = kaart ? kaart.querySelector('.ah-keuze input:checked') : null;
    let data;
    try {
        const resp = await fetch('/api/ingredienten/samenvoegen', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({winnaar_id: winnaarId, verliezer_id: verliezerId,
                                  ah_van_id: gekozen ? Number(gekozen.value) : null}),
        });
        data = await resp.json();
    } catch (e) {
        btn.disabled = false;    // offline: laat de knop bruikbaar
        return;
    }
    // Buiten de try, anders slikt hij ook fouten in deze DOM-code op.
    if (data && data.status === 'vervallen') {
        // De kaart kan niet meer. Dat hoort hij te zeggen, niet stil te slikken.
        sluitKaart(btn, `✗ ${data.message}`, 'text-[#8A6A2F]');
        return;
    }
    if (!data || data.status !== 'success') {
        btn.disabled = false;
        meldFout(btn, (data && data.message) || 'samenvoegen mislukt');
        return;
    }
    let tekst = `✓ ${data.recepten_verplaatst} recept(en) naar ${data.winnaar}; `
                + `“${data.verliezer}” is nu een alias`;
    // Omgerekende regels erbij: dan zie je zwart op wit wat de botsende
    // eenheid met je aantallen gedaan heeft.
    if (data.omgerekend && data.omgerekend.length) {
        tekst += `\nOmgerekend: ${data.omgerekend.join('; ')}`;
    }
    if (data.ah_melding) {
        tekst += `\n${data.ah_melding}`;
    }
    sluitKaart(btn, tekst);
    werkKaartenBij(data.verliezer_id, data.winnaar_id, data.verliezer, data.winnaar);
}

/** Een mislukking hoort op het scherm te komen, niet alleen in de console. */
function meldFout(btn, tekst) {
    const kaart = btn.closest('.dubbel-kaart');
    if (!kaart) return;
    let mark = kaart.querySelector('.kaart-fout');
    if (!mark) {
        mark = document.createElement('p');
        mark.className = 'kaart-fout text-xs text-[#8B1A1A] mt-1';
        kaart.appendChild(mark);
    }
    mark.textContent = `✗ ${tekst}`;
}

/** '1 bosje = 4 stuks': wat de gebruiker weet en de app niet mag verzinnen. */
async function legOmrekeningVast(ingredientId, anderId, van, naar, btn) {
    const vak = btn.closest('.omrekenvak');
    const veld = vak ? vak.querySelector('input') : null;
    if (!veld || !veld.value) return;
    btn.disabled = true;
    let data;
    try {
        const resp = await fetch('/api/ingredienten/omrekening', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ingredient_id: ingredientId, ander_id: anderId,
                                  van: van, naar: naar, factor: veld.value}),
        });
        data = await resp.json();
    } catch (e) {
        btn.disabled = false;
        return;
    }
    if (!data || data.status !== 'success') {
        btn.disabled = false;
        meldFout(btn, (data && data.message) || 'omrekening niet opgeslagen');
        return;
    }
    // De kaart opnieuw ophalen: de waarschuwing klopt niet meer en de
    // omrekening hoort nu bij allebei onder 'geen omrekening' te staan.
    const kaart = btn.closest('.dubbel-kaart');
    const vers = await verseKaarten();
    const nieuw = (vers || []).find(k => k.dataset.sleutel === kaart.dataset.sleutel);
    if (nieuw) {
        kaart.replaceWith(nieuw);
    } else {
        vak.remove();
    }
}

async function houdApart(aId, bId, btn) {
    btn.disabled = true;
    let data;
    try {
        const resp = await fetch('/api/ingredienten/apart', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ingredient_id: aId, ander_id: bId}),
        });
        data = await resp.json();
    } catch (e) {
        btn.disabled = false;
        return;
    }
    if (data && data.status === 'vervallen') {
        sluitKaart(btn, `✗ ${data.message}`, 'text-[#8A6A2F]');
        return;
    }
    if (!data || data.status !== 'success') {
        btn.disabled = false;
        meldFout(btn, (data && data.message) || 'niet opgeslagen');
        return;
    }
    sluitKaart(btn, '✓ blijven apart');
}

async function setCategory(id, category, el) {
    const row = el.closest('.review-row');
    let data;
    try {
        const resp = await fetch(`/api/ingredient/${id}/category`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({category}),
        });
        data = await resp.json();
    } catch (e) {
        return;   // offline: laat de rij staan zoals hij staat
    }
    // Buiten de try, anders slikt hij ook programmeerfouten in deze DOM-code.
    if (!data || data.status !== 'success') return;
    const sel = row.querySelector('select');
    if (sel && sel.value !== data.category) sel.value = data.category;
    const knop = row.querySelector('button');
    if (knop) knop.remove();
    flash(row, '✓ ' + data.category);
}
