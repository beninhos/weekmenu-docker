// Instellingen-pagina: AH-koppeling, API-sleutels, kookboek-CRUD.
// Vereist esc() uit utils.js.

/* ── Gemini key management ────────────────────────────────── */
async function geminiRefreshStatus() {
    try {
        const resp = await fetch('/api/gemini/status');
        const data = await resp.json();
        document.getElementById('geminiConnected').classList.toggle('hidden', !data.configured);
        document.getElementById('geminiDisconnected').classList.toggle('hidden', data.configured);
    } catch (e) {}
}

async function geminiSaveKey() {
    const key = document.getElementById('geminiKeyInput').value.trim();
    if (!key) return;
    const errDiv = document.getElementById('geminiSaveError');
    errDiv.classList.add('hidden');
    try {
        const resp = await fetch('/api/gemini/key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key})
        });
        const data = await resp.json();
        if (data.status === 'success') {
            document.getElementById('geminiKeyInput').value = '';
            geminiRefreshStatus();
        } else {
            errDiv.textContent = data.message || 'Opslaan mislukt';
            errDiv.classList.remove('hidden');
        }
    } catch (e) {
        errDiv.textContent = 'Netwerkfout: ' + e.message;
        errDiv.classList.remove('hidden');
    }
}

async function geminiRemoveKey() {
    if (!confirm('Gemini API key verwijderen?')) return;
    await fetch('/api/gemini/key', {method: 'DELETE'});
    geminiRefreshStatus();
}

geminiRefreshStatus();

/* ── Cloud Vision ────────────────────────────────────────── */
/* Elke statuswissel begint met een schone melding: anders blijft een
   waarschuwing van een vorige poging staan onder een leeg sleutelveld. */
function visionMelding(tekst, soort) {
    const div = document.getElementById('visionSaveError');
    div.classList.remove('text-red-600', 'text-amber-700');
    if (!tekst) {
        div.textContent = '';
        div.classList.add('hidden');
        return;
    }
    div.textContent = tekst;
    div.classList.add(soort === 'waarschuwing' ? 'text-amber-700' : 'text-red-600');
    div.classList.remove('hidden');
}

async function visionRefreshStatus() {
    visionMelding('');
    try {
        const data = await (await fetch('/api/vision/status')).json();
        document.getElementById('visionConnected').classList.toggle('hidden', !data.configured);
        document.getElementById('visionDisconnected').classList.toggle('hidden', data.configured);
    } catch (e) {}
}

async function visionSaveKey(button) {
    const key = document.getElementById('visionKeyInput').value.trim();
    if (!key) {
        visionMelding('Vul eerst een API key in.');
        return;
    }
    visionMelding('');
    // De sleutel wordt bij Cloud Vision uitgeprobeerd, dus dit duurt even.
    if (button) { button.disabled = true; button.textContent = 'Controleren...'; }
    try {
        const resp = await fetch('/api/vision/key', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key})
        });
        const data = await resp.json().catch(() => ({}));
        if (resp.ok && data.status === 'success') {
            document.getElementById('visionKeyInput').value = '';
            // Eerst verversen (dat wist de melding), dan pas waarschuwen.
            await visionRefreshStatus();
            if (data.warning) visionMelding(data.warning, 'waarschuwing');
        } else {
            visionMelding(data.message || `Opslaan mislukt (HTTP ${resp.status})`);
        }
    } catch (e) {
        visionMelding('Netwerkfout: ' + e.message);
    } finally {
        if (button) { button.disabled = false; button.textContent = 'Opslaan'; }
    }
}

async function visionRemoveKey() {
    if (!confirm('Cloud Vision API key verwijderen?')) return;
    await fetch('/api/vision/key', {method: 'DELETE'});
    visionRefreshStatus();
}

visionRefreshStatus();

async function importData(input) {
    const file = input.files[0];
    if (!file) return;

    const resultDiv = document.getElementById('importResult');
    resultDiv.className = 'mt-4 p-3 rounded text-sm bg-[#F5F2ED] text-[#6B6B6B]';
    resultDiv.textContent = 'Bezig met importeren...';
    resultDiv.classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/import', { method: 'POST', body: formData });
        const data = await response.json();

        if (data.status === 'success') {
            resultDiv.className = 'mt-4 p-3 rounded text-sm bg-[#FAF8F5] text-[#2C2C2C] border border-[#E8E4DC]';
            resultDiv.textContent = 'Import geslaagd: ' + data.message;
            // Ververs de statistieken na 1 seconde
            setTimeout(() => location.reload(), 1500);
        } else {
            resultDiv.className = 'mt-4 p-3 rounded text-sm bg-red-50 text-red-800 border border-red-200';
            resultDiv.textContent = 'Fout bij importeren: ' + data.message;
        }
    } catch (error) {
        resultDiv.className = 'mt-4 p-3 rounded text-sm bg-red-50 text-red-800 border border-red-200';
        resultDiv.textContent = 'Fout: ' + error.message;
    }

    input.value = '';
}

async function importZip(input) {
    const file = input.files[0];
    if (!file) return;

    const resultDiv = document.getElementById('importZipResult');
    resultDiv.className = 'mt-4 p-3 rounded text-sm bg-[#F5F2ED] text-[#6B6B6B]';
    resultDiv.textContent = 'Bezig met importeren...';
    resultDiv.classList.remove('hidden');

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/import/zip', { method: 'POST', body: formData });
        const data = await response.json();

        if (data.status === 'success') {
            resultDiv.className = 'mt-4 p-3 rounded text-sm bg-[#FAF8F5] text-[#2C2C2C] border border-[#E8E4DC]';
            resultDiv.textContent = 'Import geslaagd: ' + data.message;
            setTimeout(() => location.reload(), 1500);
        } else {
            resultDiv.className = 'mt-4 p-3 rounded text-sm bg-red-50 text-red-800 border border-red-200';
            resultDiv.textContent = 'Fout bij importeren: ' + data.message;
        }
    } catch (error) {
        resultDiv.className = 'mt-4 p-3 rounded text-sm bg-red-50 text-red-800 border border-red-200';
        resultDiv.textContent = 'Fout: ' + error.message;
    }

    input.value = '';
}
