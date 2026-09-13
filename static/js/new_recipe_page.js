// Formulier voor nieuw recept — bovenop recipe-form.js (dat de ingredient-rijen doet),
// deze module regelt titel/serves/cookbook/foto/opslaan.

const quill = setupQuill('#quill-editor');

document.querySelector('form').addEventListener('submit', function() {
  document.getElementById('fieldInstructions').value = quill.root.innerHTML;
});

/* ── Nieuw kookboek toggle ───────────────────────────────── */
let pendingSuggestion = null;

function showCookbookSuggestion(name) {
    pendingSuggestion = name;
    const banner = document.getElementById('cookbookSuggestion');
    document.getElementById('cookbookSuggestionText').textContent = `Kookboek '${name}' aanmaken?`;
    banner.classList.remove('hidden');
}

function acceptCookbookSuggestion() {
    if (!pendingSuggestion) return;
    const sel = document.getElementById('fieldCookbook');
    sel.value = '__new__';
    const input = document.getElementById('newCookbookInput');
    input.value = pendingSuggestion;
    input.classList.remove('hidden');
    document.getElementById('cookbookSuggestion').classList.add('hidden');
    pendingSuggestion = null;
}

function dismissCookbookSuggestion() {
    document.getElementById('cookbookSuggestion').classList.add('hidden');
    pendingSuggestion = null;
}

/* ── Import mode switching ────────────────────────────────── */
function showImportMode(mode) {
    const photoTab = document.getElementById('tabPhoto');
    const urlTab = document.getElementById('tabUrl');
    const photoDiv = document.getElementById('importPhoto');
    const urlDiv = document.getElementById('importUrl');

    if (mode === 'photo') {
        photoTab.className = 'flex-1 py-2 px-4 rounded-lg text-sm font-medium border-2 border-[#8B4513] bg-[#8B4513] text-white';
        urlTab.className = 'flex-1 py-2 px-4 rounded-lg text-sm font-medium border-2 border-[#D4CEC4] text-[#6B6B6B] hover:border-[#8B4513]';
        photoDiv.classList.remove('hidden');
        urlDiv.classList.add('hidden');
    } else {
        urlTab.className = 'flex-1 py-2 px-4 rounded-lg text-sm font-medium border-2 border-[#8B4513] bg-[#8B4513] text-white';
        photoTab.className = 'flex-1 py-2 px-4 rounded-lg text-sm font-medium border-2 border-[#D4CEC4] text-[#6B6B6B] hover:border-[#8B4513]';
        urlDiv.classList.remove('hidden');
        photoDiv.classList.add('hidden');
    }
}

/* ── Photo import ────────────────────────────────────────── */
let selectedPhotos = [];

function renderPhotoPreview() {
    const preview = document.getElementById('photoPreview');
    const importBtn = document.getElementById('photoImportBtn');
    const selectBtn = document.getElementById('photoSelectBtn');

    if (selectedPhotos.length === 0) {
        preview.classList.add('hidden');
        importBtn.classList.add('hidden');
        selectBtn.textContent = "Kies foto's (max 3)";
        selectBtn.classList.remove('hidden');
        return;
    }

    preview.innerHTML = '';
    selectedPhotos.forEach((file, i) => {
        const div = document.createElement('div');
        div.className = 'relative';
        const img = document.createElement('img');
        img.className = 'w-full h-24 object-cover rounded';
        img.src = URL.createObjectURL(file);
        const badge = document.createElement('span');
        badge.className = 'absolute top-1 left-1 bg-black/50 text-white text-xs px-1.5 py-0.5 rounded';
        badge.textContent = i + 1;
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.textContent = '✕';
        removeBtn.className = 'absolute top-1 right-1 bg-black/50 text-white text-xs w-5 h-5 rounded flex items-center justify-center leading-none';
        removeBtn.onclick = () => { selectedPhotos.splice(i, 1); renderPhotoPreview(); };
        div.appendChild(img);
        div.appendChild(badge);
        div.appendChild(removeBtn);
        preview.appendChild(div);
    });

    preview.classList.remove('hidden');
    importBtn.classList.remove('hidden');

    if (selectedPhotos.length >= 3) {
        selectBtn.classList.add('hidden');
    } else {
        selectBtn.classList.remove('hidden');
        selectBtn.textContent = `Voeg foto toe (${selectedPhotos.length}/3)`;
    }
}

function handlePhotoSelect(input) {
    const nieuweFiles = Array.from(input.files).filter(f =>
        !selectedPhotos.some(e => e.name === f.name && e.size === f.size)
    );
    selectedPhotos = selectedPhotos.concat(nieuweFiles).slice(0, 3);
    input.value = '';
    renderPhotoPreview();
}

async function importFromPhoto() {
    if (selectedPhotos.length === 0) return;

    const btn = document.getElementById('photoImportBtn');
    const statusDiv = document.getElementById('photoStatus');
    const banana = document.getElementById('photoBanana');
    const statusText = document.getElementById('photoStatusText');

    btn.disabled = true;
    btn.textContent = 'Bezig met lezen...';
    statusDiv.className = 'text-sm text-[#6B6B6B] flex items-center gap-2';
    statusText.textContent = 'Recept wordt herkend...';
    banana.classList.remove('hidden');
    statusDiv.classList.remove('hidden');

    const formData = new FormData();
    selectedPhotos.forEach(file => formData.append('photos', file));

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120000);

    try {
        const response = await fetch('/recipe/from-photo', {
            method: 'POST',
            body: formData,
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        const data = await response.json();

        if (data.status !== 'success') {
            statusDiv.className = 'text-sm text-red-600 flex items-center gap-2';
            banana.classList.add('hidden');
            statusText.textContent = 'Fout: ' + data.message;
            return;
        }

        // Pre-fill formulier (zelfde als URL import)
        if (data.name) document.getElementById('fieldName').value = data.name;
        if (data.serves) document.getElementById('fieldServes').value = data.serves;
        if (data.prep_time) document.getElementById('fieldPrepTime').value = data.prep_time;
        if (data.instructions_html) quill.root.innerHTML = data.instructions_html;

        const preview = document.getElementById('importedImagePreview');
        const pathField = document.getElementById('fieldImagePath');
        verbergConceptfoto();
        if (data.image_path) {
            pathField.value = data.image_path;
            preview.src = '/' + data.image_path;
            preview.classList.remove('hidden');
        }

        if (data.ingredients && data.ingredients.length > 0) {
            document.getElementById('ingredients').innerHTML = '';
            data.ingredients.forEach(ing => addIngredientRow(ing));
        }

        statusDiv.className = 'text-sm text-[#8B4513] flex items-center gap-2';
        banana.classList.add('hidden');
        statusText.textContent = `Herkend: ${data.ingredients?.length || 0} ingrediënten. Controleer en sla op.`;

    } catch (error) {
        clearTimeout(timeoutId);
        statusDiv.className = 'text-sm text-red-600 flex items-center gap-2';
        banana.classList.add('hidden');
        statusText.textContent = error.name === 'AbortError'
            ? 'Tijdlimiet overschreden. Probeer opnieuw.'
            : 'Fout: ' + error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Lees recept';
    }
}

/* ── Check Gemini API status on load ─────────────────────── */
(async function() {
    try {
        const resp = await fetch('/api/gemini/status');
        const data = await resp.json();
        if (!data.configured) {
            const btn = document.getElementById('photoSelectBtn');
            btn.disabled = true;
            btn.textContent = 'Foto import niet beschikbaar (API key ontbreekt)';
            btn.className = 'w-full py-3 border-2 border-dashed border-[#E8E4DC] rounded-lg text-[#9CA3AF] cursor-not-allowed text-sm';
        }
    } catch (e) {}
})();

/* ── URL Import ──────────────────────────────────────────── */
async function importFromUrl() {
    const url = document.getElementById('importUrlInput').value.trim();
    if (!url) return;

    const btn = document.getElementById('importBtn');
    const statusDiv = document.getElementById('importStatus');
    btn.disabled = true;
    btn.textContent = 'Bezig...';
    statusDiv.className = 'mt-2 text-sm text-[#6B6B6B]';
    statusDiv.textContent = 'Recept ophalen...';
    statusDiv.classList.remove('hidden');

    try {
        const response = await fetch('/recipe/scrape', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url})
        });
        const data = await response.json();

        if (data.status !== 'success') {
            statusDiv.className = 'mt-2 text-sm text-red-600';
            statusDiv.textContent = 'Fout: ' + data.message;
            return;
        }

        if (data.name)         document.getElementById('fieldName').value = data.name;
        if (data.serves)       document.getElementById('fieldServes').value = data.serves;
        if (data.prep_time)    document.getElementById('fieldPrepTime').value = data.prep_time;
        if (data.url)          document.getElementById('fieldUrl').value = data.url;
        if (data.instructions_html) quill.root.innerHTML = data.instructions_html;

        if (data.cookbook_exists && data.cookbook_id) {
            const sel = document.getElementById('fieldCookbook');
            if (!sel.querySelector(`option[value="${data.cookbook_id}"]`)) {
                const opt = document.createElement('option');
                opt.value = data.cookbook_id;
                opt.textContent = data.cookbook_name || '';
                const newOpt = sel.querySelector('option[value="__new__"]');
                sel.insertBefore(opt, newOpt);
            }
            sel.value = data.cookbook_id;
        } else if (!data.cookbook_exists && data.cookbook_name) {
            showCookbookSuggestion(data.cookbook_name);
        }

        const preview = document.getElementById('importedImagePreview');
        const pathField = document.getElementById('fieldImagePath');
        verbergConceptfoto();
        if (data.image_path) {
            pathField.value = data.image_path;
            preview.src = '/' + data.image_path;
            preview.classList.remove('hidden');
        } else {
            pathField.value = '';
            preview.classList.add('hidden');
        }

        if (data.ingredients && data.ingredients.length > 0) {
            document.getElementById('ingredients').innerHTML = '';
            data.ingredients.forEach(ing => addIngredientRow(ing));
        }

        statusDiv.className = 'mt-2 text-sm text-[#8B4513]';
        statusDiv.textContent = `Geïmporteerd: ${data.ingredients.length} ingrediënten. Controleer de velden en sla op.`;
    } catch (error) {
        statusDiv.className = 'mt-2 text-sm text-red-600';
        statusDiv.textContent = 'Fout: ' + error.message;
    } finally {
        btn.disabled = false;
        btn.textContent = 'Importeren';
    }
}

/* ── Bijsnijden van de conceptfoto, zelfde modal en eindpunt als de dump-pagina ── */
let _draftCrop = null;
/* Een foto- of linkimport ná het concept vervangt de foto: dan hoort het
   bijsnijden van het concept-origineel niet meer bij wat je ziet.
   fieldDraftId blijft met opzet staan — daar hangt aan dat het concept op
   'accepted' komt. Dat het origineel dan niet meegaat naar het recept beslist
   de server zelf, door het opgeslagen pad tegen dat van het concept te leggen;
   hier iets vergeten mag nooit een vreemde boekpagina opleveren. */
function verbergConceptfoto() {
    _draftCrop = null;
    document.getElementById('importedImageTools').classList.add('hidden');
}
function cropImportedImage() {
    if (!_draftCrop) return;
    openCropModal('/' + _draftCrop.source, `/dump/draft/${_draftCrop.id}/crop`, (newPath, origineel) => {
        // Na een draai is het bewaarde origineel een ander bestand; zonder dit
        // opent een tweede keer bijsnijden weer de ongedraaide pagina.
        if (origineel) {
            _draftCrop.source = origineel;
            const orig = document.getElementById('importedOriginalLink');
            if (orig) orig.href = '/' + origineel;
        }
        document.getElementById('fieldImagePath').value = newPath;
        document.getElementById('importedImagePreview').src = '/' + newPath + '?t=' + Date.now();
    });
}

/* ── Prefill vanuit een dump-draft (?draft=<id>) ── */
(async function() {
    const draftId = new URLSearchParams(location.search).get('draft');
    if (!draftId) return;
    try {
        const resp = await fetch(`/dump/draft/${draftId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        document.getElementById('fieldDraftId').value = draftId;
        if (data.name) document.getElementById('fieldName').value = data.name;
        if (data.serves) document.getElementById('fieldServes').value = data.serves;
        if (data.prep_time) document.getElementById('fieldPrepTime').value = data.prep_time;
        // Pagina en kookboek gingen hier verloren: wie een concept eerst
        // aanpaste, kreeg een recept zonder boek en zonder paginanummer,
        // terwijl 'Opslaan' die twee wel meenam.
        if (data.source_page) document.getElementById('fieldPage').value = data.source_page;
        const cookbook = new URLSearchParams(location.search).get('cookbook');
        if (cookbook) document.getElementById('fieldCookbook').value = cookbook;
        // instructions_html komt van de server: dezelfde omzetting als bij
        // 'Overnemen', zodat beide wegen dezelfde alinea's opleveren.
        if (data.instructions_html) quill.root.innerHTML = data.instructions_html;
        if (data.image_path) {
            document.getElementById('fieldImagePath').value = data.image_path;
            const preview = document.getElementById('importedImagePreview');
            preview.src = '/' + data.image_path;
            preview.classList.remove('hidden');
            _draftCrop = { id: draftId, source: data.original_image_path || data.image_path };
            document.getElementById('importedImageTools').classList.remove('hidden');
            const orig = document.getElementById('importedOriginalLink');
            orig.href = '/' + _draftCrop.source;
            orig.classList.remove('hidden');
            if (data.back_image_path) {
                const back = document.getElementById('importedBackLink');
                back.href = '/' + data.back_image_path;
                back.classList.remove('hidden');
            }
        }
        if (data.ingredients && data.ingredients.length > 0) {
            document.getElementById('ingredients').innerHTML = '';
            data.ingredients.forEach(ing => addIngredientRow(ing));
        }
    } catch (e) {}
})();
