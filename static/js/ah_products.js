// /ah-producten: per ingredient een AH-product koppelen. Vereist utils.js en ah_common.js.

function filterIngredients(q) {
    const lower = q.toLowerCase();
    document.querySelectorAll('.ingredient-card').forEach(card => {
        card.style.display = card.dataset.name.includes(lower) ? '' : 'none';
    });
}

function openSearch(id) {
    document.getElementById('search-' + id).classList.remove('hidden');
    document.getElementById('searchInput-' + id).focus();
    doSearch(id);
}

function closeSearch(id) {
    document.getElementById('search-' + id).classList.add('hidden');
}

function ahResultCard(id, p) {
    return `
        <button onclick='selectProduct(${id}, ${JSON.stringify(p).replace(/'/g, "\\'")})'
                class="ah-fade flex items-center gap-2 bg-white border border-[#E8E4DC] rounded-lg p-2 hover:border-[#C9A882] hover:bg-[#FAF8F5] transition-colors text-left">
            ${p.image
                ? `<img src="${p.image}" class="w-12 h-12 object-contain rounded flex-shrink-0">`
                : `<div class="w-12 h-12 bg-[#F5F2ED] rounded flex-shrink-0"></div>`}
            <div class="min-w-0">
                <p class="text-xs font-medium text-[#2C2C2C] leading-tight line-clamp-2">${p.isOrganic ? '🌱 ' : ''}${esc(p.title)}</p>
                <p class="text-xs text-[#6B6B6B]">${p.brand ? esc(p.brand) + ' · ' : ''}${esc(p.size)}</p>
                <div class="flex items-center flex-wrap gap-1 mt-0.5">
                    ${p.price ? `<span class="ah-price text-xs font-semibold">€${p.price}</span>` : ''}
                    ${p.wasPrice ? `<span class="ah-price text-xs text-[#6B6B6B] line-through">€${p.wasPrice}</span>` : ''}
                    ${p.unitPriceLabel ? `<span class="ah-price text-xs text-[#8B7355]">${p.unitPriceLabel}</span>` : ''}
                    ${p.isBonus ? '<span class="text-xs bg-[#C9A882] text-[#2C2C2C] font-bold px-1 rounded">BONUS</span>' : ''}
                </div>
                ${p.bonusMechanism ? `<p class="text-[10px] text-[#8B4513] leading-tight">${esc(p.bonusMechanism)}</p>` : ''}
            </div>
        </button>`;
}

async function doSearch(id) {
    const q = document.getElementById('searchInput-' + id).value.trim();
    if (!q) return;
    document.getElementById('advice-' + id).innerHTML = '';
    const resultsEl = document.getElementById('searchResults-' + id);
    resultsEl.innerHTML = '<p class="text-xs text-[#6B6B6B] col-span-2">Zoeken...</p>';
    const data = await ahFetchProducts(q, { size: 12 });
    let products = (data && data.products) || [];
    if (!products.length) {
        resultsEl.innerHTML = '<p class="text-xs text-[#6B6B6B] col-span-2">Geen resultaten gevonden.</p>';
        return;
    }
    if (document.getElementById('sortSel-' + id).value === 'unit') {
        products = products.slice().sort((a, b) => {
            if (a.unitPrice == null) return 1;
            if (b.unitPrice == null) return -1;
            return a.unitPrice - b.unitPrice;
        });
    }
    resultsEl.innerHTML = products.map(p => ahResultCard(id, p)).join('');
}

function adviceCard(id, col, p) {
    return `
        <div class="bg-white border rounded-lg p-2 flex flex-col" style="border-color:${col.accent}55">
            <div class="text-xs font-semibold mb-1" style="color:${col.accent}">${col.label}</div>
            ${p.image ? `<img src="${p.image}" class="w-full h-16 object-contain mb-1">` : ''}
            <p class="text-xs font-medium text-[#2C2C2C] leading-tight line-clamp-2 flex-1">${p.isOrganic ? '🌱 ' : ''}${esc(p.title)}</p>
            <div class="mt-1 leading-tight">
                <span class="ah-price text-base font-bold" style="color:${col.accent}">${p.unitPriceLabel || ('€' + p.price)}</span>
                <span class="ah-price text-[11px] text-[#6B6B6B] block">€${p.price} • ${esc(p.size)}</span>
            </div>
            <button onclick='selectProduct(${id}, ${JSON.stringify(p).replace(/'/g, "\\'")})'
                    class="ah-prijsknop mt-2 text-xs font-medium text-white rounded px-2 py-1.5 hover:opacity-90"
                    style="background:${col.accent}">Kies dit</button>
        </div>`;
}

async function showAdvice(id) {
    const q = document.getElementById('searchInput-' + id).value.trim();
    if (!q) return;
    const adviceEl = document.getElementById('advice-' + id);
    document.getElementById('searchResults-' + id).innerHTML = '';
    adviceEl.innerHTML = '<p class="text-xs text-[#6B6B6B]">Prijsadvies laden…</p>';
    const resp = await fetch('/api/ah/advice?q=' + encodeURIComponent(q));
    const d = await resp.json();
    const cols = [
        {key: 'cheapest', label: '💰 Goedkoopst', accent: '#16a34a'},
        {key: 'mid',      label: '⚖️ Tussenin',   accent: '#8B4513'},
        {key: 'organic',  label: '🌱 Biologisch', accent: '#3f7d3f'},
    ].filter(c => d[c.key]);
    if (!cols.length) {
        adviceEl.innerHTML = '<p class="text-xs text-[#6B6B6B]">Geen vergelijkbaar advies — te weinig producten met een €/eenheid.</p>';
        return;
    }
    adviceEl.innerHTML = `
        <div class="ah-fade space-y-2">
            <div class="text-xs text-[#6B6B6B]">Beste prijs per ${d.unit || 'eenheid'} — kies wat bij je past:</div>
            <div class="ah-advice-grid">
                ${cols.map(c => adviceCard(id, c, d[c.key])).join('')}
            </div>
        </div>`;
}

async function selectProduct(ingId, product) {
    const card = document.querySelector(`.ingredient-card[data-id="${ingId}"]`);
    if (card) card.style.opacity = '0.5';
    try {
        const resp = await fetch(`/api/ah/ingredient/${ingId}/link`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(product),
        });
        if (!resp.ok) throw new Error('Koppelen mislukt');
        await softRefreshCard(ingId);
    } catch (e) {
        if (card) card.style.opacity = '';
        alert(e.message || 'Koppelen mislukt');
    }
}

// Vervang één ingrediëntkaart door de verse server-versie — zonder
// volledige page-reload, zodat scrollpositie en andere panelen blijven.
async function softRefreshCard(ingId) {
    const current = document.querySelector(`.ingredient-card[data-id="${ingId}"]`);
    if (!current) { location.reload(); return; }
    const html = await (await fetch('/ah-producten')).text();
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const fresh = doc.querySelector(`.ingredient-card[data-id="${ingId}"]`);
    if (!fresh) { location.reload(); return; }
    fresh.classList.add('ah-fade');
    current.replaceWith(fresh);
    refreshStats();
}

// Werk de "x gekoppeld / y nog te koppelen" tellers bij na een wijziging.
function refreshStats() {
    const cards = document.querySelectorAll('.ingredient-card');
    let linked = 0;
    cards.forEach(c => { if (c.querySelector('[id^="card-"]')) linked++; });
    const total = cards.length;
    const linkedEl = document.getElementById('statLinked');
    const unlinkedEl = document.getElementById('statUnlinked');
    if (linkedEl) linkedEl.textContent = `${linked} gekoppeld`;
    if (unlinkedEl) unlinkedEl.textContent = `${total - linked} nog te koppelen`;
}

function togglePkg(id) {
    const panel = document.getElementById('pkg-' + id);
    const btn = document.getElementById('pkgToggle-' + id);
    const wasHidden = panel.classList.contains('hidden');
    panel.classList.toggle('hidden');
    btn.textContent = wasHidden ? '▾ Verpakking instellen' : '▸ Verpakking instellen';
}

// Eenheden waarin je meet in plaats van telt — spiegelt _MEETEENHEDEN in
// weekmenu/constants.py. Alleen om de vraag meteen mee te draaien als je de
// verpakkingseenheid aanpast; wat er wordt opgeslagen rekent de server uit.
const MAAT_MEETEENHEDEN = ['g', 'gr', 'gram', 'kg', 'kilo', 'kilogram',
                           'ml', 'cl', 'dl', 'l', 'liter'];
const MAAT_ANTWOORDEENHEID = {kg: 'g', kilo: 'g', kilogram: 'g',
                              l: 'ml', liter: 'ml', cl: 'ml', dl: 'ml'};

function zetMaatRichting(id) {
    const eenheid = (document.getElementById('pkgUnit-' + id).value || '').trim().toLowerCase();
    const aantal = parseFloat(document.getElementById('pkgQty-' + id).value);
    const perStuk = MAAT_MEETEENHEDEN.includes(eenheid);
    document.getElementById('maatStuk-' + id).classList.toggle('hidden', !perStuk);
    document.getElementById('maatPak-' + id).classList.toggle('hidden', perStuk);
    document.getElementById('maatStukEen-' + id).textContent =
        MAAT_ANTWOORDEENHEID[eenheid] || eenheid || 'g';
    // Gaat er meer dan één in een verpakking, dan zeggen we erbij om welke het
    // gaat: het veld vraagt naar één stuk, niet naar het hele netje.
    document.getElementById('maatPakVraag-' + id).textContent = (aantal > 1)
        ? `1 van de ${maatGetal(aantal)} ${eenheid || 'pak'} bevat`
        : `1 ${eenheid || 'pak'} bevat`;
    zetMaatTotaal(id);
}

// Getallen net zo opschrijven als de server: hoogstens twee decimalen en geen
// nullen die niets zeggen.
function maatGetal(getal) {
    return String(Math.round(getal * 100) / 100);
}

// Het doorgerekende totaal van één verpakking, zodat je kunt zien of je het
// veld goed leest: 10 teen per bol is 20 teen per netje van twee.
function zetMaatTotaal(id) {
    const doel = document.getElementById('maatPakTotaal-' + id);
    if (!doel) return;
    const aantal = parseFloat(document.getElementById('pkgQty-' + id).value);
    const waarde = parseFloat(document.getElementById('maatPakWaarde-' + id).value);
    const eenheid = document.getElementById('maatPakEenheid-' + id).value.trim();
    doel.textContent = (aantal > 1 && waarde > 0 && eenheid)
        ? `samen ${maatGetal(waarde * aantal)} ${eenheid} per verpakking` : '';
}

// Hetzelfde totaal op de kaarten in het blok hierboven.
function maatTotaalBij(kaart) {
    const doel = kaart.querySelector('.maat-totaal');
    if (!doel) return;
    const aantal = parseFloat(kaart.dataset.pkgAantal);
    const waarde = parseFloat(kaart.querySelector('.maat-waarde').value);
    doel.textContent = (aantal > 1 && waarde > 0)
        ? `samen ${maatGetal(waarde * aantal)} ${kaart.dataset.eenheid} per verpakking` : '';
}

async function savePkg(id, event) {
    const btn = event.target;
    const perStuk = !document.getElementById('maatStuk-' + id).classList.contains('hidden');
    const eenheidEl = document.getElementById((perStuk ? 'maatStukEenheid-' : 'maatPakEenheid-') + id);
    const waardeEl  = document.getElementById((perStuk ? 'maatStukWaarde-' : 'maatPakWaarde-') + id);
    const data = {
        ah_pkg_qty:  parseFloat(document.getElementById('pkgQty-' + id).value) || null,
        ah_pkg_unit: document.getElementById('pkgUnit-' + id).value.trim() || null,
        // Het antwoord op de gestelde vraag, niet de factor: welke kant die
        // vraag opstond weet de server ook, en daar hoort het omrekenen.
        maat_richting: perStuk ? 'per_stuk' : 'per_verpakking',
        maat_eenheid:  eenheidEl.value.trim(),
        // Rauw doorgeven: een leeg veld wist de maat, en over een getal dat
        // niets oplevert (nul, negatief) beslist de server — niet parseFloat,
        // die van 0 stilletjes 'leeg' maakt.
        maat_waarde:   waardeEl.value.trim() || null,
        maat_antwoord_eenheid: perStuk
            ? document.getElementById('maatStukEen-' + id).textContent.trim() : null,
    };
    const resp = await fetch(`/api/ah/ingredient/${id}/pkg-config`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data),
    });
    // Een weigering mag niet als 'Opgeslagen' voorbijkomen: dan denk je dat de
    // maat staat terwijl de server hem juist niet aannam.
    const d = await resp.json().catch(() => ({}));
    if (!resp.ok) {
        alert(d.message || 'Opslaan mislukt');
        return;
    }
    btn.textContent = '✓ Opgeslagen';
    setTimeout(() => btn.textContent = 'Opslaan', 1500);
}

// ── Het blok met de scheve verpakkingen ──────────────────────────────────

function maatKaartWeg(kaart) {
    kaart.remove();
    maatTellersBij();
}

// De twee tellers in het blok, en het blok zelf: dat verdwijnt pas als er ook
// geen overgeslagen geval meer onder staat — anders was de weg terug weg.
function maatTellersBij() {
    const open = document.querySelectorAll('#maatLijst .maat-kaart').length;
    const over = document.querySelectorAll('#maatOverLijst .maat-kaart').length;
    document.getElementById('maatTeller').textContent = open;
    document.getElementById('maatOverTeller').textContent = `${over} overgeslagen`;
    document.getElementById('maatOverBlok').classList.toggle('hidden', !over);
    if (!open && !over) document.getElementById('maatBlok').remove();
}

function toonOvergeslagen() {
    const lijst = document.getElementById('maatOverLijst');
    const verborgen = lijst.classList.contains('hidden');
    lijst.classList.toggle('hidden');
    document.getElementById('maatOverPijl').textContent = verborgen ? '▾' : '▸';
    document.getElementById('maatOverActie').textContent = verborgen ? 'verbergen' : 'tonen';
}

async function bevestigMaat(btn) {
    const kaart = btn.closest('.maat-kaart');
    const waarde = parseFloat(kaart.querySelector('.maat-waarde').value);
    if (!waarde || waarde <= 0) {
        alert('Vul eerst in wat één stuk is.');
        return;
    }
    btn.disabled = true;
    const id = kaart.dataset.id;
    const resp = await fetch(`/api/ah/ingredient/${id}/maat`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            eenheid: kaart.dataset.eenheid,
            waarde: waarde,
            richting: kaart.dataset.richting,
            antwoord_eenheid: kaart.dataset.antwoordEenheid,
        }),
    });
    const d = await resp.json();
    if (d.status !== 'success') {
        btn.disabled = false;
        alert(d.message || 'Opslaan mislukt');
        return;
    }
    // De ingrediëntkaart verderop toont dezelfde instelling; die bijwerken is
    // goedkoper dan de hele pagina opnieuw ophalen.
    const perStuk = kaart.dataset.richting === 'per_stuk';
    const eenheidEl = document.getElementById((perStuk ? 'maatStukEenheid-' : 'maatPakEenheid-') + id);
    const waardeEl  = document.getElementById((perStuk ? 'maatStukWaarde-' : 'maatPakWaarde-') + id);
    if (eenheidEl) eenheidEl.value = kaart.dataset.eenheid;
    if (waardeEl) waardeEl.value = waarde;
    maatKaartWeg(kaart);
}

async function slaMaatOver(btn) {
    const kaart = btn.closest('.maat-kaart');
    btn.disabled = true;
    const resp = await fetch(`/api/ah/ingredient/${kaart.dataset.id}/maat/overslaan`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({eenheid: kaart.dataset.eenheid}),
    });
    const d = await resp.json();
    if (d.status !== 'success') {
        btn.disabled = false;
        alert(d.message || 'Opslaan mislukt');
        return;
    }
    // Niet weggooien maar verplaatsen: onder het blok blijft hij bereikbaar,
    // zodat één misklik geen eindstation is.
    kaart.querySelector('.maat-knop-over').classList.add('hidden');
    kaart.querySelector('.maat-knop-terug').classList.remove('hidden');
    btn.disabled = false;
    document.getElementById('maatOverLijst').appendChild(kaart);
    maatTellersBij();
}

async function vraagMaatToch(btn) {
    const kaart = btn.closest('.maat-kaart');
    btn.disabled = true;
    const resp = await fetch(`/api/ah/ingredient/${kaart.dataset.id}/maat/terug`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({eenheid: kaart.dataset.eenheid}),
    });
    const d = await resp.json();
    if (d.status !== 'success') {
        btn.disabled = false;
        alert(d.message || 'Terugzetten mislukt');
        return;
    }
    kaart.querySelector('.maat-knop-terug').classList.add('hidden');
    kaart.querySelector('.maat-knop-over').classList.remove('hidden');
    btn.disabled = false;
    document.getElementById('maatLijst').appendChild(kaart);
    maatTellersBij();
}

async function refreshIngredient(ingId, event) {
    const btn = event.target;
    btn.textContent = '⏳';
    btn.disabled = true;
    const resp = await fetch(`/api/ah/ingredient/${ingId}/refresh`, {method: 'POST'});
    const data = await resp.json();
    if (data.status === 'success') {
        location.reload();
    } else {
        btn.textContent = '🔄';
        btn.disabled = false;
        alert(data.message || 'Vernieuwen mislukt');
    }
}
