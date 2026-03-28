let acDebounce = null;

/* -- Autocomplete ------------------------------------------------ */
function initAutocomplete(input) {
    const wrap = input.closest('.relative') || input.parentElement;
    const dropdown = wrap.querySelector('.ac-dropdown');
    const hiddenId = wrap.querySelector('input[name="ingredient_id[]"]');
    let activeIdx = -1;

    input.addEventListener('input', () => {
        hiddenId.value = '';
        const q = input.value.trim();
        clearTimeout(acDebounce);
        if (q.length < 1) { dropdown.classList.add('hidden'); return; }
        acDebounce = setTimeout(() => fetchResults(q, dropdown, input, hiddenId), 200);
    });

    input.addEventListener('keydown', (e) => {
        if (dropdown.classList.contains('hidden')) return;
        const items = dropdown.querySelectorAll('.ac-item');
        if (e.key === 'ArrowDown') { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); highlightItem(items, activeIdx); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlightItem(items, activeIdx); }
        else if (e.key === 'Enter' && activeIdx >= 0 && items[activeIdx]) { e.preventDefault(); items[activeIdx].click(); }
        else if (e.key === 'Escape') { dropdown.classList.add('hidden'); activeIdx = -1; }
    });

    document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target)) { dropdown.classList.add('hidden'); activeIdx = -1; }
    });
}

function highlightItem(items, idx) {
    items.forEach((el, i) => {
        el.classList.toggle('bg-[#FAF8F5]', i === idx);
    });
}

async function fetchResults(q, dropdown, input, hiddenId) {
    try {
        const resp = await fetch('/api/ingredients/search?q=' + encodeURIComponent(q));
        const results = await resp.json();
        if (!results.length) {
            dropdown.innerHTML = `<div class="px-3 py-2 text-xs text-[#6B6B6B]">Geen match \u2014 wordt nieuw aangemaakt bij opslaan</div>`;
            dropdown.classList.remove('hidden');
            return;
        }
        dropdown.innerHTML = results.map((r, i) => `
            <div class="ac-item flex items-center justify-between px-3 py-1.5 cursor-pointer hover:bg-[#FAF8F5] text-sm"
                 data-id="${r.id}" data-name="${esc(r.name)}" data-cat="${esc(r.category)}">
                <span class="text-[#2C2C2C]">${esc(r.name)}</span>
                <span class="text-xs text-[#6B6B6B]">${esc(r.category)}${r.has_ah ? ' \u00B7 AH' : ''}</span>
            </div>
        `).join('');
        dropdown.querySelectorAll('.ac-item').forEach(item => {
            item.addEventListener('click', () => {
                input.value = item.dataset.name;
                hiddenId.value = item.dataset.id;
                const row = input.closest('.ingredient-row');
                if (row) {
                    const catSel = row.querySelector('select[name="category[]"]');
                    if (catSel) catSel.value = item.dataset.cat;
                }
                dropdown.classList.add('hidden');
            });
        });
        dropdown.classList.remove('hidden');
    } catch (err) {
        dropdown.classList.add('hidden');
    }
}

// Initialize autocomplete on all existing rows
document.querySelectorAll('.ingredient-ac').forEach(initAutocomplete);
