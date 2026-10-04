// Boodschappenlijst-pagina: recept-picker, extra-items, verstuur naar AH, klik-af-flow.
// Data komt via <script type="application/json" id="page-data"> in het template.
// Vereist utils.js, ah_common.js, ah_search.js (in die volgorde ingeladen).

const _pageData = JSON.parse(document.getElementById("page-data").textContent);

const RECIPES = _pageData.recipes;
const WEEKS_BY_ING = _pageData.weeksByIngredient;

(function() {
    const input    = document.getElementById('extraRecipeInput');
    const dropdown = document.getElementById('extraRecipeDropdown');

    function render(q) {
        const needle = q.toLowerCase();
        const hits = RECIPES.filter(r => r.name.toLowerCase().includes(needle)).slice(0, 12);
        if (!hits.length) {
            dropdown.innerHTML = '<div class="px-3 py-2 text-xs text-[#6B6B6B]">Geen recept gevonden</div>';
        } else {
            dropdown.innerHTML = hits.map(r => `
                <div class="extra-recipe-option px-3 py-2 cursor-pointer hover:bg-[#FAF8F5] text-sm text-[#2C2C2C]"
                     data-id="${r.id}" data-name="${esc(r.name)}" data-serves="${r.serves || ''}">${esc(r.name)}</div>
            `).join('');
            dropdown.querySelectorAll('.extra-recipe-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    input.value = opt.dataset.name;
                    input.dataset.recipeId = opt.dataset.id;
                    if (opt.dataset.serves) document.getElementById('extraPeople').value = opt.dataset.serves;
                    dropdown.classList.add('hidden');
                });
            });
        }
        dropdown.classList.remove('hidden');
    }

    input.addEventListener('input', () => {
        delete input.dataset.recipeId;
        const q = input.value.trim();
        if (q.length < 1) { dropdown.classList.add('hidden'); return; }
        render(q);
    });
    input.addEventListener('focus', () => { if (input.value.trim()) render(input.value.trim()); });
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) dropdown.classList.add('hidden');
    });
})();

async function checkItem(ingredientId, checked) {
    const resp = await fetch(`/api/boodschappen/item/${ingredientId}/check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checked }),
    });
    if (resp.ok) location.reload();
}

async function checkAll() {
    if (!confirm('Alle openstaande items afvinken?')) return;
    const btn = document.getElementById('checkAllBtn');
    btn.disabled = true;
    btn.textContent = 'Bezig…';
    await fetch('/api/boodschappen/check-all', { method: 'POST' });
    location.reload();
}

async function removeExtra(id) {
    await fetch(`/api/boodschappen/extra/${id}`, { method: 'DELETE' });
    location.reload();
}

function toggleExtraPicker() {
    document.getElementById('extraPicker').classList.toggle('hidden');
}

function toggleAddItemPicker() {
    document.getElementById('addItemPicker').classList.toggle('hidden');
}

async function addExtra() {
    const input = document.getElementById('extraRecipeInput');
    let recipeId = input.dataset.recipeId ? parseInt(input.dataset.recipeId) : null;
    if (!recipeId) {
        const match = RECIPES.find(r => r.name.toLowerCase() === input.value.trim().toLowerCase());
        if (match) recipeId = match.id;
    }
    if (!recipeId) { alert('Kies een recept uit de suggesties'); return; }
    const people = parseInt(document.getElementById('extraPeople').value) || 4;
    // Staat dit recept deze week al als los recept op de lijst? Dan vragen:
    // zelfde maaltijd past het aantal aan, 'komt erbij' maakt een tweede, en
    // wegklikken voegt niets toe.
    const naam = (RECIPES.find(r => r.id === recipeId) || {}).name;
    const { keuze } = await kiesBijLosRecept(_pageData.losseRecepten, recipeId,
                                             _pageData.year, _pageData.week, naam);
    if (keuze === 'annuleer') return;
    const erbij = keuze === 'erbij';
    const resp = await fetch('/api/boodschappen/extra', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ recipe_id: recipeId, people_count: people, erbij }),
    });
    if (resp.ok) location.reload();
}

async function terugzetten(ingredientId) {
    const resp = await fetch(`/api/boodschappen/item/${ingredientId}/terugzetten`, { method: 'POST' });
    if (resp.ok) location.reload();
}

function collectQtyOverrides() {
    const qtys = {};
    document.querySelectorAll('.shopping-item').forEach(item => {
        const ingId = item.dataset.ingredientId;
        const valEl = item.querySelector('.qty-value');
        if (ingId && valEl) qtys[ingId] = parseInt(valEl.textContent, 10);
    });
    return qtys;
}

async function sendToAh() {
    const btn = document.getElementById('sendAhBtn');
    btn.disabled = true;
    const qty_overrides = collectQtyOverrides();
    const resp = await fetch('/api/boodschappen/send-to-ah', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ qty_overrides }),
    });
    const data = await resp.json();
    alert(data.message || (resp.ok ? 'Verstuurd' : 'Mislukt'));
    if (resp.ok && data.status === 'success') location.reload(); else btn.disabled = false;
}

// Een tweede tik op ✕ terwijl de eerste nog loopt doet niets: het kruisje
// legt de open hoeveelheid vast, en twee keer is dubbel.
const _bezig = new Set();

async function excludeItem(ingredientId) {
    if (_bezig.has(ingredientId)) return;
    _bezig.add(ingredientId);
    await fetch(`/api/boodschappen/item/${ingredientId}/remove`, { method: 'POST' });
    location.reload();
}

// ── Qty controls (lokaal, opgeslagen naar de laatste bijdragende week) ──
function changeQty(btn, delta) {
    const control = btn.closest('.qty-control');
    const item    = control.closest('.shopping-item');
    const valEl   = control.querySelector('.qty-value');
    const current = parseInt(valEl.textContent, 10);
    const ingredientId = item.dataset.ingredientId;

    // Prullenbak: qty=1 en min geklikt → uitsluiten van de lijst
    if (delta === -1 && current <= 1) {
        excludeItem(ingredientId);
        return;
    }

    const next    = Math.max(1, current + delta);
    if (next === current) return;
    valEl.textContent = next;
    const icon = control.querySelector('.qty-minus-icon');
    if (icon) icon.textContent = next <= 1 ? '🗑' : '−';

    const weeks = WEEKS_BY_ING[String(ingredientId)] || [];
    if (!weeks.length) return;
    const [y, w] = weeks[weeks.length - 1];
    fetch(`/api/shopping-list/${y}/${w}/item/${ingredientId}/qty`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ qty: next }),
    }).catch(e => console.warn('Qty opslaan mislukt:', e));
}

// ── (+) Los item toevoegen (aan de huidige ISO-week) ─────────────────────
(function() {
    const input    = document.getElementById('addItemInput');
    const dropdown = document.getElementById('addItemDropdown');
    let debounce   = null;
    let activeIdx  = -1;

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(debounce);
        if (q.length < 1) { dropdown.classList.add('hidden'); return; }
        debounce = setTimeout(() => fetchAddResults(q), 200);
    });

    input.addEventListener('keydown', (e) => {
        if (dropdown.classList.contains('hidden')) return;
        const items = dropdown.querySelectorAll('.add-item-option');
        if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); highlightAdd(items); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlightAdd(items); }
        else if (e.key === 'Enter' && activeIdx >= 0 && items[activeIdx]) { e.preventDefault(); items[activeIdx].click(); }
        else if (e.key === 'Escape') { dropdown.classList.add('hidden'); activeIdx = -1; }
    });

    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.add('hidden'); activeIdx = -1;
        }
    });

    function highlightAdd(items) {
        items.forEach((el, i) => el.classList.toggle('bg-[#FAF8F5]', i === activeIdx));
    }

    async function fetchAddResults(q) {
        try {
            const resp = await fetch('/api/ingredients/search?q=' + encodeURIComponent(q));
            const results = await resp.json();
            if (!results.length) {
                dropdown.innerHTML = '<div class="px-3 py-2 text-xs text-[#6B6B6B]">Geen ingrediënt gevonden</div>';
                dropdown.classList.remove('hidden');
                return;
            }
            dropdown.innerHTML = results.map(r => `
                <div class="add-item-option flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[#FAF8F5] text-sm"
                     data-id="${r.id}" data-name="${esc(r.name)}" data-cat="${esc(r.category)}">
                    <span class="text-[#2C2C2C]">${esc(r.name)}</span>
                    <span class="text-xs text-[#6B6B6B]">${esc(r.category)}${r.has_ah ? ' · AH' : ''}</span>
                </div>
            `).join('');
            dropdown.querySelectorAll('.add-item-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    input.value = opt.dataset.name;
                    input.dataset.ingredientId = opt.dataset.id;
                    dropdown.classList.add('hidden');
                });
            });
            dropdown.classList.remove('hidden');
            activeIdx = -1;
        } catch (e) {
            dropdown.classList.add('hidden');
        }
    }
})();

async function addLosItem() {
    const input        = document.getElementById('addItemInput');
    const ingredientId  = input.dataset.ingredientId;
    if (!ingredientId) { alert('Kies een ingrediënt uit de suggesties'); return; }
    const amount = parseFloat(document.getElementById('addItemAmount').value) || 1;
    const unit   = document.getElementById('addItemUnit').value.trim() || 'stuks';

    try {
        const resp = await fetch(`/api/shopping-list/${_pageData.year}/${_pageData.week}/add-item`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ingredient_id: parseInt(ingredientId), amount, unit }),
        });
        const data = await resp.json();
        if (data.status === 'success') {
            location.reload();
        } else {
            alert(data.message || 'Item toevoegen mislukt');
        }
    } catch (e) {
        console.error('Item toevoegen mislukt:', e);
    }
}

async function setBron(ingredientId, bron, el) {
    try {
        const resp = await fetch(`/api/ingredient/${ingredientId}/bron`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({bron}),
        });
        const data = await resp.json();
        if (data.status !== 'success') return;
        window.location.reload();   // item springt naar het juiste blok
    } catch (e) { /* offline: keuze blijft staan tot de volgende keer */ }
}
