/* Het venster 'Is dit dezelfde maaltijd?' losgekoppeld naspelen.
 *
 * Wat hier getest wordt is de keuze die het venster teruggeeft, niet hoe het
 * eruitziet (dat vraagt een browser). Twee dingen uit de eindreview van 4 okt
 * 2026: wegklikken (Escape of naast het venster) is annuleren en mag niet
 * stil 'komt erbij' kiezen, en een dubbelklik op de knop die het venster
 * opende mag het niet meteen beantwoorden.
 *
 * Draaien met: node tests/js/zelfde_maaltijd.test.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const WORTEL = path.resolve(__dirname, '..', '..');

// --- een nagebouwde DOM: net genoeg voor het venster ----------------------

class Element {
    constructor(tag) {
        this.tag = tag;
        this.children = [];
        this.luisteraars = {};
        this.style = {};
        this.attributen = {};
        this.dataset = {};
        this.textContent = '';
        this.className = '';
        this.weg = false;
    }
    appendChild(kind) { kind.ouder = this; this.children.push(kind); return kind; }
    setAttribute(naam, waarde) { this.attributen[naam] = waarde; }
    addEventListener(type, f) { (this.luisteraars[type] = this.luisteraars[type] || []).push(f); }
    remove() { this.weg = true; }
    focus() { this.gefocust = true; }
    klik(doel) { (this.luisteraars.click || []).forEach(f => f({ target: doel || this })); }
    *alles() { yield this; for (const k of this.children) yield* k.alles(); }
}

function maakWereld() {
    const body = new Element('body');
    const venster = { luisteraars: [] };
    venster.addEventListener = (type, f, vangen) => venster.luisteraars.push({ type, f, vangen });
    venster.removeEventListener = (type, f, vangen) => {
        venster.luisteraars = venster.luisteraars.filter(l => !(l.type === type && l.f === f && l.vangen === vangen));
    };
    const klok = { nu: 1000 };
    const wereld = {
        document: { createElement: tag => new Element(tag), body },
        window: venster,
        Date: { now: () => klok.nu },
        Promise, Number,
    };
    vm.createContext(wereld);
    vm.runInContext(fs.readFileSync(path.join(WORTEL, 'static', 'js', 'zelfde-maaltijd.js'), 'utf8'), wereld);
    const achtergrond = () => body.children[body.children.length - 1];
    const knop = keuze => [...achtergrond().alles()].find(e => e.dataset.keuze === keuze);
    const toets = sleutel => {
        const e = { key: sleutel, gestopt: false, stopPropagation() { this.gestopt = true; },
                    preventDefault() {} };
        venster.luisteraars.filter(l => l.type === 'keydown').forEach(l => l.f(e));
        return e;
    };
    return { wereld, body, venster, klok, achtergrond, knop, toets };
}

const LOS = [{ id: 7, recipe_id: 18, recipe_name: 'Chili con carne', people_count: 12,
               year: 2026, week: 40 }];

async function nogOpen(belofte) {
    const uit = await Promise.race([belofte, new Promise(r => setTimeout(() => r('open'), 10))]);
    return uit === 'open';
}

async function toetsen() {
    // Geen los recept die week: niets vragen.
    {
        const w = maakWereld();
        const uit = await w.wereld.kiesBijLosRecept(LOS, 18, 2026, 41, 'Chili con carne');
        assert.deepStrictEqual(uit.keuze, 'geen');
        assert.strictEqual(w.body.children.length, 0, 'geen venster als er niets te vragen is');
    }
    // 'Ja, zelfde maaltijd' geeft het losse recept terug; id als tekst mag ook.
    {
        const w = maakWereld();
        const belofte = w.wereld.kiesBijLosRecept(LOS, '18', 2026, 40, 'Chili con carne');
        w.klok.nu += 500;
        w.knop('zelfde').klik();
        const uit = await belofte;
        assert.strictEqual(uit.keuze, 'zelfde');
        assert.strictEqual(uit.los.id, 7);
        assert.ok(w.achtergrond().weg, 'het venster gaat weg');
    }
    // Een dubbelklik vlak na openen kiest niets, op de achtergrond noch op een knop.
    {
        const w = maakWereld();
        const belofte = w.wereld.kiesBijLosRecept(LOS, 18, 2026, 40, 'Chili con carne');
        w.klok.nu += 50;
        w.achtergrond().klik();
        w.knop('erbij').klik();
        assert.ok(await nogOpen(belofte), 'een klik binnen 300 ms beantwoordt de vraag niet');
        w.klok.nu += 400;
        w.achtergrond().klik();
        assert.strictEqual((await belofte).keuze, 'annuleer', 'naast het venster klikken is annuleren');
    }
    // Escape is annuleren, en gaat niet ook nog naar de planpopup eronder.
    {
        const w = maakWereld();
        const belofte = w.wereld.kiesBijLosRecept(LOS, 18, 2026, 40, 'Chili con carne');
        assert.ok(w.venster.luisteraars.some(l => l.type === 'keydown' && l.vangen === true),
                  'Escape wordt in de capture-fase afgevangen, voor de andere luisteraars');
        const e = w.toets('Escape');
        assert.strictEqual((await belofte).keuze, 'annuleer');
        assert.ok(e.gestopt, 'de Escape gaat niet door naar de planpopup');
        assert.strictEqual(w.venster.luisteraars.length, 0, 'de luisteraar is weer weg');
    }
    // 'Nee, komt erbij' na de wachttijd.
    {
        const w = maakWereld();
        const belofte = w.wereld.kiesBijLosRecept(LOS, 18, 2026, 40);
        w.klok.nu += 301;
        w.knop('erbij').klik();
        assert.strictEqual((await belofte).keuze, 'erbij');
    }
    console.log('zelfde-maaltijd: alle toetsen geslaagd');
}

toetsen().catch(fout => { console.error(fout); process.exit(1); });
