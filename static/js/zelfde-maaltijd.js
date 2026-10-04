// Vraag of een recept dat al als los recept op de lijst staat dezelfde maaltijd
// is. Rutger koos (4 okt 2026) voor even vragen: stil overnemen laat een extra
// set wegvallen, stil optellen gaf in week 40 de chili dubbel.
// Gebruikt door het weekmenu, de receptenplanner en + Recept op /boodschappen.
// Getest in tests/js/zelfde_maaltijd.test.js.

// Een dubbelklik op de knop die dit venster opent landt anders op het venster
// zelf en kiest voor je; klikken zo kort na openen tellen daarom niet.
const ZM_WACHTTIJD_MS = 300;

// Geeft een Promise: 'zelfde', 'erbij', of null als je het wegklikt (Escape of
// naast het venster). Wat null betekent bepaalt de aanroeper.
function vraagZelfdeMaaltijd(recept, personen) {
    return new Promise(resolve => {
        const geopend = Date.now();
        const telt = () => Date.now() - geopend > ZM_WACHTTIJD_MS;

        const achter = document.createElement('div');
        achter.className = 'fixed inset-0 flex items-center justify-center px-4';
        achter.style.background = 'rgba(44,44,44,0.5)';
        achter.style.zIndex = '1000';     // boven de planpopup (200)

        const venster = achter.appendChild(document.createElement('div'));
        venster.setAttribute('role', 'dialog');
        venster.setAttribute('aria-modal', 'true');
        venster.setAttribute('aria-labelledby', 'zm-titel');
        venster.className = 'w-full max-w-sm rounded-lg bg-white p-5 shadow-lg';

        const titel = venster.appendChild(document.createElement('h2'));
        titel.id = 'zm-titel';
        titel.className = 'text-lg font-bold text-[#2C2C2C]';
        titel.textContent = 'Is dit dezelfde maaltijd?';

        const uitleg = venster.appendChild(document.createElement('p'));
        uitleg.className = 'mt-2 text-sm text-[#6B6B6B]';
        uitleg.textContent =
            `${recept} staat al als los recept voor ${personen} personen op je boodschappenlijst.`;

        const knoppen = venster.appendChild(document.createElement('div'));
        knoppen.className = 'mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end';
        const knop = (tekst, keuze, stijl) => {
            const k = knoppen.appendChild(document.createElement('button'));
            k.setAttribute('type', 'button');
            k.dataset.keuze = keuze;
            k.className = stijl;
            k.textContent = tekst;
            k.addEventListener('click', () => { if (telt()) klaar(keuze); });
            return k;
        };

        const klaar = keuze => {
            window.removeEventListener('keydown', toets, true);
            achter.remove();
            resolve(keuze);
        };
        // In de capture-fase en gestopt: anders sluit dezelfde Escape ook de
        // planpopup eronder, en lijkt het plannen geannuleerd terwijl het doorgaat.
        const toets = e => {
            if (e.key !== 'Escape') return;
            e.stopPropagation();
            e.preventDefault();
            klaar(null);
        };

        knop('Nee, komt erbij', 'erbij',
             'rounded border border-[#E8E4DC] px-4 py-2 text-sm text-[#2C2C2C]');
        const ja = knop('Ja, zelfde maaltijd', 'zelfde',
                        'rounded bg-[#2C2C2C] px-4 py-2 text-sm text-white');
        achter.addEventListener('click', e => {
            if (e.target === achter && telt()) klaar(null);
        });
        window.addEventListener('keydown', toets, true);
        document.body.appendChild(achter);
        ja.focus();
    });
}

// Het losse recept van die week voor dit recept, of undefined.
function losRecept(losseRecepten, recipeId, jaar, week) {
    return (losseRecepten || []).find(q =>
        q.recipe_id === Number(recipeId) && q.year === Number(jaar) && q.week === Number(week));
}

// Vraag het alleen als het recept die week al als los recept op de lijst staat.
// Geeft {keuze, los}: keuze is 'geen' (niets te vragen), 'zelfde', 'erbij' of
// 'annuleer' (weggeklikt).
async function kiesBijLosRecept(losseRecepten, recipeId, jaar, week, naam) {
    const los = losRecept(losseRecepten, recipeId, jaar, week);
    if (!los) return { keuze: 'geen' };
    const keuze = await vraagZelfdeMaaltijd(naam || los.recipe_name, los.people_count);
    return { keuze: keuze || 'annuleer', los };
}
