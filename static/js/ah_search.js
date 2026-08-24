// AH-productzoeker voor boodschappenlijst-items.
// Verwacht per item een .shopping-item met daarin het paneel uit
// templates/_ah_search_panel.html. Vereist esc() uit utils.js.

const AH_SEARCH_SIZE = 50;

// Laatste zoekresultaat + gekozen filters per paneel.
const _ahState = new WeakMap();

function toggleSearch(trigger) {
    const item      = trigger.closest('.shopping-item');
    const panel     = item.querySelector('.ah-search-panel');
    const wasHidden = panel.classList.contains('hidden');
    document.querySelectorAll('.ah-search-panel').forEach(p => p.classList.add('hidden'));
    if (wasHidden) {
        panel.classList.remove('hidden');
        panel.querySelector('.ah-search-input').focus();
    }
}

// ── Zoeken ────────────────────────────────────────────────────────────────
// taxonomyId/pkg: undefined = huidige chip behouden, null = filter opheffen.
async function doSearch(input, taxonomyId, pkg) {
    const panel     = input.closest('.ah-search-panel');
    const resultsEl = panel.querySelector('.ah-results');
    const query     = panel.querySelector('.ah-search-input').value.trim();
    if (!query) return;

    const prev = _ahState.get(panel);
    if (taxonomyId === undefined) taxonomyId = prev ? prev.taxonomyId : null;
    if (pkg === undefined)        pkg        = prev ? prev.pkg : null;

    resultsEl.innerHTML = '<div class="text-xs text-[#6B6B6B] p-3 text-center">Zoeken...</div>';
    let url = '/api/ah/product-search?q=' + encodeURIComponent(query) + '&size=' + AH_SEARCH_SIZE;
    if (taxonomyId) url += '&taxonomy_id=' + encodeURIComponent(taxonomyId);
    if (pkg) url += '&pkg=' + encodeURIComponent(pkg);

    try {
        const resp = await fetch(url);
        const data = await resp.json();
        _ahState.set(panel, {
            products:   data.products || [],
            taxonomies: data.taxonomies || [],
            sizes:      data.sizes || [],
            total:      data.total || 0,
            shown:      data.shown || 0,
            error:      data.error || '',
            pkg:        pkg || null,
            taxonomyId: taxonomyId || null,
        });
        _ahRender(panel);
    } catch (e) {
        resultsEl.innerHTML = '<div class="text-xs text-red-400 p-3 text-center">Fout: ' + esc(e.message) + '</div>';
    }
}

// Nogmaals op dezelfde chip klikken heft dat filter op.
function ahPickTaxonomy(btn, taxonomyId) {
    const panel = btn.closest('.ah-search-panel');
    const state = _ahState.get(panel);
    const next  = (state && state.taxonomyId === taxonomyId) ? null : taxonomyId;
    doSearch(panel.querySelector('.ah-search-input'), next);
}

function ahPickSize(btn, pkg) {
    const panel = btn.closest('.ah-search-panel');
    const state = _ahState.get(panel);
    const next  = (state && state.pkg === pkg) ? null : pkg;
    doSearch(panel.querySelector('.ah-search-input'), undefined, next);
}

// Eén rij filterchips: [label] [chip] [chip] …
function _ahChipRow(el, label, chips, onclickFor) {
    if (!chips.length) {
        el.classList.add('hidden');
        el.classList.remove('flex');
        return;
    }
    el.innerHTML =
        `<span class="shrink-0 text-xs text-[#9CA3AF] pr-1">${label}</span>` +
        chips.map(c => `
            <button onclick="${onclickFor(c)}"
                    class="shrink-0 rounded-full border px-2 py-0.5 text-xs ${c.active
                        ? 'bg-[#2C2C2C] text-white border-[#2C2C2C]'
                        : 'border-[#D4CEC4] text-[#6B6B6B] hover:bg-[#FAF8F5]'}">
                ${esc(c.label)} <span class="opacity-60">${c.count}</span>
            </button>`).join('');
    el.classList.remove('hidden');
    el.classList.add('flex');
}

function _ahRender(panel) {
    const state = _ahState.get(panel);
    if (!state) return;
    const resultsEl = panel.querySelector('.ah-results');
    const countEl   = panel.querySelector('.ah-result-count');

    // Beide facetten komen van AH zelf, per zoekopdracht — dus geen eigen
    // categorie- of matenlijst om bij te houden.
    _ahChipRow(
        panel.querySelector('.ah-taxonomies'), 'Soort',
        state.taxonomies.map(t => ({...t, active: state.taxonomyId === t.id})),
        c => `ahPickTaxonomy(this, '${c.id}')`);
    _ahChipRow(
        panel.querySelector('.ah-sizes'), 'Maat',
        state.sizes.map(s => ({...s, active: state.pkg === s.label})),
        c => `ahPickSize(this, '${c.label}')`);

    const note = state.error;
    const capped = state.shown > state.products.length
        ? ` (eerste ${state.products.length} getoond)` : '';
    countEl.textContent = state.pkg
        ? `${state.shown} van ${state.total} met maat ${state.pkg}${capped}`
        : `${state.shown} van ${state.total} resultaten${capped}`;

    resultsEl.innerHTML =
        (note ? `<div class="text-xs text-[#8B4513] bg-[#FDF8F3] px-3 py-2">${note}</div>` : '') +
        (state.products.length
            ? state.products.map(_ahResultRow).join('')
            : (note ? '' : '<div class="text-xs text-[#6B6B6B] p-3 text-center">Geen resultaten</div>'));
}

function _ahResultRow(p) {
    return `
        <div class="flex items-center gap-3 px-3 py-2 hover:bg-[#FAF8F5] cursor-pointer border-b border-[#E8E4DC] last:border-0"
             onclick="linkProduct(this, ${JSON.stringify(p).replace(/"/g, '&quot;')})">
            <div class="shrink-0 rounded-lg overflow-hidden" style="width:48px;height:48px;background-color:${p.bgColor || '#f0ede8'}">
                ${p.image ? `<img src="${p.image}" class="w-full h-full object-contain p-1.5" style="mix-blend-mode:multiply" alt="">` : ''}
            </div>
            <div class="flex-grow min-w-0">
                <div class="text-sm font-semibold text-[#2C2C2C] truncate">${esc(p.title)}</div>
                <div class="text-xs text-[#6B6B6B]">${esc(p.size || '')}${p.subCategory ? ' · ' + esc(p.subCategory) : ''}</div>
            </div>
            <div class="text-right shrink-0">
                ${p.isBonus ? '<div style="font-size:10px" class="font-semibold bg-[#FDF8F3] text-[#8B4513] px-1 rounded mb-0.5">BONUS</div>' : ''}
                <div class="text-sm font-bold text-[#2C2C2C]">${p.price ? '€' + p.price : ''}</div>
                ${p.unitPriceLabel ? `<div class="text-xs text-[#8B7355]">${esc(p.unitPriceLabel)}</div>` : ''}
            </div>
        </div>`;
}

async function linkProduct(row, product) {
    const panel        = row.closest('.ah-search-panel');
    const item         = panel.closest('.shopping-item');
    const ingredientId = item.dataset.ingredientId;
    if (!ingredientId) return;

    try {
        const resp = await fetch(`/api/ah/ingredient/${ingredientId}/link`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(product),
        });
        const data = await resp.json();
        if (data.ok || data.status === 'ok') {
            location.reload();
        } else {
            alert(data.message || 'Koppelen mislukt');
        }
    } catch (e) {
        console.error('Koppelen mislukt:', e);
    }
}
