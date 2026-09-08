/* De bijsnijdmodal: cropper opzetten, draaien, en de fracties versturen.
 *
 * Hoort bij templates/_crop_modal.html; los bestand omdat het rekenwerk
 * (welke fracties gaan er naar de server) getest wordt in
 * tests/js/crop_modal.test.js.
 *
 * openCropModal(srcUrl, saveUrl, onSaved) — onSaved krijgt het nieuwe
 * afbeeldingspad en het nieuwe pad van de bewaarde volledige pagina; die
 * tweede verandert zodra er gedraaid is, en de aanroeper moet zijn
 * bijsnijdknop daarop bijwerken.
 */
let _cropper = null, _cropSaveUrl = null, _cropOnSaved = null, _cropBasisRotatie = 0;

function openCropModal(srcUrl, saveUrl, onSaved) {
    _cropSaveUrl = saveUrl;
    _cropOnSaved = onSaved;
    _cropBasisRotatie = 0;
    const img = document.getElementById('cropImage');
    document.getElementById('cropError').classList.add('hidden');
    document.getElementById('cropModal').classList.remove('hidden');
    if (_cropper) { _cropper.destroy(); _cropper = null; }
    img.onload = () => {
        if (typeof Cropper === 'undefined') {
            showCropModalError('Bijsnijden niet beschikbaar (library niet geladen)');
            return;
        }
        _cropper = new Cropper(img, {
            // viewMode 1 blijft staan: het cropvak mag het beeld niet uit, dat
            // scheelt onzinselecties. Het nadeel ervan (na een draai houdt
            // cropper de oude pixelschaal aan, valt een deel van het beeld
            // buiten het venster en is het met viewMode 1 niet meer aan te
            // wijzen) vangt _pasCropKaderAan() op door het canvas zelf terug
            // in de container te schalen.
            viewMode: 1,
            // Het hele beeld staat aangevinkt bij het openen. Met de vorige
            // 0.8 sneed 'even rechtzetten en opslaan' er een tiende aan elke
            // kant af zonder dat iemand het aanwees; wie minder wil, sleept
            // het kader zelf kleiner.
            autoCropArea: 1,
            ready() {
                // Cropper past de EXIF-oriëntatie zelf toe, als een draai. Die
                // stand is het NULPUNT: de server zet het beeld met
                // exif_transpose in precies dezelfde stand. Alleen wat de
                // gebruiker daarna zélf draait mag mee naar de server, anders
                // draait die dubbel. Bij een foto die sinds deze versie is
                // ingelezen zit er geen EXIF-draai meer in en is de basis 0.
                const c = this.cropper || _cropper;
                _cropBasisRotatie = (c && c.getData().rotate) || 0;
            },
        });
    };
    img.src = srcUrl + (srcUrl.includes('?') ? '&' : '?') + 't=' + Date.now();
}

function closeCropModal() {
    if (_cropper) { _cropper.destroy(); _cropper = null; }
    document.getElementById('cropModal').classList.add('hidden');
    document.getElementById('cropImage').src = '';
}

function showCropModalError(msg) {
    const el = document.getElementById('cropError');
    el.textContent = msg;
    el.classList.remove('hidden');
}

function draaiCropModal(graden) {
    if (!_cropper) return;
    const container = _cropper.getContainerData();
    // Eerst het cropvak minimaal maken: met viewMode 1 mag het canvas nooit
    // kleiner worden dan het cropvak, en dan zou het terugschalen hieronder
    // juist inzoomen in plaats van uit.
    _cropper.setCropBoxData({ left: container.width / 2, top: container.height / 2,
                              width: 1, height: 1 });
    _cropper.rotate(graden);
    _pasCropKaderAan();
}

function _pasCropKaderAan() {
    const container = _cropper.getContainerData();
    const canvas = _cropper.getCanvasData();
    const schaal = Math.min(container.width / canvas.naturalWidth,
                            container.height / canvas.naturalHeight);
    const breedte = canvas.naturalWidth * schaal, hoogte = canvas.naturalHeight * schaal;
    _cropper.setCanvasData({
        left: (container.width - breedte) / 2, top: (container.height - hoogte) / 2,
        width: breedte, height: hoogte,
    });
    // En het kader beslaat weer het hele beeld. Het krimpen hierboven was een
    // truc om het canvas te mogen uitzoomen, geen keuze van de gebruiker; wie
    // alleen rechtzet hoort niets kwijt te raken.
    const nieuw = _cropper.getCanvasData();
    _cropper.setCropBoxData({
        left: nieuw.left, top: nieuw.top,
        width: nieuw.width, height: nieuw.height,
    });
}

async function saveCropModal() {
    if (!_cropper) return;
    const cd = _cropper.getData();
    // Delen door het GEDRAAIDE kader. getCanvasData() geeft de afmetingen van
    // het beeld zoals het nu staat -- bij een kwartslag zijn breedte en hoogte
    // verwisseld -- en getData() rekent tegen datzelfde kader. getImageData()
    // geeft de ongedraaide bestandsmaat en leverde bij oriëntatie 6/8 fracties
    // boven de 1 op, waar de server terecht een 400 op gaf.
    const kader = _cropper.getCanvasData();
    const klem = (v) => Math.min(1, Math.max(0, v));
    // Klemmen op [0,1]: een cropvak dat een paar pixels buiten het beeld steekt
    // mag geen foutmelding opleveren, alleen een iets kleinere uitsnede.
    const links = Math.min(klem(cd.x / kader.naturalWidth), 0.999);
    const boven = Math.min(klem(cd.y / kader.naturalHeight), 0.999);
    const rechts = klem((cd.x + cd.width) / kader.naturalWidth);
    const onder = klem((cd.y + cd.height) / kader.naturalHeight);
    const body = {
        x: links, y: boven,
        width: Math.max(rechts - links, 0.001),
        height: Math.max(onder - boven, 0.001),
        rotate: (cd.rotate || 0) - _cropBasisRotatie,
    };
    try {
        const resp = await fetch(_cropSaveUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await resp.json();
        if (!resp.ok || data.status !== 'success') {
            showCropModalError(data.message || 'Bijsnijden mislukt');
            return;
        }
        if (_cropOnSaved) _cropOnSaved(data.image_path, data.original_image_path);
        closeCropModal();
    } catch (err) {
        showCropModalError('Bijsnijden mislukt: ' + err.message);
    }
}
