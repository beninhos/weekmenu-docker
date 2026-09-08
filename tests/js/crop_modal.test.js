/* De bijsnijdmodal losgekoppeld naspelen.
 *
 * Wat hier getest wordt is rekenwerk: welke fracties de modal naar de server
 * stuurt. Cropper.js zelf heeft een browser met echte afmetingen nodig, dus
 * staat hier een nagebouwde cropper die de afspraken van cropperjs 1.6.2
 * aanhoudt die de modal gebruikt:
 *
 *   - getData() geeft het cropvak in pixels van het GEDRAAIDE beeld:
 *     x = (cropvak.left - canvas.left) / schaal, schaal = canvas.width /
 *     canvas.naturalWidth  (cropper.js r2526 e.v.)
 *   - een kwartslag verwisselt canvas.naturalWidth en -Height en schaalt het
 *     canvas evenredig mee  (r1301 e.v.)
 *   - viewMode 1 laat het canvas nooit kleiner worden dan het cropvak
 *     (limitCanvas, r1237 e.v.) -- precies de reden dat de modal het cropvak
 *     eerst tot 1x1 krimpt voordat hij draait.
 *
 * Draaien met: node tests/js/crop_modal.test.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const WORTEL = path.resolve(__dirname, '..', '..');

/** De modal-code, waar hij ook staat.
 *
 * Sinds deze versie is het een los bestand; daarvoor stond dezelfde code in
 * het sjabloon. De test leest allebei, zodat hij ook op de vorige versie een
 * echte uitkomst meet in plaats van te struikelen over een ontbrekend pad.
 */
function leesModalCode() {
    const losBestand = path.join(WORTEL, 'static', 'js', 'crop-modal.js');
    if (fs.existsSync(losBestand)) return fs.readFileSync(losBestand, 'utf8');
    const sjabloon = fs.readFileSync(
        path.join(WORTEL, 'templates', '_crop_modal.html'), 'utf8');
    const blokken = [...sjabloon.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
    assert.ok(blokken.length, 'geen scriptblok in _crop_modal.html gevonden');
    return blokken.map(m => m[1]).join('\n');
}

// --- de nagebouwde cropper ------------------------------------------------

class NagebouwdeCropper {
    constructor(img, opties) {
        this.opties = opties || {};
        this.container = { width: 600, height: 400 };
        const nb = img.natuurlijkeBreedte, nh = img.natuurlijkeHoogte;
        const schaal = Math.min(this.container.width / nb, this.container.height / nh);
        this.canvas = {
            width: nb * schaal, height: nh * schaal,
            naturalWidth: nb, naturalHeight: nh,
        };
        this.canvas.left = (this.container.width - this.canvas.width) / 2;
        this.canvas.top = (this.container.height - this.canvas.height) / 2;
        this.rotatie = 0;
        const deel = this.opties.autoCropArea === undefined ? 0.8 : this.opties.autoCropArea;
        this.cropvak = {
            left: this.canvas.left + this.canvas.width * (1 - deel) / 2,
            top: this.canvas.top + this.canvas.height * (1 - deel) / 2,
            width: this.canvas.width * deel, height: this.canvas.height * deel,
        };
        this.kapot = false;
        if (this.opties.ready) this.opties.ready.call({ cropper: this });
    }

    getContainerData() { return Object.assign({}, this.container); }
    getCanvasData() { return Object.assign({}, this.canvas); }
    getCropBoxData() { return Object.assign({}, this.cropvak); }

    /** viewMode 1: het canvas mag niet kleiner worden dan het cropvak. */
    _ondergrens() {
        const verhouding = this.canvas.naturalWidth / this.canvas.naturalHeight;
        let b = this.cropvak.width, h = this.cropvak.height;
        if (h * verhouding > b) b = h * verhouding; else h = b / verhouding;
        return { width: b, height: h };
    }

    setCanvasData(d) {
        const grens = this._ondergrens();
        let breedte = Math.max(d.width, grens.width);
        let hoogte = Math.max(d.height, grens.height);
        // cropper houdt de verhouding vast aan de breedte
        hoogte = breedte / (this.canvas.naturalWidth / this.canvas.naturalHeight);
        if (hoogte < grens.height) {
            hoogte = grens.height;
            breedte = hoogte * (this.canvas.naturalWidth / this.canvas.naturalHeight);
        }
        this.canvas.width = breedte;
        this.canvas.height = hoogte;
        if (d.left !== undefined) this.canvas.left = d.left;
        if (d.top !== undefined) this.canvas.top = d.top;
    }

    setCropBoxData(d) {
        const breedte = Math.min(d.width, this.canvas.width);
        const hoogte = Math.min(d.height, this.canvas.height);
        const links = Math.min(Math.max(d.left, this.canvas.left),
                               this.canvas.left + this.canvas.width - breedte);
        const boven = Math.min(Math.max(d.top, this.canvas.top),
                               this.canvas.top + this.canvas.height - hoogte);
        this.cropvak = { left: links, top: boven, width: breedte, height: hoogte };
    }

    rotate(graden) {
        this.rotatie += graden;
        const kwartslag = Math.abs(graden / 90) % 2 === 1;
        const midden = { x: this.canvas.left + this.canvas.width / 2,
                         y: this.canvas.top + this.canvas.height / 2 };
        if (kwartslag) {
            const b = this.canvas.naturalWidth;
            this.canvas.naturalWidth = this.canvas.naturalHeight;
            this.canvas.naturalHeight = b;
            const oud = this.canvas.width;
            this.canvas.width = this.canvas.height;
            this.canvas.height = oud;
        }
        const grens = this._ondergrens();
        if (this.canvas.width < grens.width) {
            this.canvas.width = grens.width;
            this.canvas.height = grens.height;
        }
        this.canvas.left = midden.x - this.canvas.width / 2;
        this.canvas.top = midden.y - this.canvas.height / 2;
    }

    getData() {
        const schaal = this.canvas.width / this.canvas.naturalWidth;
        return {
            x: (this.cropvak.left - this.canvas.left) / schaal,
            y: (this.cropvak.top - this.canvas.top) / schaal,
            width: this.cropvak.width / schaal,
            height: this.cropvak.height / schaal,
            rotate: this.rotatie,
        };
    }

    destroy() { this.kapot = true; }
}

// --- de nagebouwde pagina -------------------------------------------------

function maakOmgeving(beeld) {
    const elementen = {};
    const maakElement = (id) => ({
        id,
        classList: {
            _set: new Set(),
            add(k) { this._set.add(k); },
            remove(k) { this._set.delete(k); },
            contains(k) { return this._set.has(k); },
        },
        textContent: '',
        set src(waarde) {
            this._src = waarde;
            if (this.onload) this.onload();
        },
        get src() { return this._src; },
        natuurlijkeBreedte: beeld.breedte,
        natuurlijkeHoogte: beeld.hoogte,
    });
    for (const id of ['cropImage', 'cropError', 'cropModal']) elementen[id] = maakElement(id);

    const verstuurd = [];
    const sandbox = {
        document: { getElementById: (id) => elementen[id] || null },
        Cropper: NagebouwdeCropper,
        Date,
        Math,
        JSON,
        console,
        fetch: async (url, opties) => {
            verstuurd.push({ url, body: JSON.parse(opties.body) });
            return { ok: true, json: async () => ({ status: 'success',
                                                    image_path: 'static/uploads/nieuw.jpg' }) };
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(leesModalCode(), sandbox);
    // `let _cropper` staat in de lexicale scope van het script, niet op het
    // globale object; een tweede stukje code in dezelfde context komt er wel
    // bij. Zo hoeft de modal zelf niets voor de test prijs te geven.
    const cropper = () => vm.runInContext('_cropper', sandbox);
    return { sandbox, elementen, verstuurd, cropper };
}

function open(omgeving) {
    omgeving.sandbox.openCropModal('/static/uploads/pagina.jpg', '/recipe/1/crop', null);
    return omgeving.cropper();
}

// --- de tests -------------------------------------------------------------

const tests = [];
function test(naam, fn) { tests.push([naam, fn]); }

function ongeveer(gemeten, verwacht, marge = 0.005) {
    return Math.abs(gemeten - verwacht) <= marge;
}

test('alleen openen en opslaan snijdt niets af', async () => {
    const o = maakOmgeving({ breedte: 800, hoogte: 1200 });
    open(o);
    await o.sandbox.saveCropModal();
    const body = o.verstuurd[0].body;
    assert.ok(ongeveer(body.x, 0) && ongeveer(body.y, 0),
              `linksboven moet 0,0 zijn, was ${body.x},${body.y}`);
    assert.ok(ongeveer(body.width, 1) && ongeveer(body.height, 1),
              `het hele beeld moet mee, was ${body.width}x${body.height}`);
});

test('alleen rechtzetten snijdt niets af', async () => {
    const o = maakOmgeving({ breedte: 800, hoogte: 1200 });
    open(o);
    o.sandbox.draaiCropModal(90);
    await o.sandbox.saveCropModal();
    const body = o.verstuurd[0].body;
    assert.strictEqual(body.rotate, 90);
    assert.ok(ongeveer(body.x, 0) && ongeveer(body.y, 0),
              `linksboven moet 0,0 zijn, was ${body.x},${body.y}`);
    assert.ok(ongeveer(body.width, 1) && ongeveer(body.height, 1),
              `het hele beeld moet mee, was ${body.width}x${body.height}`);
});

test('twee kwartslagen snijden ook niets af', async () => {
    const o = maakOmgeving({ breedte: 800, hoogte: 1200 });
    open(o);
    o.sandbox.draaiCropModal(90);
    o.sandbox.draaiCropModal(90);
    await o.sandbox.saveCropModal();
    const body = o.verstuurd[0].body;
    assert.strictEqual(body.rotate, 180);
    assert.ok(ongeveer(body.width, 1) && ongeveer(body.height, 1),
              `het hele beeld moet mee, was ${body.width}x${body.height}`);
});

test('na een draai past het beeld nog in het venster', async () => {
    // De reden dat het cropvak eerst tot 1x1 krimpt: met viewMode 1 zou het
    // canvas anders niet meer terug mogen schalen en zou een deel van de
    // pagina buiten beeld vallen, onbereikbaar voor het cropvak.
    const o = maakOmgeving({ breedte: 800, hoogte: 1200 });
    open(o);
    o.sandbox.draaiCropModal(90);
    const c = o.cropper();
    const container = c.getContainerData(), canvas = c.getCanvasData();
    assert.ok(canvas.width <= container.width + 0.5,
              `canvas ${canvas.width} breder dan venster ${container.width}`);
    assert.ok(canvas.height <= container.height + 0.5,
              `canvas ${canvas.height} hoger dan venster ${container.height}`);
});

test('een eigen selectie gaat onveranderd mee', async () => {
    const o = maakOmgeving({ breedte: 800, hoogte: 1200 });
    open(o);
    const c = o.cropper();
    const canvas = c.getCanvasData();
    c.setCropBoxData({ left: canvas.left, top: canvas.top,
                       width: canvas.width / 2, height: canvas.height });
    await o.sandbox.saveCropModal();
    const body = o.verstuurd[0].body;
    assert.ok(ongeveer(body.width, 0.5), `halve breedte verwacht, was ${body.width}`);
    assert.ok(ongeveer(body.height, 1), `hele hoogte verwacht, was ${body.height}`);
});

(async () => {
    let mislukt = 0;
    for (const [naam, fn] of tests) {
        try {
            await fn();
            console.log('ok   - ' + naam);
        } catch (e) {
            mislukt++;
            console.log('FOUT - ' + naam + '\n       ' + e.message);
        }
    }
    console.log(`${tests.length - mislukt}/${tests.length} geslaagd`);
    process.exit(mislukt ? 1 : 0);
})();
