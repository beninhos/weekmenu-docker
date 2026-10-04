// Vraag of een recept dat al als los recept op de lijst staat dezelfde maaltijd
// is. Rutger koos (4 okt 2026) voor even vragen: stil overnemen laat een extra
// set wegvallen, stil optellen gaf in week 40 de chili dubbel.
// Gebruikt door het weekmenu, de receptenplanner en + Recept op /boodschappen.

// Geeft een Promise: 'zelfde', 'erbij', of null (Escape of naast het venster
// klikken; de aanroeper behandelt dat als 'erbij', dan telt alles zichtbaar mee).
function vraagZelfdeMaaltijd(recept, personen) {
    return new Promise(resolve => {
        const achter = document.createElement('div');
        achter.className = 'fixed inset-0 flex items-center justify-center px-4';
        achter.style.background = 'rgba(44,44,44,0.5)';
        achter.style.zIndex = '1000';     // boven de planpopup (200)
        achter.innerHTML = `
            <div role="dialog" aria-modal="true" aria-labelledby="zm-titel"
                 class="w-full max-w-sm rounded-lg bg-white p-5 shadow-lg">
                <h2 id="zm-titel" class="text-lg font-bold text-[#2C2C2C]">Is dit dezelfde maaltijd?</h2>
                <p class="mt-2 text-sm text-[#6B6B6B]"></p>
                <div class="mt-4 flex flex-col gap-2 sm:flex-row sm:justify-end">
                    <button type="button" data-keuze="erbij"
                            class="rounded border border-[#E8E4DC] px-4 py-2 text-sm text-[#2C2C2C]">Nee, komt erbij</button>
                    <button type="button" data-keuze="zelfde"
                            class="rounded bg-[#2C2C2C] px-4 py-2 text-sm text-white">Ja, zelfde maaltijd</button>
                </div>
            </div>`;
        achter.querySelector('p').textContent =
            `${recept} staat al als los recept voor ${personen} personen op je boodschappenlijst.`;

        const klaar = keuze => {
            document.removeEventListener('keydown', toets);
            achter.remove();
            resolve(keuze);
        };
        const toets = e => { if (e.key === 'Escape') klaar(null); };
        achter.addEventListener('click', e => {
            if (e.target === achter) { klaar(null); return; }
            const knop = e.target.closest('[data-keuze]');
            if (knop) klaar(knop.dataset.keuze);
        });
        document.addEventListener('keydown', toets);
        document.body.appendChild(achter);
        achter.querySelector('[data-keuze="zelfde"]').focus();
    });
}

// Het losse recept van die week voor dit recept, of undefined.
function losRecept(losseRecepten, recipeId, jaar, week) {
    return (losseRecepten || []).find(q =>
        q.recipe_id === Number(recipeId) && q.year === Number(jaar) && q.week === Number(week));
}
